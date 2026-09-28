"""Document parsing and authorized hybrid retrieval; one process owns local Qdrant."""
import json
import os
import re
import threading
import subprocess
import uuid
from pathlib import Path
from typing import Annotated

import fitz
import httpx
import jieba
from bs4 import BeautifulSoup
from fastapi import FastAPI, Header, HTTPException, Depends
from pydantic import BaseModel, Field
from qdrant_client import QdrantClient, models
from rank_bm25 import BM25Okapi

ROOT = Path(os.environ.get('APP_ROOT', Path(__file__).resolve().parents[1]))
CONFIG = json.loads((ROOT / '.runtime/config.json').read_text())
DATA = ROOT / '.runtime/rag'
DATA.mkdir(parents=True, exist_ok=True)
LOCK = threading.RLock()
client = QdrantClient(path=str(DATA / 'vectors'))
COLLECTION = 'financial_chunks'
if not client.collection_exists(COLLECTION):
    client.create_collection(COLLECTION, vectors_config=models.VectorParams(size=1024, distance=models.Distance.COSINE))
app = FastAPI(title='Financial document retrieval', docs_url=None, redoc_url=None)


def authorize(x_internal_token: Annotated[str | None, Header()] = None):
    import secrets
    if not x_internal_token or not secrets.compare_digest(x_internal_token, CONFIG['INTERNAL_TOKEN']):
        raise HTTPException(403, 'Internal service only')


class IndexInput(BaseModel):
    document_id: int
    owner_id: int
    filename: str
    path: str


class SearchInput(BaseModel):
    owner_id: int
    document_ids: list[int] = Field(min_length=1, max_length=20)
    query: str = Field(min_length=1, max_length=2000)


class ReadInput(BaseModel):
    owner_id: int
    document_ids: list[int]
    chunk_id: str


def tokens(text):
    return [s.lower() for s in jieba.lcut(text) if s.strip() and re.search(r'\w', s)]


def split_text(text, max_chars=1600):
    """Prefer line boundaries; repeat preceding context for long tables/paragraphs."""
    text = re.sub(r'[ \t]+', ' ', text).strip()
    parts, current = [], ''
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        for start in range(0, len(line), max_chars):
            segment = line[start:start + max_chars]
            if current and len(current) + len(segment) > max_chars:
                parts.append(current)
                current = current[-160:] + '\n'
            current += segment + '\n'
    if current.strip():
        parts.append(current.strip())
    return parts


def parse_document(path: Path, filename: str):
    suffix = path.suffix.lower()
    sections = []
    if suffix == '.pdf':
        with fitz.open(path) as pdf:
            if len(pdf) > 600:
                raise ValueError('PDF exceeds 600 pages')
            for number, page in enumerate(pdf, 1):
                text = page.get_text(sort=True).strip()
                if text:
                    sections.append((number, f'第 {number} 页', text))
    elif suffix in ('.html', '.htm'):
        soup = BeautifulSoup(path.read_text(encoding='utf-8'), 'html.parser')
        for unsafe in soup(['script', 'style', 'iframe', 'noscript']):
            unsafe.decompose()
        title = soup.title.get_text(' ', strip=True) if soup.title else filename
        text = soup.get_text('\n', strip=True)
        sections = [(None, f'{title} · 段落 {i}', block) for i, block in enumerate(split_text(text, 1600), 1)]
    elif suffix == '.txt':
        text = path.read_text(encoding='utf-8')
        sections = [(None, f'段落 {i}', block) for i, block in enumerate(split_text(text, 1600), 1)]
    elif suffix in ('.png', '.jpg', '.jpeg'):
        sections = [(None, '图片文字识别（OCR，请核对原图）', recognize_image(path))]
    else:
        raise ValueError('Only PDF, HTML, UTF-8 TXT, PNG and JPG are supported')
    chunks = []
    for page, anchor, content in sections:
        for part in split_text(content):
            chunks.append({'page': page, 'anchor': anchor, 'text': part})
    if not chunks:
        raise ValueError('No text found; scanned PDFs require OCR, which is not enabled')
    if len(chunks) > 3000:
        raise ValueError('Document exceeds 3000 chunks')
    return chunks


