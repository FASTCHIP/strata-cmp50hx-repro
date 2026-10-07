#!/usr/bin/env python3
"""Offline-only verification of the 2026-10-07 engine update; stdlib, no network."""
import json
import pathlib
import statistics
from collections import Counter

SCREEN_CASES = ('short_code', 'short_prose', 'p4k_code', 'p4k_prose', 'p32k_code', 'p32k_prose')
LONG_CASES = ('p120k_code',)
MODES = ('smoke', 'screen', 'long', 'concurrent')
ARMS = ('old', 'new')


def summarize(rows, mode, label):
    requests = [r for r in rows if r['kind'] == 'request']
    cases = SCREEN_CASES if mode == 'screen' else LONG_CASES if mode == 'long' else ('p4k_code', 'p4k_prose') if mode == 'concurrent' else ('smoke',)
    expected = Counter((c, rep, False) for c in cases for rep in (range(3) if mode == 'screen' else range(1)))
    if mode == 'screen':
        expected[('warmup', -1, True)] = 1
    assert Counter((r['case'], r['repetition'], r['warmup']) for r in requests) == expected
    pivot = {}
    for case in cases:
        g = [r for r in requests if r['case'] == case and not r['warmup']]
        pivot[case] = {label: {
            'n': len(g),
            'actual_completion_tokens': [r['usage']['completion_tokens'] for r in g],
            'median_client_tokens_per_s': statistics.median(r['usage']['completion_tokens'] / r['wall_s'] for r in g),
            'median_wall_s': statistics.median(r['wall_s'] for r in g),
            'median_ttft_s': statistics.median(r['ttft_s'] for r in g),
            'median_token_window_s': statistics.median(r['token_window_s'] for r in g),
        }}
    result = dict(mode=mode, labels=[label], measured_rows=sum(v[label]['n'] for v in pivot.values()), pivot=pivot)
    groups = [r for r in rows if r['kind'] == 'concurrent_group']
    if mode == 'concurrent':
        assert len(groups) == 1 and groups[0]['ok']
        group = groups[0]
        assert group['completion_tokens'] == sum(r['usage']['completion_tokens'] for r in requests)
        assert group['actual_tokens_per_s'] == group['completion_tokens'] / group['wall_s']
        result['concurrent_groups'] = {label: group}
    else:
        assert not groups
    return result


def recalculate(directory):
    directory = pathlib.Path(directory)
    allrows, counts, summaries = [], {}, {}
    for arm in ARMS:
        for mode in MODES:
            name = arm + '-' + mode
            rows = [json.loads(line) for line in (directory / (name + '.jsonl')).read_text().splitlines() if line.strip()]
            counts[name + '.jsonl'] = len(rows)
            assert len(rows) == {'smoke': 1, 'screen': 19, 'long': 1, 'concurrent': 3}[mode]
            for r in rows:
                assert r['label'] == arm and r['mode'] == mode and r['ok']
                if r['kind'] == 'concurrent_group':
                    continue
                assert r['done'] and r['nonempty_text'] and not r['reasoning_present']
                assert r['finish_reason'] in ('stop', 'length')
                assert r['usage']['completion_tokens'] == r['completion_tokens'] > 0
                assert not (r['usage'].get('completion_tokens_details') or {}).get('reasoning_tokens', 0)
                assert r['client_tokens_per_s'] == r['completion_tokens'] / r['wall_s']
                if r['expected_prompt_tokens'] is not None:
                    assert r['usage']['prompt_tokens'] == r['expected_prompt_tokens']
                if mode != 'concurrent' and not r['warmup']:
                    assert r['timings']['cache_n'] == 0
                if mode == 'smoke' or r['warmup']:
                    assert r['known_answer_ok'] and r['finish_reason'] == 'stop'
            allrows.extend(rows)
            summaries[name] = summarize(rows, mode, arm)
    comparisons = []
    for case in SCREEN_CASES + LONG_CASES:
        row: dict = {'case': case}
        for arm in ARMS:
            g = [r for r in allrows if r['kind'] == 'request' and r['mode'] in ('screen', 'long') and r['label'] == arm and r['case'] == case]
            row[arm] = {
                'n': len(g),
                'completion_tokens': [r['usage']['completion_tokens'] for r in g],
                'prompt_tokens': [r['usage']['prompt_tokens'] for r in g],
                'client_tps': statistics.median(r['usage']['completion_tokens'] / r['wall_s'] for r in g),
                'wall_s': statistics.median(r['wall_s'] for r in g),
                'ttft_s': statistics.median(r['ttft_s'] for r in g),
                'server_prefill_tps': statistics.median(r['timings']['prompt_per_second'] for r in g),
                'server_decode_tps': statistics.median(r['timings']['predicted_per_second'] for r in g),
            }
        for delta, metric in [('client_delta_pct', 'client_tps'), ('prefill_delta_pct', 'server_prefill_tps'), ('decode_delta_pct', 'server_decode_tps')]:
            row[delta] = (row['new'][metric] / row['old'][metric] - 1) * 100
        comparisons.append(row)
    concurrent = {a: summaries[a + '-concurrent']['concurrent_groups'][a] for a in ARMS}
    return {
        'comparisons': comparisons,
        'concurrent': concurrent,
        'concurrent_delta_pct': (concurrent['new']['actual_tokens_per_s'] / concurrent['old']['actual_tokens_per_s'] - 1) * 100,
        'raw_counts': counts,
        'summaries': summaries,
    }


if __name__ == '__main__':
    root = pathlib.Path(__file__).resolve().parents[2]
    directory = root / 'results/2026-10-07-update'
    result = recalculate(directory)
    assert result == json.loads((directory / 'COMPARISON.json').read_text()), 'Summary mismatch'
    manifest = json.loads((directory / 'PUBLICATION.json').read_text())
    import hashlib
    for name, expected in manifest['sha256'].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, 'Hash mismatch: ' + name
    print(json.dumps({'summary_equal': True, 'manifest_equal': True, 'request_rows': 46, 'warmups_excluded': 2, 'concurrent_groups': 2, 'client_delta_pct': [r['client_delta_pct'] for r in result['comparisons']], 'concurrent_delta_pct': result['concurrent_delta_pct']}, indent=2))
