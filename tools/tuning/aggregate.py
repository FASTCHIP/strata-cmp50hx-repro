#!/usr/bin/env python3
"""Recalculate published numerical evidence offline; no HTTP/GPU/service operations."""
import pathlib,json,statistics,math
import bench
CASES=bench.SCREEN_CASES
def select(rows):
 arms=sorted({r.get('label') for r in rows if r.get('mode')=='screen' and not r.get('warmup')})
 if 'R' not in arms:raise ValueError('Missing reference')
 med={}
 for arm in arms:
  med[arm]={}
  for c in CASES:
   g=[r for r in rows if r.get('label')==arm and r.get('case')==c and r.get('mode')=='screen' and not r.get('warmup')]
   if len(g)!=3 or {r['repetition'] for r in g}!={0,1,2} or not all(r['ok'] for r in g):raise ValueError('Incomplete '+arm+' '+c)
   med[arm][c]={k:statistics.median(r['timings'][k] for r in g) for k in ['predicted_per_second','prompt_per_second']}
 scores={}
 for arm in arms:
  scores[arm]={k:math.exp(statistics.mean(math.log(med[arm][c][k]/med['R'][c][k]) for c in (CASES if k=='predicted_per_second' else CASES[2:]))) for k in ['predicted_per_second','prompt_per_second']}
 chosen=['R']
 for k in ['predicted_per_second','prompt_per_second']:
  winner=max((a for a in arms if a!='Z'),key=lambda a:scores[a][k])
  if scores[winner][k]>1.02 and winner not in chosen:chosen.append(winner)
 return {'medians':med,'scores_vs_R':scores,'long_arms':chosen,'concurrent_arms':chosen+(['Z'] if 'Z' in arms else [])}
def recalculate(directory):
 directory=pathlib.Path(directory)
 allrows=[json.loads(l) for f in sorted(directory.glob('*.jsonl')) for l in f.read_text().splitlines() if l.strip()]
 for r in allrows:
  if r.get('kind')=='concurrent_group':continue
  assert r['ok'] and r['done'] and not r['reasoning_present'], 'incomplete SSE/reasoning'
  assert r['usage']['completion_tokens']>0
  if r['mode']!='concurrent' and not r['warmup']:assert r['timings']['cache_n']==0, 'unexpected prefix reuse'
  if r.get('expected_prompt_tokens') is not None:assert r['usage']['prompt_tokens']==r['expected_prompt_tokens']
 selection=select(allrows)
 summary={'screen':bench.summarize(allrows,'screen',['R','T8','L','D2','D3','D6','P1','P4','Z']), 'selection':selection, 'long':bench.summarize(allrows,'long',selection['long_arms']), 'concurrent':bench.summarize(allrows,'concurrent',selection['concurrent_arms'])}
 return summary
if __name__=='__main__':
 root=pathlib.Path(__file__).resolve().parents[2]/'results/2026-10-07'
 result=recalculate(root)
 expected=json.loads((root/'summary.json').read_text())
 assert result==expected, 'Published summary does not reproduce'
 print(json.dumps({'summary_equal':True,'measured_rows':{k:result[k]['measured_rows'] for k in ['screen','long','concurrent']}},indent=2))