def recognize_image(path: Path):
    binary = ROOT / '.runtime/bin/vision-ocr'
    if not binary.is_file():
        raise ValueError('图片 OCR 未安装，请在 macOS 上运行 scripts/build.sh')
    try:
        result = subprocess.run([str(binary), str(path)], capture_output=True, text=True, timeout=60, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ValueError('图片文字识别超时，请裁剪图片后重试') from exc
    if result.returncode:
        raise ValueError('图片无法识别：请使用有效 PNG/JPG，尺寸不超过 3200 万像素、单边 16000 像素')
    text = json.loads(result.stdout)['text'].strip()
    if not text:
        raise ValueError('图片未识别到文字，请上传清晰的文档截图；不支持纯图形分析')
    return text


def embed(texts):
    vectors = []
    with httpx.Client(timeout=60) as http:
        for start in range(0, len(texts), 10):
            response = http.post(CONFIG['LLM_BASE_URL'] + '/embeddings', headers={'Authorization': 'Bearer ' + CONFIG['LLM_API_KEY']}, json={'model': CONFIG['EMBEDDING_MODEL'], 'input': texts[start:start+10], 'dimensions': 1024})
            if response.status_code != 200:
                raise RuntimeError(f'Embedding provider returned HTTP {response.status_code}')
            rows = sorted(response.json()['data'], key=lambda item: item['index'])
            if len(rows) != len(texts[start:start+10]):
                raise RuntimeError('Embedding count mismatch')
            vectors.extend(row['embedding'] for row in rows)
    return vectors


def rrf(dense_ids, sparse_ids, k=60):
    scores = {}
    for ranked in (dense_ids, sparse_ids):
        for rank, chunk_id in enumerate(ranked, 1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (k + rank)
    return sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))


def load_chunks(owner, document_ids):
    chunks = []
    for document in document_ids:
        path = DATA / f'{owner}_{document}.json'
        if not path.exists():
            raise HTTPException(409, 'Document is not indexed')
        chunks.extend(json.loads(path.read_text()))
    return chunks


@app.get('/health')
def health():
    return {'status': 'UP', 'storage': 'qdrant-local', 'embedding_model': CONFIG['EMBEDDING_MODEL']}


@app.post('/index', dependencies=[Depends(authorize)])
def index(body: IndexInput):
    path = Path(body.path).resolve()
    if not path.is_relative_to((ROOT / '.runtime/uploads').resolve()) or not path.is_file():
        raise HTTPException(400, 'Invalid upload path')
    try:
        chunks = parse_document(path, body.filename)
        for i, chunk in enumerate(chunks):
            chunk.update({'id': str(uuid.uuid5(uuid.NAMESPACE_URL, f'{body.owner_id}/{body.document_id}/{i}')), 'owner_id': body.owner_id, 'document_id': body.document_id, 'filename': body.filename})
        vectors = embed([chunk['text'] for chunk in chunks])
        with LOCK:
            client.upsert(COLLECTION, [models.PointStruct(id=chunk['id'], vector=vector, payload=chunk) for chunk, vector in zip(chunks, vectors)])
            destination = DATA / f'{body.owner_id}_{body.document_id}.json'
            temporary = destination.with_suffix('.tmp')
            temporary.write_text(json.dumps(chunks, ensure_ascii=False))
            temporary.replace(destination)
        return {'chunks': len(chunks), 'pages': len({c['page'] for c in chunks if c['page']})}
    except (ValueError, RuntimeError, httpx.HTTPError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post('/search', dependencies=[Depends(authorize)])
def search(body: SearchInput):
    chunks = load_chunks(body.owner_id, body.document_ids)
    vector = embed([body.query])[0]
    with LOCK:
        hits = client.query_points(COLLECTION, query=vector, limit=20, query_filter=models.Filter(must=[models.FieldCondition(key='owner_id', match=models.MatchValue(value=body.owner_id)), models.FieldCondition(key='document_id', match=models.MatchAny(any=body.document_ids))])).points
    corpus = [tokens(c['text']) or ['_'] for c in chunks]
    scores = BM25Okapi(corpus).get_scores(tokens(body.query))
    sparse = sorted(range(len(chunks)), key=lambda i: -scores[i])[:20]
    ids = rrf([str(hit.id) for hit in hits], [chunks[i]['id'] for i in sparse if scores[i] > 0])[:8]
    by_id = {c['id']: c for c in chunks}
    return {'query': body.query, 'method': 'BM25 + dense / RRF', 'hits': [by_id[i] for i in ids]}


@app.post('/read', dependencies=[Depends(authorize)])
def read(body: ReadInput):
    for chunk in load_chunks(body.owner_id, body.document_ids):
        if chunk['id'] == body.chunk_id:
            return chunk
    raise HTTPException(404, 'Chunk not found in authorized documents')


class SourceInput(BaseModel):
    owner_id: int
    document_id: int


@app.post('/source', dependencies=[Depends(authorize)])
def source(body: SourceInput):
    return {'chunks': load_chunks(body.owner_id, [body.document_id])}


@app.post('/delete', dependencies=[Depends(authorize)])
def delete(body: SourceInput):
    with LOCK:
        client.delete(COLLECTION, points_selector=models.FilterSelector(filter=models.Filter(must=[
            models.FieldCondition(key='owner_id', match=models.MatchValue(value=body.owner_id)),
            models.FieldCondition(key='document_id', match=models.MatchValue(value=body.document_id))
        ])))
        (DATA / f'{body.owner_id}_{body.document_id}.json').unlink(missing_ok=True)
    return {'ok': True}
