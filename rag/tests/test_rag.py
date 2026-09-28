import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import pytest
from fastapi.testclient import TestClient

PROJECT=Path(__file__).resolve().parents[2]
TEMP=tempfile.TemporaryDirectory()
root=Path(TEMP.name)
(root/'.runtime').mkdir()
(root/'.runtime/config.json').write_text((PROJECT/'.runtime/config.json').read_text())
os.environ['APP_ROOT']=str(root)
sys.path.insert(0,str(PROJECT/'rag'))
rag=importlib.import_module('app')
client=TestClient(rag.app)


def test_chinese_tokens():
    result=rag.tokens('营业收入 Revenue 2025')
    assert '2025' in result and 'revenue' in result and len(result)>2


def test_rrf_agreement_wins():
    assert rag.rrf(['a','b'],['b','c'])[0]=='b'


def test_split_preserves_content():
    text='第一段收入 100 万元\n第二段成本 80 万元\n'+'内容'*1800
    chunks=rag.split_text(text)
    assert len(chunks)>1 and '100 万元' in chunks[0]
    assert all(len(c)<=1800 for c in chunks)


def test_html_drops_instructions_in_scripts(tmp_path):
    p=tmp_path/'x.html';p.write_text('<title>年报</title><script>steal_secret()</script><p>收入100万元</p>')
    chunks=rag.parse_document(p,p.name)
    assert 'steal_secret' not in str(chunks)
    assert '收入100万元' in str(chunks)


def test_txt_and_empty(tmp_path):
    p=tmp_path/'x.txt';p.write_text('营业收入 123 万元\n单位：万元')
    assert rag.parse_document(p,p.name)[0]['page'] is None
    p.write_text('')
    with pytest.raises(ValueError,match='No text'):rag.parse_document(p,p.name)


def test_pdf_real_page_anchor(tmp_path):
    p=tmp_path/'x.pdf'
    with rag.fitz.open() as doc:
        page=doc.new_page();page.insert_text((60,70),'Revenue 100 million')
        doc.save(p)
    chunks=rag.parse_document(p,p.name)
    assert chunks[0]['page']==1 and 'Revenue' in chunks[0]['text']


def test_auth_and_file_boundary():
    assert client.post('/search',json={'owner_id':1,'document_ids':[1],'query':'收入'}).status_code==403
    response=client.post('/index',headers={'X-Internal-Token':rag.CONFIG['INTERNAL_TOKEN']},json={'owner_id':1,'document_id':1,'filename':'secret.txt','path':'/etc/passwd'})
    assert response.status_code==400


def test_cross_owner_cannot_load():
    (rag.DATA/'1_7.json').write_text(json.dumps([{'id':'a','document_id':7,'owner_id':1}]))
    assert len(rag.load_chunks(1,[7]))==1
    with pytest.raises(rag.HTTPException):rag.load_chunks(2,[7])


def test_read_requires_authorized_doc():
    response=client.post('/read',headers={'X-Internal-Token':rag.CONFIG['INTERNAL_TOKEN']},json={'owner_id':1,'document_ids':[7],'chunk_id':'other'})
    assert response.status_code==404


def test_vector_failure_not_silently_sparse(monkeypatch):
    def fail(_):raise RuntimeError('vector unavailable')
    monkeypatch.setattr(rag,'embed',fail)
    with pytest.raises(RuntimeError,match='vector unavailable'):
        rag.search(rag.SearchInput(owner_id=1,document_ids=[7],query='收入'))


def test_image_ocr_is_marked_as_recognized_text(monkeypatch, tmp_path):
    monkeypatch.setattr(rag, 'recognize_image', lambda path: '2025年营业收入 123.45 万元')
    chunks = rag.parse_document(tmp_path / 'statement.png', 'statement.png')
    assert '123.45' in chunks[0]['text']
    assert 'OCR' in chunks[0]['anchor'] and chunks[0]['page'] is None


def test_ocr_failures_are_explicit(monkeypatch, tmp_path):
    binary = rag.ROOT / '.runtime/bin/vision-ocr'
    with pytest.raises(ValueError, match='未安装'):
        rag.recognize_image(tmp_path / 'image.jpg')
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.touch()
    def response(returncode, stdout):
        return rag.subprocess.CompletedProcess([], returncode, stdout, '')
    monkeypatch.setattr(rag.subprocess, 'run', lambda *a, **kw: response(0, '{"text":""}'))
    with pytest.raises(ValueError, match='未识别到文字'):
        rag.recognize_image(tmp_path / 'image.jpg')
    monkeypatch.setattr(rag.subprocess, 'run', lambda *a, **kw: response(1, ''))
    with pytest.raises(ValueError, match='图片无法识别'):
        rag.recognize_image(tmp_path / 'image.jpg')
    def timeout(*args, **kwargs):
        raise rag.subprocess.TimeoutExpired('ocr', 60)
    monkeypatch.setattr(rag.subprocess, 'run', timeout)
    with pytest.raises(ValueError, match='超时'):
        rag.recognize_image(tmp_path / 'image.jpg')
    monkeypatch.setattr(rag.subprocess, 'run', lambda *a, **kw: response(0, '{"text":"收入 99.50 万元"}'))
    assert rag.recognize_image(tmp_path / 'image.jpg') == '收入 99.50 万元'
    binary.unlink()


def test_delete_removes_only_owner_document_and_is_idempotent():
    from qdrant_client import models
    ids = [str(rag.uuid.uuid4()) for _ in range(3)]
    for chunk, owner, document in zip(ids, [101, 102, 101], [90, 90, 91]):
        rag.client.upsert(rag.COLLECTION, [models.PointStruct(id=chunk, vector=[0.1]*1024, payload={'owner_id': owner, 'document_id': document})])
        (rag.DATA / f'{owner}_{document}.json').write_text('[]')
    body = rag.SourceInput(owner_id=101, document_id=90)
    rag.delete(body)
    rag.delete(body)
    assert not (rag.DATA / '101_90.json').exists()
    assert (rag.DATA / '102_90.json').exists()
    assert (rag.DATA / '101_91.json').exists()
    remaining = rag.client.retrieve(rag.COLLECTION, ids)
    assert {point.id for point in remaining} == set(ids[1:])
