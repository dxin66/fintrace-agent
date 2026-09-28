import httpx,json,pathlib,time,uuid
r=pathlib.Path(__file__).resolve().parents[1];config=json.loads((r/'.runtime/config.json').read_text())
def login(username,password):
 h=httpx.Client(base_url='http://127.0.0.1:8080',timeout=90);h.headers['X-CSRF-TOKEN']=h.get('/api/auth/csrf').json()['token'];response=h.post('/api/auth/login',json={'username':username,'password':password});response.raise_for_status();return h
h=login('demo',config['DEMO_PASSWORD']);qa=login('qa_browser_0903','FinancialTest_2026!')
checks={}
checks['cross_user_task']=h.get('/api/tasks/9').status_code==404
checks['cross_user_source']=h.get('/api/documents/5/source').status_code==404
checks['cross_user_sse']=h.get('/api/tasks/9/events').status_code==404
stream=h.get('/api/tasks/5/events');stream.raise_for_status();ids=[int(line[3:]) for line in stream.text.splitlines() if line.startswith('id:')]
assert ids==sorted(set(ids)) and len(ids)>5
last=ids[-1];replay=h.get('/api/tasks/5/events',headers={'Last-Event-ID':str(last)})
checks['sse_replay_no_duplicate']=replay.status_code==200 and 'id:' not in replay.text
checks['cancelled_terminal']=qa.get('/api/tasks/11').json()['status']=='CANCELLED'
checks['review_history']=qa.get('/api/tasks/9').json()['review_status']=='CONFIRMED'
checks['source_paragraph']=('chunk-' in qa.get('/api/documents/5/source').text)
assert all(checks.values()),checks
# Add a complete HTML body alongside the index-only sample; do not overwrite old records.
name='证监会_易事特行政处罚决定书.html';docs=h.get('/api/documents').json();matched=[d for d in docs if d['filename']==name]
if matched:doc=matched[0]
else:
 with open(r/'samples'/name,'rb') as file:
  response=h.post('/api/documents',files={'file':(name,file,'text/html')});response.raise_for_status();doc=response.json()
for _ in range(60):
 documents=h.get('/api/documents').json();item=next(d for d in documents if d['id']==doc['id'])
 if item['status']=='READY':break
 if item['status']=='FAILED':raise AssertionError(item)
 time.sleep(1)
else:raise AssertionError('HTML indexing failed')
s=h.post('/api/sessions',json={'title':'HTML 正文核查'}).json();t=h.post('/api/tasks',json={'session_id':s['id'],'document_ids':[doc['id']],'instruction':'这份行政处罚决定书中，易事特2017年虚增营业收入的金额是多少？注明单位，引用原文。','idempotency_key':str(uuid.uuid4())}).json()
for _ in range(90):
 detail=h.get('/api/tasks/'+str(t['id'])).json()
 if detail['status'] in ('SUCCEEDED','FAILED','CANCELLED'):break
 time.sleep(2)
assert detail['status']=='SUCCEEDED',detail.get('error')
assert '6371498.89' in detail['result'].replace(',','') and '元' in detail['result']
checks['real_html_body_number']=True
(r/'.runtime'/f"acceptance-task-{detail['id']}.json").write_text(json.dumps(detail,ensure_ascii=False,indent=2))
(r/'.runtime/http-checks.json').write_text(json.dumps({'checks':checks,'html_task_id':detail['id'],'html_document_id':doc['id']},ensure_ascii=False,indent=2));print(json.dumps(checks,ensure_ascii=False))
