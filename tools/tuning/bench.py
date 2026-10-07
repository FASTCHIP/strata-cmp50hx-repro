#!/usr/bin/env python3
"""Stdlib-only streaming benchmark; raw JSONL is evidence, not synthetic data."""
import time
import argparse
import csv
import io
import os
import subprocess
import threading
import uuid
import urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json
import statistics
from collections import Counter


def summarize(rows, mode='screen', labels=None):
    groups = [r for r in rows if r.get('mode') == mode and r.get('kind') == 'concurrent_group']
    rows = [r for r in rows if r.get('mode') == mode and r.get('kind','request') == 'request']
    labels = labels if labels is not None else sorted({r['label'] for r in rows})
    if not labels:
        raise ValueError('no variants')
    cases = SCREEN_CASES if mode == 'screen' else LONG_CASES if mode == 'long' else ('p4k_code','p4k_prose') if mode == 'concurrent' else ('smoke',)
    expected = Counter((c,rep,False) for c in cases for rep in (range(3) if mode == 'screen' else range(1)))
    if mode == 'screen':
        expected[('warmup',-1,True)] = 1
    pivot = {}
    measured = 0
    for label in labels:
        arm = [r for r in rows if r['label'] == label]
        actual = Counter((r['case'],r['repetition'],r['warmup']) for r in arm)
        if actual != expected or any(not r.get('ok') for r in arm):
            raise ValueError('incomplete/duplicate/failed arm: ' + label)
        for case in cases:
            samples = [r for r in arm if not r['warmup'] and r['case'] == case]
            measured += len(samples)
            pivot.setdefault(case,{})[label] = {
                'n':len(samples),
                'actual_completion_tokens':[r['usage']['completion_tokens'] for r in samples],
                'median_client_tokens_per_s':statistics.median(r['usage']['completion_tokens']/r['wall_s'] for r in samples),
                'median_wall_s':statistics.median(r['wall_s'] for r in samples),
                'median_ttft_s':statistics.median(r['ttft_s'] for r in samples),
                'median_token_window_s':statistics.median(r['token_window_s'] for r in samples),
            }
    result = dict(mode=mode, labels=list(labels), measured_rows=measured, pivot=pivot)
    if mode == 'concurrent':
        result['concurrent_groups'] = {}
        for label in labels:
            arm_groups = [g for g in groups if g['label'] == label]
            if len(arm_groups) != 1 or not arm_groups[0].get('ok'):
                raise ValueError('missing/duplicate/failed concurrent group: ' + label)
            result['concurrent_groups'][label] = arm_groups[0]
    return result

SCREEN_CASES = ('short_code','short_prose','p4k_code','p4k_prose','p32k_code','p32k_prose')
LONG_CASES = ('p120k_code','p250k_code')
SMOKE = {'messages':[{'role':'user','content':'Reply with OK only.'}]}


def make_plan(fixtures, mode):
    def item(case, rep, fixture, warmup=False):
        return dict(case=case, repetition=rep, fixture=fixture, warmup=warmup)
    if mode == 'smoke':
        return [item('smoke',0,SMOKE)]
    cases = SCREEN_CASES if mode == 'screen' else LONG_CASES if mode == 'long' else ('p4k_code','p4k_prose')
    selected = {}
    for case in cases:
        entry = fixtures[case]
        reps = entry.get('repetitions', [entry])
        if mode == 'screen':
            if len(reps) != 3:
                raise ValueError(case + ': screen requires 3 prebuilt unique repetitions')
            prefixes = []
            for f in reps:
                user = next((m.get('content') for m in f['messages'] if m.get('role') == 'user'), '')
                if not isinstance(user,str) or not user:
                    raise ValueError('first user content must be a nonempty string')
                prefixes.append(user[:128])
                if not isinstance(f.get('prompt_tokens'), int):
                    raise ValueError('prebuilt repetition token count required')
            if len(set(prefixes)) != 3:
                raise ValueError('repetition prefixes must differ within first 128 characters')
        selected[case] = reps
    if mode == 'concurrent' and selected[cases[0]][0]['messages'] == selected[cases[1]][0]['messages']:
        raise ValueError('concurrent fixtures must have distinct messages')
    if mode != 'screen':
        return [item(c,0,selected[c][0]) for c in cases]
    result = [item('warmup',-1,SMOKE,True)]
    for rep in range(3):
        order = cases[rep:] + cases[:rep]
        result.extend(item(c,rep,selected[c][rep]) for c in order)
    return result


def require_idle(status):
    if status.get('loaded') is not True:
        raise ValueError('engine not loaded')
    if status.get('activity', {}).get('in_flight') != 0:
        raise ValueError('foreign traffic or unknown in_flight')


