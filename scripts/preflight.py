import json,pathlib,httpx,time
root=pathlib.Path(__file__).resolve().parents[1];c=json.loads((root/'.runtime/config.json').read_text())
results=[]
for endpoint,payload in [('chat/completions',{'model':c['LLM_MODEL'],'messages':[{'role':'user','content':'仅回复 OK'}],'max_tokens':8,'enable_thinking':False}),('embeddings',{'model':c['EMBEDDING_MODEL'],'input':['金融文档核查测试'],'dimensions':1024})]:
 start=time.monotonic()
 r=httpx.post(c['LLM_BASE_URL']+'/'+endpoint,headers={'Authorization':'Bearer '+c['LLM_API_KEY']},json=payload,timeout=90)
 item={'endpoint':endpoint,'status':r.status_code,'seconds':round(time.monotonic()-start,2)}
 if r.status_code==200:
  body=r.json();item['usage']=body.get('usage');item['output']=body['choices'][0]['message']['content'] if endpoint.startswith('chat') else {'dimensions':len(body['data'][0]['embedding'])}
 else:
  body=r.json();item['error_code']=body.get('error',{}).get('code');item['message']=body.get('error',{}).get('message','Provider error').replace(c['LLM_API_KEY'],'[redacted]')
 results.append(item)
(root/'.runtime/model-preflight.json').write_text(json.dumps(results,ensure_ascii=False,indent=2));print(json.dumps(results,ensure_ascii=False))
assert all(r['status']==200 for r in results)
