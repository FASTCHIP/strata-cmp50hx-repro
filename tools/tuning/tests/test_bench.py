"""Offline unit tests. SSE bytes below are explicit UNIT TEST mocks, not API evidence."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bench', ROOT / 'bench.py')
bench = importlib.util.module_from_spec(spec) if spec else None
if spec and spec.loader and (ROOT / 'bench.py').exists():
    spec.loader.exec_module(bench)

def sse(done=True, prompt=7, reasoning=''):
    events = [{'choices':[{'delta':{'content':'OK','reasoning_content':reasoning},'finish_reason':None}]},
              {'choices':[{'delta':{},'finish_reason':'stop'}], 'usage':{'prompt_tokens':prompt,'completion_tokens':2}, 'timings':{'cache_n':0,'predicted_per_second':999}}]
    return io.BytesIO((''.join('data: '+json.dumps(e)+'\n\n' for e in events)+('data: [DONE]\n\n' if done else '')).encode())

class ParseTests(unittest.TestCase):
    def test_stream_preserves_actual_counts_and_done(self):
        self.assertTrue(hasattr(bench, 'parse_sse'), 'stream parser missing')
        r = bench.parse_sse(sse(), 0, clock=lambda:1)
        self.assertEqual(r['text'],'OK')
        self.assertEqual(r['usage']['completion_tokens'],2)
        self.assertTrue(r['done'])
        self.assertEqual(r['finish_reason'],'stop')
        self.assertEqual(r['ttft_s'],1)
        self.assertIn('[DONE]', r['raw_sse'])

class ValidationTests(unittest.TestCase):
    def test_integrity_rejects_missing_done_foreign_mismatch_and_reasoning(self):
        self.assertTrue(hasattr(bench, 'validate'), 'integrity validator missing')
        good = bench.parse_sse(sse(),0,clock=lambda:1)
        bench.validate(good,7,solo=True)
        for key,value in [('done',False),('text',''),('reasoning','thought'),('timings',{'cache_n':1})]:
            bad = dict(good, **{key:value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                bench.validate(bad,7,solo=True)
        with self.assertRaises(ValueError): bench.validate(good,8,solo=True)
        with self.assertRaises(ValueError): bench.require_idle({'loaded':True,'activity':{'in_flight':1}})
        bench.require_idle({'loaded':True,'activity':{'in_flight':0}})
        bench.validate(good,7,solo=False,smoke=True)
        with self.assertRaises(ValueError): bench.validate(dict(good,finish_reason='length'),7,solo=False,smoke=True)

class PlanTests(unittest.TestCase):
    def test_screen_rotates_distinct_prebuilt_repetitions_and_warmup(self):
        self.assertTrue(hasattr(bench,'make_plan'), 'fixture planner missing')
        fixtures = {c:{'repetitions':[{'messages':[{'role':'user','content':f'{c}-{i} unique'}], 'prompt_tokens':7+i} for i in range(3)]} for c in bench.SCREEN_CASES}
        plan = bench.make_plan(fixtures,'screen')
        self.assertEqual(len(plan),19)
        self.assertTrue(plan[0]['warmup'])
        self.assertEqual(plan[1]['case'],bench.SCREEN_CASES[0])
        self.assertEqual(plan[7]['case'],bench.SCREEN_CASES[1])
        self.assertEqual(plan[13]['case'],bench.SCREEN_CASES[2])
        self.assertEqual(plan[0]['fixture']['messages'][0]['content'], 'Reply with OK only.')
        fixtures[bench.SCREEN_CASES[0]]['repetitions'][1] = fixtures[bench.SCREEN_CASES[0]]['repetitions'][0]
        with self.assertRaises(ValueError): bench.make_plan(fixtures,'screen')
        self.assertEqual([r['case'] for r in bench.make_plan({c:{'messages':[], 'prompt_tokens':1} for c in ('p120k_code','p250k_code')},'long')],['p120k_code','p250k_code'])

class SummaryTests(unittest.TestCase):
    def test_exact_completeness_and_unequal_repetition_medians(self):
        self.assertTrue(hasattr(bench,'summarize'), 'summary missing')
        rows = [dict(label='v',mode='screen',case='warmup',repetition=-1,warmup=True,ok=True)]
        for c in bench.SCREEN_CASES:
            for rep,tokens,wall in [(0,2,1),(1,100,2),(2,9,3)]:
                rows.append(dict(label='v',mode='screen',case=c,repetition=rep,warmup=False,ok=True,usage={'completion_tokens':tokens},wall_s=wall,ttft_s=wall/2,token_window_s=wall/3))
        result = bench.summarize(rows, 'screen', ['v'])
        self.assertEqual(result['pivot'][bench.SCREEN_CASES[0]]['v']['median_client_tokens_per_s'],3)
        self.assertEqual(result['measured_rows'],18)
        with self.assertRaises(ValueError): bench.summarize(rows[:-1],'screen',['v'])
        with self.assertRaises(ValueError): bench.summarize(rows,'screen',['v','missing'])
        with self.assertRaises(ValueError): bench.summarize(rows+[rows[-1]],'screen',['v'])

class RunnerTests(unittest.TestCase):
    def test_mock_sse_solo_recorder_body_fallback_failures_and_timeout(self):
        self.assertTrue(hasattr(bench,'run_campaign'), 'campaign runner missing')
        calls = []
        def transport(req, timeout):
            calls.append((req.full_url,req.data,timeout))
            if req.full_url.endswith('/v1/models'): return io.BytesIO(b'{"data":[{"id":"unit-test-model"}]}')
            if req.full_url.endswith('/v1/status'): return io.BytesIO(b'{"loaded":true,"activity":{"in_flight":0},"last_timings":{"cache_n":0}}')
            return sse()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)/'raw.jsonl'
            args = bench.arguments(['--base','http://127.0.0.1:18080','--out',str(out),'--label','unit-test','--mode','smoke','--timeout','23'])
            result = bench.run_campaign(args, transport=transport, gpu=lambda:{'error':'unit-test no GPU'})
            rows = [json.loads(line) for line in out.read_text().splitlines()]
            self.assertTrue(rows[0]['ok'])
            body = json.loads(next(data for url,data,_ in calls if url.endswith('/v1/chat/completions')))
            self.assertEqual(body['max_tokens'],64)
            self.assertEqual(body['temperature'],0)
            self.assertEqual(body['seed'],42)
            self.assertEqual(body['chat_template_kwargs'],{'enable_thinking':False})
            self.assertTrue(body['stream_options']['include_usage'])
            self.assertEqual(rows[0]['body_json'],next(data.decode() for url,data,_ in calls if url.endswith('/v1/chat/completions')))
            self.assertEqual(rows[0]['gpu_before']['error'],'unit-test no GPU')
            self.assertTrue(all(timeout==23 for _,_,timeout in calls))
            self.assertEqual(result['measured_rows'],1)
            def bad(req, timeout):
                if req.full_url.endswith('/v1/chat/completions'): return sse(done=False)
                return transport(req,timeout)
            with self.assertRaises(ValueError): bench.run_campaign(args,transport=bad,gpu=lambda:{})
            rows = [json.loads(line) for line in out.read_text().splitlines()]
            self.assertEqual(len(rows),2)
            self.assertFalse(rows[-1]['ok'])
            self.assertIn('missing DONE',rows[-1]['error'])
            self.assertEqual(rows[-1]['text'],'OK')

    def test_mock_concurrent_aggregate_actual_count_no_status_access(self):
        self.assertTrue(hasattr(bench,'run_campaign'), 'campaign runner missing')
        import threading
        gate = threading.Barrier(2)
        urls = []
        def transport(req,timeout):
            urls.append(req.full_url)
            if req.full_url.endswith('/v1/models'): return io.BytesIO(b'{"data":[{"id":"unit-test-model"}]}')
            gate.wait(timeout=5)
            return sse()
        with tempfile.TemporaryDirectory() as td:
            fixtures = Path(td)/'fixtures.json'
            fixtures.write_text(json.dumps({c:{'messages':[{'role':'user','content':c}], 'prompt_tokens':7} for c in ('p4k_code','p4k_prose')}))
            out = Path(td)/'raw.jsonl'
            args = bench.arguments(['--out',str(out),'--label','unit-test','--fixtures',str(fixtures),'--mode','concurrent'])
            result = bench.run_campaign(args,transport=transport,gpu=lambda:{})
            rows = [json.loads(line) for line in out.read_text().splitlines()]
            group = next(r for r in rows if r['kind']=='concurrent_group')
            self.assertEqual(group['completion_tokens'],4)
            self.assertAlmostEqual(group['actual_tokens_per_s'],4/group['wall_s'])
            self.assertFalse(any(u.endswith('/v1/status') for u in urls))
            self.assertEqual(result['measured_rows'],2)

class AdditionalSafetyTests(unittest.TestCase):
    def test_hidden_reasoning_tokens_rejected(self):
        r = bench.parse_sse(sse(),0,clock=lambda:1)
        r['usage']['completion_tokens_details'] = {'reasoning_tokens':1}
        with self.assertRaises(ValueError): bench.validate(r,7)

    def test_concurrent_identical_messages_refused(self):
        f = {'messages':[{'role':'user','content':'identical unit-test'}], 'prompt_tokens':7}
        with self.assertRaises(ValueError): bench.make_plan({'p4k_code':f,'p4k_prose':f},'concurrent')

    def test_offline_concurrent_requires_group_and_returns_actual_aggregate(self):
        rows = [dict(kind='request',label='v',mode='concurrent',case=c,repetition=0,warmup=False,ok=True,usage={'completion_tokens':2},wall_s=1,ttft_s=.1,token_window_s=.5) for c in ('p4k_code','p4k_prose')]
        with self.assertRaises(ValueError): bench.summarize(rows,'concurrent',['v'])
        group = dict(kind='concurrent_group',label='v',mode='concurrent',ok=True,completion_tokens=4,wall_s=2,actual_tokens_per_s=2)
        result = bench.summarize(rows+[group],'concurrent',['v'])
        self.assertEqual(result['concurrent_groups']['v']['actual_tokens_per_s'],2)

class RegressionTests(unittest.TestCase):
    def test_full_screen_long_fallback_and_foreign_traffic_offline_transport(self):
        calls = []
        foreign = [False]
        def transport(req,timeout):
            calls.append((req.full_url,timeout))
            if req.full_url.endswith('/v1/models'): return io.BytesIO(b'{"data":[{"id":"unit-test"}]}')
            if req.full_url.endswith('/v1/status'):
                return io.BytesIO(json.dumps({'loaded':True,'activity':{'in_flight':int(foreign[0])},'last_timings':{'cache_n':0}}).encode())
            body = json.loads(req.data)
            content = body['messages'][0]['content']
            self.assertEqual(body['max_tokens'],64 if content=='Reply with OK only.' else 128 if content.startswith('long') else 256)
            response = sse().getvalue().decode()
            # Explicit UNIT TEST transport: exercise documented solo status fallback.
            response = response.replace(', "timings": {"cache_n": 0, "predicted_per_second": 999}','')
            return io.BytesIO(response.encode())
        with tempfile.TemporaryDirectory() as td:
            fixtures = Path(td)/'fixtures.json'
            data = {c:{'repetitions':[{'messages':[{'role':'user','content':f'{c}-{i} unique'}], 'prompt_tokens':7} for i in range(3)]} for c in bench.SCREEN_CASES}
            data.update({c:{'messages':[{'role':'user','content':'long-'+c}], 'prompt_tokens':7} for c in bench.LONG_CASES})
            fixtures.write_text(json.dumps(data))
            out = Path(td)/'records.jsonl'
            args = bench.arguments(['--out',str(out),'--label','unit-test','--fixtures',str(fixtures),'--mode','screen'])
            result = bench.run_campaign(args,transport=transport,gpu=lambda:{})
            self.assertEqual(result['measured_rows'],18)
            rows = [json.loads(line) for line in out.read_text().splitlines()]
            self.assertEqual(len(rows),19)
            self.assertTrue(all(r['timings_source']=='solo_status_last_timings' for r in rows))
            self.assertEqual(args.timeout,300)
            args.mode='long'
            result = bench.run_campaign(args,transport=transport,gpu=lambda:{})
            self.assertEqual(result['measured_rows'],2)
            self.assertEqual(bench.arguments(['--out',str(out),'--label','unit-test','--fixtures',str(fixtures),'--mode','long']).timeout,900)
            foreign[0] = True
            before = sum(url.endswith('/v1/chat/completions') for url,_ in calls)
            with self.assertRaises(ValueError): bench.run_campaign(args,transport=transport,gpu=lambda:{})
            self.assertEqual(before,sum(url.endswith('/v1/chat/completions') for url,_ in calls))
            self.assertIn('foreign traffic',json.loads(out.read_text().splitlines()[-1])['error'])

    def test_gpu_probe_failure_is_data(self):
        with patch.object(bench.subprocess,'run',side_effect=FileNotFoundError('unit-test mock')):
            self.assertIn('FileNotFoundError',bench.gpu_snapshot()['error'])

if __name__ == '__main__': unittest.main()