def validate(r, expected=None, solo=True, smoke=False):
    if not r.get('done'):
        raise ValueError('missing DONE')
    if not r.get('text', '').strip():
        raise ValueError('empty content')
    if r.get('reasoning') or '<think>' in r.get('text', '') or '</think>' in r.get('text', ''):
        raise ValueError('unexpected reasoning')
    usage = r.get('usage') or {}
    if (usage.get('completion_tokens_details') or {}).get('reasoning_tokens',0):
        raise ValueError('unexpected hidden reasoning tokens')
    if not isinstance(usage.get('completion_tokens'), int) or usage['completion_tokens'] <= 0:
        raise ValueError('missing actual completion count')
    if expected is not None and usage.get('prompt_tokens') != expected:
        raise ValueError('prompt token count mismatch')
    if r.get('finish_reason') not in ('stop', 'length'):
        raise ValueError('missing/invalid finish reason')
    if solo and (r.get('timings') or {}).get('cache_n') != 0:
        raise ValueError('missing timings or reused cache')
    if smoke and (r.get('finish_reason') != 'stop' or 'OK' not in r.get('text','')):
        raise ValueError('known-answer smoke failed')


def parse_sse(stream, start, clock=time.monotonic, record=None):
    r = record if record is not None else {}
    r.update(text='', reasoning='', done=False, usage=None, timings=None,
             finish_reason=None, ttft_s=None, token_window_s=None, raw_sse='')
    first = last = None
    pending = []
    raw = []
    def event():
        nonlocal first, last
        if not pending:
            return
        data = '\n'.join(pending)
        pending.clear()
        if data == '[DONE]':
            r['done'] = True
            return
        obj = json.loads(data)
        if 'error' in obj:
            raise ValueError('SSE error: ' + str(obj['error']))
        if obj.get('usage') is not None:
            r['usage'] = obj['usage']
        if obj.get('timings') is not None:
            r['timings'] = obj['timings']
        for choice in obj.get('choices', []):
            delta = choice.get('delta', {})
            content = delta.get('content') or ''
            reasoning = delta.get('reasoning_content') or delta.get('reasoning') or ''
            if content or reasoning:
                last = clock()
                if first is None:
                    first = last
                    r['ttft_s'] = first - start
                r['text'] += content
                r['reasoning'] += reasoning
                r['token_window_s'] = last - first
            if choice.get('finish_reason') is not None:
                r['finish_reason'] = choice['finish_reason']
    try:
        for line in stream:
            text = line.decode('utf-8') if isinstance(line, bytes) else line
            raw.append(text)
            text = text.rstrip('\r\n')
            if not text:
                event()
                if r['done']:
                    break
            elif text.startswith('data:'):
                pending.append(text[5:].lstrip(' '))
        event()
        return r
    finally:
        r['raw_sse'] = ''.join(raw)
        r['wall_s'] = clock() - start


def gpu_snapshot():
    fields = ['index','uuid','clocks.sm','clocks.mem','temperature.gpu','memory.used','memory.total','power.draw','utilization.gpu']
    try:
        p = subprocess.run(['nvidia-smi','--query-gpu='+','.join(fields),'--format=csv,noheader,nounits'], capture_output=True,text=True,timeout=5,check=True)
        return {'at':time.time(),'gpus':[dict(zip(fields,row)) for row in csv.reader(io.StringIO(p.stdout),skipinitialspace=True)]}
    except Exception as exc:
        return {'at':time.time(),'error':type(exc).__name__+': '+str(exc)}


