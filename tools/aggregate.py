#!/usr/bin/env python3
import collections,json,pathlib,statistics
import sys
root=pathlib.Path(sys.argv[1]) if len(sys.argv)>1 else pathlib.Path(__file__).resolve().parents[1]/"results/2026-10-06"
assert (root/'DONE').exists() and (root/'FOLLOWUP_DONE').exists(), 'benchmarks incomplete'
raw=[json.loads(p.read_text())|{'file':p.name} for p in sorted((root/'raw').glob('*.json'))]
assert len(raw)==24,(len(raw),'expected baseline15 + concurrent4 + code3 + cache2')
for r in raw:
    assert 'error' not in r,r
    response=r['response']
    actual=response['usage']['completion_tokens']
    assert actual==512 or (r['label']=='source-code' and 128<=actual<=512),(r['file'],actual)
    if 'done' in response:assert response['done'],r['file']
    assert not response['reasoning_present'],r['file']
groups=collections.defaultdict(list)
for r in raw:
    if r['label'] not in ['parallel','parallel-extra','cache-control','warmup']:groups[r['label']].append(r)
summ=[]
for label,rs in groups.items():
    ts=[r['response']['timings'] for r in rs]
    assert all(t['cache_n']==0 for t in ts),label
    item={'label':label,'repetitions':len(rs),'prompt_tokens_range':[min(t['prompt_n'] for t in ts),max(t['prompt_n'] for t in ts)],'output_tokens_range':[min(r['response']['usage']['completion_tokens'] for r in rs),max(r['response']['usage']['completion_tokens'] for r in rs)]}
    for key,vals in [('prefill_tps',[t['prompt_per_second'] for t in ts]),('decode_tps',[t['predicted_per_second'] for t in ts]),('ttft_s',[r['ttft_s'] for r in rs]),('wall_s',[r['wall_s'] for r in rs])]:
        item[key]={'median':statistics.median(vals),'min':min(vals),'max':max(vals)}
    offered=sum(t['draft_n'] for t in ts); accepted=sum(t['draft_n_accepted'] for t in ts)
    item['mtp_acceptance']=accepted/offered if offered else None;summ.append(item)
pairs=[]
for path in [root/'parallel-summary.json',root/'parallel-extra-1.json',root/'parallel-extra-2.json']:
    d=json.loads(path.read_text());rs=d['results'];n=sum(r['response']['usage']['completion_tokens'] for r in rs)
    pairs.append({'file':path.name,'wall_s':d['wall_s'],'output_tokens':n,'aggregate_output_tps_including_prefill':n/d['wall_s'],'ttft_s':[r['ttft_s'] for r in rs],'client_end_to_end_tps':[r['response']['usage']['completion_tokens']/r['wall_s'] for r in rs]})
tele=[json.loads(l) for l in (root/'telemetry.jsonl').read_text().splitlines()]
gpu=collections.defaultdict(list);ram=[]
for sample in tele:
    for line in sample['stdout'].splitlines():
        if line and line[0].isdigit() and ', ' in line:
            a=line.split(', ')
            if len(a)==7:gpu[int(a[0])].append([float(x.split()[0]) for x in a[1:]])
        if line.startswith('MemAvailable:'):ram.append(int(line.split()[1]))
res={'request_artifact_count':len(raw),'solo':summ,'concurrent':pairs,'concurrent_median_aggregate_tps':statistics.median(r['aggregate_output_tps_including_prefill'] for r in pairs),'cache_control':{r['file']:r['response']['timings'] for r in raw if r['label']=='cache-control'},'telemetry_baseline':{'samples':len(tele),'gpu_peak':{i:{'memory_mib':max(r[0] for r in rs),'temperature_c':max(r[2] for r in rs),'power_w':max(r[3] for r in rs)} for i,rs in gpu.items()},'ram_min_available_gib':min(ram)/1024/1024}}
(root/'summary.json').write_text(json.dumps(res,indent=2))
print(json.dumps(res,indent=2))
