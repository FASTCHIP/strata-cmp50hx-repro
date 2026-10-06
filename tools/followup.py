#!/usr/bin/env python3
import concurrent.futures,json,pathlib,time,urllib.request,datetime
import benchmark as b
root=b.ROOT
if not __import__('os').environ.get('STRATA_SOURCE_FILE'): raise SystemExit('Set STRATA_SOURCE_FILE to the audited server.py input before followup')
# Run only after baseline; source-code workloads and repeated concurrency.
if not (root/'DONE').exists(): raise SystemExit('baseline not complete')
for rep in range(1,3):
    start=time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        rr=list(ex.map(lambda n:b.request('parallel-extra',4000,n,stream=True),[rep*2,rep*2+1]))
    (root/f'parallel-extra-{rep}.json').write_text(json.dumps({'wall_s':time.monotonic()-start,'results':rr},ensure_ascii=False,indent=2))
for rep in range(3):
    b.request('source-code',0,rep,stream=True,prompt_text=pathlib.Path(__import__('os').environ['STRATA_SOURCE_FILE']).read_text()[:100000])
first=b.request('cache-control',4000,0,stream=True)
(root/'raw/cache-control-first.json').write_text(json.dumps(first,ensure_ascii=False,indent=2))
b.request('cache-control',4000,0,stream=True)
(root/'raw/cache-control-0.json').rename(root/'raw/cache-control-repeat.json')
payload={'model':'qwen3.8-flash-next','messages':[{'role':'user','content':'What is the capital of Australia? Answer with one word.'}],'max_tokens':32,'temperature':0,'chat_template_kwargs':{'enable_thinking':False}}
for label,path in [('openai','/v1/chat/completions'),('anthropic','/v1/messages')]:
    pp=dict(payload)
    if label=='anthropic': pp.pop('chat_template_kwargs');pp['thinking']={'type':'disabled'}
    st=time.monotonic()
    try:
        r=json.load(b.OP.open(urllib.request.Request(b.BASE+path,data=json.dumps(pp).encode(),headers={**b.HEADERS,'anthropic-version':'2023-06-01'}),timeout=120))
        out={'wall_s':time.monotonic()-st,'response':r}
    except Exception as e:out={'error':repr(e)}
    (root/f'check-{label}.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)); print(label,json.dumps(out,ensure_ascii=False),flush=True)
(root/'FOLLOWUP_DONE').write_text(datetime.datetime.now(datetime.timezone.utc).isoformat())