def arguments(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base',default='http://127.0.0.1:18080')
    p.add_argument('--out',help='append-only raw JSONL file path')
    p.add_argument('--label')
    p.add_argument('--fixtures')
    p.add_argument('--mode',choices=['screen','long','concurrent','smoke'],default='screen')
    p.add_argument('--timeout',type=float,help='socket timeout seconds; default 900 long, 300 otherwise')
    p.add_argument('--summarize',metavar='JSONL',help='offline only; no HTTP/GPU calls')
    p.add_argument('--labels',help='comma-separated expected variants for offline completeness')
    a = p.parse_args(argv)
    if a.timeout is None: a.timeout = 900 if a.mode == 'long' else 300
    if a.timeout <= 0: p.error('timeout must be positive')
    if not a.summarize and (not a.out or not a.label or (a.mode != 'smoke' and not a.fixtures)):
        p.error('--out, --label and --fixtures required (smoke does not need fixtures)')
    return a


def run_campaign(args, transport=None, gpu=gpu_snapshot):
    """One arm per invocation; controller must reload engine between variants.

    --out is a JSONL FILE. token_window_s is first-to-last received content chunk,
    not token IDs. Concurrent server timings are last-segment diagnostics only.
    """
    opener = transport or urllib.request.build_opener(urllib.request.ProxyHandler({})).open
    base = args.base.rstrip('/')
    def get(path):
        with opener(urllib.request.Request(base+path),timeout=args.timeout) as response:
            return json.load(response)
    fixtures = json.loads(Path(args.fixtures).read_text()) if args.fixtures else {}
    plan = make_plan(fixtures,args.mode)
    model = get('/v1/models')['data'][0]['id']
    run_id = str(uuid.uuid4())
    output = Path(args.out)
    output.parent.mkdir(parents=True,exist_ok=True)
    lock = threading.Lock()
    def append(record):
        with lock, output.open('a',encoding='utf-8') as f:
            f.write(json.dumps(record,ensure_ascii=False,allow_nan=False)+'\n')
            f.flush()
            os.fsync(f.fileno())
    def snapshot():
        try: return gpu()
        except Exception as exc: return {'at':time.time(),'error':type(exc).__name__+': '+str(exc)}
    def request(item, barrier=None):
        solo = args.mode != 'concurrent'
        smoke = args.mode == 'smoke' or item['warmup']
        maximum = 64 if smoke else 128 if args.mode == 'long' else 256
        fixture = item['fixture']
        body = {'model':model,'messages':fixture['messages'],'stream':True,
                'temperature':0,'seed':42,'max_tokens':maximum,
                'chat_template_kwargs':{'enable_thinking':False},'stream_options':{'include_usage':True}}
        wire = json.dumps(body,ensure_ascii=False,separators=(',',':'))
        r = dict(kind='request',label=args.label,mode=args.mode,run_id=run_id,
                 case=item['case'],repetition=item['repetition'],warmup=item['warmup'],
                 body=body,body_json=wire,expected_prompt_tokens=fixture.get('prompt_tokens'),
                 ok=False,at=time.time(),gpu_samples=[])
        stopped = threading.Event()
        def sample():
            while not stopped.wait(1): r['gpu_samples'].append(snapshot())
        sampler = None
        try:
            if solo:
                r['status_before'] = get('/v1/status')
                require_idle(r['status_before'])
            r['gpu_before'] = snapshot()
            if barrier is not None: barrier.wait(timeout=args.timeout)
            sampler = threading.Thread(target=sample,daemon=True)
            sampler.start()
            start = time.monotonic()
            r['client_start_monotonic'] = start
            req = urllib.request.Request(base+'/v1/chat/completions',data=wire.encode('utf-8'), headers={'Content-Type':'application/json','Accept':'text/event-stream'},method='POST')
            with opener(req,timeout=args.timeout) as stream: parse_sse(stream,start,record=r)
            r['client_end_monotonic'] = time.monotonic()
            if solo:
                r['status_after'] = get('/v1/status')
                require_idle(r['status_after'])
                if not r.get('timings'):
                    r['timings'] = r['status_after'].get('last_timings')
                    r['timings_source'] = 'solo_status_last_timings'
                else: r['timings_source'] = 'response'
            else: r['timings_source'] = 'response_last_segment_diagnostic_only'
            validate(r,fixture.get('prompt_tokens'),solo=solo and not smoke,smoke=smoke)
            r['completion_tokens'] = r['usage']['completion_tokens']
            r['client_tokens_per_s'] = r['completion_tokens']/r['wall_s']
            r['ok'] = True
        except Exception as exc: r['error'] = type(exc).__name__+': '+str(exc)
        finally:
            stopped.set()
            if sampler is not None: sampler.join(timeout=6)
            r['gpu_after'] = snapshot()
            append(r)
        return r
    if args.mode == 'concurrent':
        gate = threading.Barrier(2)
        start = time.monotonic()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(request,item,gate) for item in plan]
            rows = [f.result() for f in futures]
        starts = [r['client_start_monotonic'] for r in rows if 'client_start_monotonic' in r]
        ends = [r['client_end_monotonic'] for r in rows if 'client_end_monotonic' in r]
        wall = max(ends)-min(starts) if len(starts)==2 and len(ends)==2 else time.monotonic()-start
        count = sum((r.get('usage') or {}).get('completion_tokens',0) for r in rows)
        group = dict(kind='concurrent_group',mode=args.mode,label=args.label,run_id=run_id,
                     ok=all(r['ok'] for r in rows),wall_s=wall,completion_tokens=count,
                     actual_tokens_per_s=count/wall if wall > 0 else None,
                     per_request=[{k:r.get(k) for k in ('case','ok','ttft_s','token_window_s','completion_tokens')} for r in rows])
        append(group)
    else:
        rows = []
        for item in plan:
            row = request(item)
            rows.append(row)
            if not row['ok']: raise ValueError(row['error'])
    if any(not row['ok'] for row in rows): raise ValueError('concurrent request failure; inspect raw JSONL')
    result = summarize(rows+([group] if args.mode == 'concurrent' else []),args.mode,[args.label])
    if args.mode == 'concurrent': result['concurrent_group'] = group
    return result


def main(argv=None):
    args = arguments(argv)
    if args.summarize:
        with open(args.summarize,encoding='utf-8') as f:
            rows = [json.loads(line) for line in f if line.strip()]
        result = summarize(rows,args.mode,args.labels.split(',') if args.labels else None)
    else: result = run_campaign(args)
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    return 0


if __name__ == '__main__':
    try: raise SystemExit(main())
    except Exception as exc:
        import sys
        print(type(exc).__name__+': '+str(exc),file=sys.stderr)
        raise SystemExit(1)
