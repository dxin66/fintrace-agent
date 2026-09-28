import concurrent.futures,json,pathlib,time,statistics,httpx
r=pathlib.Path(__file__).resolve().parents[1];cfg=json.loads((r/'.runtime/config.json').read_text());docs=json.loads((r/'.runtime/seed-documents.json').read_text());pdfs=[d['id'] for d in docs if d['filename'].endswith('.pdf')]
def search(doc):
 response=httpx.post('http://127.0.0.1:8081/search',headers={'X-Internal-Token':cfg['INTERNAL_TOKEN']},json={'owner_id':1,'document_ids':[doc],'query':'合并利润表 营业收入'},timeout=90);response.raise_for_status();assert response.json()['hits'];return len(response.json()['hits'])
serial=[];parallel=[]
for _ in range(3):
 start=time.monotonic();[search(d) for d in pdfs];serial.append(time.monotonic()-start)
 start=time.monotonic()
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(search,pdfs))
 parallel.append(time.monotonic()-start)
report={'description':'Two real independent retrieval HTTP calls; three serial/parallel pairs, including live embedding API latency. Not full Agent latency.','serial_seconds':serial,'parallel_seconds':parallel,'median_serial':statistics.median(serial),'median_parallel':statistics.median(parallel)}
(r/'.runtime/tool-benchmark.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
