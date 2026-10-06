#!/usr/bin/env python3
import os,concurrent.futures,datetime,json,pathlib,random,time,urllib.request,traceback
ROOT=pathlib.Path(os.environ.get("STRATA_OUTPUT_DIR", "run-output"))
ROOT.mkdir(parents=True,exist_ok=True)
BASE=os.environ.get("STRATA_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
HEADERS={"Content-Type":"application/json"}
if os.environ.get("STRATA_API_KEY"):HEADERS["Authorization"]="Bearer "+os.environ["STRATA_API_KEY"]
OP=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def get(path):
    return json.load(OP.open(urllib.request.Request(BASE+path,headers=HEADERS),timeout=20))
def request(label,scale,rep,stream=False,prompt_text=None):
    rng=random.Random(1062026+rep+scale)
    # Unique initial prefix prevents previous requests from supplying a cached prompt.
    nonce=f'Benchmark {label} repetition {rep}: {rng.getrandbits(96):024x}. '
    words=['system','network','database','memory','server','record','request','response','process','token','cache','thread','queue','service','client','document']
    text=nonce+(prompt_text if prompt_text is not None else ' '.join(rng.choice(words) for _ in range(scale)))
    text+='\nWrite a detailed numbered technical explanation of server architecture, at least 2000 words. Continue until the output budget is exhausted. Do not summarize the input.'
    payload={'model':'qwen3.8-flash-next','messages':[{'role':'user','content':text}],'max_tokens':512,'temperature':0,'chat_template_kwargs':{'enable_thinking':False},'stream':stream}
    start=time.monotonic(); ttft=None; chunks=[]; data=None
    try:
        req=urllib.request.Request(BASE+'/v1/chat/completions',data=json.dumps(payload).encode(),headers=HEADERS)
        with OP.open(req,timeout=1200) as res:
            if not stream: data=json.load(res)
            else:
                for line in res:
                    line=line.decode().strip()
                    if line=='data: [DONE]': break
                    if not line.startswith('data: '): continue
                    c=json.loads(line[6:]); chunks.append(c)
                    ds=[x.get('delta',{}) for x in c.get('choices',[])]
                    if ttft is None and any(d.get('content') or d.get('reasoning_content') for d in ds): ttft=time.monotonic()-start
                data={'stream_chunks':chunks,'timings':next((c['timings'] for c in reversed(chunks) if 'timings' in c),None),'usage':next((c['usage'] for c in reversed(chunks) if 'usage' in c),None),'done':line=='data: [DONE]'}
        out={'label':label,'rep':rep,'word_count':scale,'wall_s':time.monotonic()-start,'ttft_s':ttft,'response':data}
    except Exception as e:
        out={'label':label,'rep':rep,'word_count':scale,'wall_s':time.monotonic()-start,'error':repr(e)}
    out['at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    (ROOT/'raw').mkdir(exist_ok=True)
    (ROOT/'raw'/f'{label}-{rep}.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in out.items() if k!='response'}),data.get('timings') if data else None,flush=True)
    return out

def main():
    (ROOT/'status-before.json').write_text(json.dumps(get('/v1/status'),indent=2))
    request('warmup',64,0)
    for name,n,reps in [('short',128,3),('p4k',4000,3),('p32k',32000,3),('p120k',120000,2),('p250k',250000,1)]:
        for rep in range(reps):
            o=request(name,n,rep,stream=True)
            if 'error' in o: raise RuntimeError(o['error'])
            (ROOT/'status-latest.json').write_text(json.dumps(get('/v1/status'),indent=2))
    begin=time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        out=list(ex.map(lambda r:request('parallel',4000,r,stream=True),range(2)))
    (ROOT/'parallel-summary.json').write_text(json.dumps({'wall_s':time.monotonic()-begin,'results':out},ensure_ascii=False,indent=2))
    (ROOT/'status-after.json').write_text(json.dumps(get('/v1/status'),indent=2))
    (ROOT/'DONE').write_text(datetime.datetime.now(datetime.timezone.utc).isoformat())
if __name__=='__main__': main()
