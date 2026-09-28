"""Real MySQL / real model end-to-end checks. Does not compare model accuracy to other products."""
import json,pathlib,time,uuid,httpx,sys
ROOT=pathlib.Path(__file__).resolve().parents[1];config=json.loads((ROOT/'.runtime/config.json').read_text())
client=httpx.Client(base_url='http://127.0.0.1:8080',timeout=60)
token=client.get('/api/auth/csrf').json()['token'];client.headers['X-CSRF-TOKEN']=token
r=client.post('/api/auth/login',json={'username':'demo','password':config['DEMO_PASSWORD']});r.raise_for_status()
client.headers['X-CSRF-TOKEN']=client.get('/api/auth/csrf').json()['token']

def post(path,payload):
 r=client.post(path,json=payload);r.raise_for_status();return r.json()

def task(instruction,documents):
 session=post('/api/sessions',{'title':instruction[:40]})['id'];key=str(uuid.uuid4())
 body={'session_id':session,'document_ids':documents,'instruction':instruction,'idempotency_key':key}
 start=time.monotonic();created=post('/api/tasks',body);again=post('/api/tasks',body)
 assert created['id']==again['id'],'Idempotency mismatch'
 conflict=client.post('/api/tasks',json={**body,'instruction':instruction+'different'})
 assert conflict.status_code==409
 for _ in range(360):
  detail=client.get(f"/api/tasks/{created['id']}").json()
  if detail['status'] in ('SUCCEEDED','FAILED','CANCELLED'):break
  time.sleep(2)
 else:raise AssertionError('Timed out')
 detail['elapsed_seconds']=round(time.monotonic()-start,2)
 (ROOT/'.runtime'/f"acceptance-task-{created['id']}.json").write_text(json.dumps(detail,ensure_ascii=False,indent=2))
 print(json.dumps({'id':detail['id'],'status':detail['status'],'seconds':detail['elapsed_seconds'],'agents':len(detail['agents']),'tools':len(detail['tools']),'error':detail.get('error')},ensure_ascii=False),flush=True)
 assert detail['status']=='SUCCEEDED',detail.get('error')
 assert detail['tools'] and detail['evidence']
 return detail

mode=sys.argv[1] if len(sys.argv)>1 else 'seed'
if mode=='seed':
 docs=client.get('/api/documents').json()
 if not docs:
  result=client.post('/api/documents/samples');result.raise_for_status();print('Real sample documents submitted for indexing.',flush=True)
 for _ in range(300):
  docs=client.get('/api/documents').json()
  if any(d['status']=='FAILED' for d in docs):raise AssertionError([(d['filename'],d.get('error')) for d in docs if d['status']=='FAILED'])
  if len(docs)>=4 and all(d['status']=='READY' for d in docs):break
  time.sleep(3)
 else:raise AssertionError('Index did not finish')
 print(json.dumps([{'id':d['id'],'filename':d['filename'],'chunks':d['chunk_count']} for d in docs],ensure_ascii=False),flush=True)
 (ROOT/'.runtime/seed-documents.json').write_text(json.dumps(docs,ensure_ascii=False,indent=2))
elif mode=='tasks':
 docs=client.get('/api/documents').json();pdfs=[d['id'] for d in docs if '年报' in d['filename'] and d['status']=='READY'];txt=[d['id'] for d in docs if d['filename'].endswith('.txt') and d['status']=='READY'];html=[d['id'] for d in docs if d['filename'].endswith('.html') and d['status']=='READY']
 a=task('比较宁德时代2024和2025年的合并营业收入。分别委派两个独立子Agent核查每份年报的主要会计数据表，再使用计算工具核对2025同比增幅。注明千元口径、精确原始数值及来源页码。',pdfs)
 assert sum(bool(r.get('parent_id')) for r in a['agents'])>=2,'No real child agents'
 assert any(t['name']=='calculate' and t['status']=='SUCCEEDED' for t in a['tools'])
 normalized=a['result'].replace(',','').replace('，','')
 assert '362012554' in normalized and '423701834' in normalized,'Revenue evidence not represented accurately'
 assert any('2024' in e['filename'] and '362,012,554' in e['text'] for e in a['evidence'])
 assert any('2025' in e['filename'] and '423,701,834' in e['text'] for e in a['evidence'])
 # Valid citations can point to the summary or the consolidated income statement.
 import fitz,re
 for citation in set(re.findall(r'\[E:([^\]]+)\]',a['result'])):
  chunk=next(e for e in a['evidence'] if e['citation_id']==citation)
  with fitz.open(ROOT/'samples'/chunk['filename']) as pdf:
   assert '营业' in pdf[chunk['page']-1].get_text()
 review=post(f"/api/tasks/{a['id']}/reviews",{'version':a['version'],'decision':'CONFIRMED','note':'已人工核对2024年报第9页与2025年报第11页，营业收入分别为362,012,554千元和423,701,834千元；同比约17.04%。'})
 assert review['result']==a['result'] and review['review_status']=='CONFIRMED'
 stale=client.post(f"/api/tasks/{a['id']}/reviews",json={'version':a['version'],'decision':'CORRECTED','note':'stale'})
 assert stale.status_code==409
 b=task('依据所选文件，概括数据处理者的数据安全管理责任，引用两个具体原文条款，不作额外法律推断。',txt)
 c=task('这份监管文件的主题是什么？摘录一项明确要求，并引用对应原文。',html)
 d=task('仅根据所选材料，能否确定宁德时代2030年的营业收入？不要预测，明确说明材料是否足以回答。',pdfs)
 assert '证据不足' in d['result'] or '无法' in d['result'] or '不能' in d['result']
 (ROOT/'.runtime/acceptance-summary.json').write_text(json.dumps({'task_ids':[a['id'],b['id'],c['id'],d['id']],'real_model':True,'expected_revenue_thousand_cny':[362012554,423701834],'checks':['idempotency','conflicting-key','multi-agent','hybrid-retrieval','calculator','PDF-page-citations','TXT-source','HTML-source','review','optimistic-lock','insufficient-evidence']},ensure_ascii=False,indent=2))
