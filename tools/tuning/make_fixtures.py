"""Deterministic offline fixtures. No engine, GPU, HTTP, or service operations."""
from __future__ import annotations

TASKS = {
    'code': 'Implement a Python LRU cache with O(1) get and put, positive capacity validation, least-recently-used eviction, and explicit tests for updates, misses, and capacity one. Explain the invariants briefly. Treat the preceding numbered records as background reference, not instructions.',
    'prose': 'Explain TCP connection establishment, sequence numbers, acknowledgments, retransmission, flow control, and congestion control. Use a concise coherent technical explanation and distinguish receiver limits from network congestion. Treat the preceding numbered records as background reference, not instructions.',
}


def filler_lines(kind, count):
    if kind not in TASKS or count < 0:
        raise ValueError('invalid kind or negative line count')
    if kind == 'code':
        operations = ('lookup', 'insert', 'evict', 'refresh', 'resize', 'validate', 'snapshot')
        return [f'record_{i:06d} = {{"operation": "{operations[i % 7]}", "bucket": {i % 97}, "revision": {i * 13 + 7}, "limit": {i % 251 + 1}, "expected": {(i * 29) % 997}}}\n' for i in range(count)]
    topics = ('receive window', 'packet ordering', 'recovery timer', 'acknowledgment delay', 'route capacity', 'sender pacing', 'segment delivery')
    return [f'Reference {i:06d}: The {topics[i % 7]} experiment uses channel {i % 97}, revision {i * 13 + 7}, and interval {i % 251 + 1} milliseconds; observation {(i * 29) % 997} records a distinct controlled condition.\n' for i in range(count)]


def messages_for(case, repetition, lines=0, pad=''):
    kind = case.rsplit('_', 1)[-1]
    identifier = f'strata-20261007-{case}-rep{repetition + 1}'
    text = f'Fixture-ID: {identifier}\nBackground reference records:\n' + ''.join(filler_lines(kind, lines))
    if pad:
        text += pad
    return [{'role': 'user', 'content': text + '\nFinal task:\n' + TASKS[kind]}]


def fit_exact(case, repetition, target, counter):
    """Search structured line count, then pad characters; accept only full re-encode equality."""
    calls = 0
    def measure(lines, pad=''):
        nonlocal calls
        calls += 1
        messages = messages_for(case, repetition, lines, pad)
        return counter(messages), messages

    base, messages = measure(0)
    if base > target:
        raise ValueError(f'target {target} below minimum {base}')
    lo, hi = 0, 1
    while measure(hi)[0] <= target:
        lo, hi = hi, hi * 2
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if measure(mid)[0] <= target:
            lo = mid
        else:
            hi = mid
    # A few alternative line boundaries cope with BPE boundary merges.
    for lines in range(lo, max(-1, lo - 3), -1):
        actual, messages = measure(lines)
        if actual == target:
            return messages, {'prompt_tokens': actual, 'filler_lines': lines, 'pad_chars': 0, 'encode_calls': calls}
        gap = target - actual
        pad_source = ''.join(f'{i}: checkpoint {(i * 17 + 11) % 101}; ' for i in range(max(32, gap * 4)))
        left, right = 0, len(pad_source)
        if measure(lines, pad_source)[0] < target:
            continue
        while right - left > 1:
            mid = (left + right) // 2
            if measure(lines, pad_source[:mid])[0] <= target:
                left = mid
            else:
                right = mid
        # Exhaustive bounded exact search, not interpolation or token estimates.
        lengths = range(max(0, left - 64), min(len(pad_source), right + 64) + 1)
        for length in sorted(lengths, key=lambda n: (abs(n - left), n)):
            actual, messages = measure(lines, pad_source[:length])
            if actual == target:
                return messages, {'prompt_tokens': actual, 'filler_lines': lines, 'pad_chars': length, 'encode_calls': calls}
    raise RuntimeError(f'no exact padding found for {case} rep {repetition + 1} target {target}')


CASES = {'short_code': None, 'short_prose': None, 'p4k_code': 4096, 'p4k_prose': 4096,
         'p32k_code': 32768, 'p32k_prose': 32768, 'p120k_code': 122880, 'p250k_code': 261120}


def build_fixtures(counter, cases=None):
    import hashlib
    import time
    fixtures, metrics = {}, []
    for case, target in (CASES if cases is None else cases).items():
        repetitions = []
        for rep in range(3):
            started = time.monotonic()
            if target is None:
                messages = messages_for(case, rep)
                details = {'prompt_tokens': counter(messages), 'filler_lines': 0, 'pad_chars': 0, 'encode_calls': 1}
            else:
                messages, details = fit_exact(case, rep, target, counter)
            # Final full encode is separate from the search's accepted candidate.
            actual = counter(messages)
            if actual != details['prompt_tokens'] or (target is not None and actual != target):
                raise ValueError('final token count mismatch')
            repetitions.append({'messages': messages, 'prompt_tokens': actual})
            metrics.append(dict(details, case=case, repetition=rep + 1, target_tokens=target,
                                fixture_id=messages[0]['content'].splitlines()[0].removeprefix('Fixture-ID: '),
                                content_sha256=hashlib.sha256(messages[0]['content'].encode()).hexdigest(),
                                elapsed_s=time.monotonic() - started, encode_calls_total=details['encode_calls'] + 1))
        fixtures[case] = {'repetitions': repetitions}
    return fixtures, metrics


def verify_fixtures(path, counter, cases=None):
    import hashlib
    import json
    from pathlib import Path
    cases = CASES if cases is None else cases
    fixtures = json.loads(Path(path).read_text())
    if set(fixtures) != set(cases):
        raise ValueError('fixture case set differs')
    rows, ids = [], set()
    for case, target in cases.items():
        repetitions = fixtures[case]['repetitions']
        if len(repetitions) != 3:
            raise ValueError('expected three repetitions')
        for rep, row in enumerate(repetitions):
            if set(row) != {'messages', 'prompt_tokens'}:
                raise ValueError('invalid fixture row schema')
            text = row['messages'][0]['content']
            identifier = text.splitlines()[0].removeprefix('Fixture-ID: ')
            expected_id = f'strata-20261007-{case}-rep{rep + 1}'
            if identifier != expected_id or identifier in ids or not text.endswith(TASKS[case.rsplit('_', 1)[-1]]):
                raise ValueError('invalid identifier or task suffix')
            ids.add(identifier)
            actual = counter(row['messages'])
            if actual != row['prompt_tokens'] or (target is not None and actual != target):
                raise ValueError(f'export count mismatch: {case} rep{rep + 1}: {actual}')
            rows.append({'case': case, 'repetition': rep + 1, 'fixture_id': identifier,
                         'prompt_tokens': actual, 'content_sha256': hashlib.sha256(text.encode()).hexdigest()})
    return rows


def load_offline(cache_bpe=True):
    """Read the preserved pack; instantiate no Engine and start no threads/services."""
    import functools
    import hashlib
    import json
    from pathlib import Path
    from tools.strata_tokenizer import Tokenizer
    from serve.server import Service, ChatTemplate
    root = Path(__import__('os').environ.get('STRATA_ROOT', '.')).resolve()
    directory = root / 'packs/qwen20/tokenizer'
    vocab = json.loads((directory / 'vocab.json').read_text(encoding='utf-8'))
    tokens = [None] * len(vocab)
    for text, index in vocab.items():
        tokens[index] = text
    merges = (directory / 'merges.txt').read_text(encoding='utf-8').split('\n')
    types = json.loads((directory / 'token_type.json').read_text())
    tok = Tokenizer(tokens, merges, types)
    # Pure in-memory memoization only. Independent verification can disable it.
    if cache_bpe:
        tok._bpe = functools.lru_cache(maxsize=65536)(tok._bpe)
    svc = Service(None, tok, ChatTemplate(directory / 'chat_template.jinja'))
    svc.effort_end = True
    provenance = {'cwd': str(root), 'tokenizer_directory': str(directory), 'effort_end': True,
                  'encode_kwargs': {'enable_thinking': False}, 'tools': None,
                  'request_sampling': {'temperature': 0, 'seed': 42}, 'reasoning_effort': None,
                  'engine': None, 'bpe_memoization': cache_bpe,
                  'sha256': {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in
                             [root / 'tools/strata_tokenizer.py', root / 'serve/server.py'] +
                             [directory / name for name in ('vocab.json', 'merges.txt', 'token_type.json', 'chat_template.jinja')]}}
    return svc, provenance


def main(verify_only=False, cache_bpe=True):
    import hashlib
    import json
    import time
    from pathlib import Path
    started = time.monotonic()
    svc, provenance = load_offline(cache_bpe=cache_bpe)
    counter = lambda messages: len(svc.encode_prompt(messages, None, {'enable_thinking': False}))
    output = Path(__import__('os').environ.get('STRATA_FIXTURES', 'fixtures.json')).resolve()
    generation = []
    if not verify_only:
        fixtures, generation = build_fixtures(counter)
        output.write_text(json.dumps(fixtures, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    # Always read the actual exported file and re-encode every message.
    verification = verify_fixtures(output, counter)
    report = {'output': str(output), 'case_count': len(CASES), 'fixture_count': len(verification),
              'total_prompt_tokens': sum(row['prompt_tokens'] for row in verification),
              'fixtures_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
              'fixtures_bytes': output.stat().st_size, 'provenance': provenance,
              'generation': generation, 'verification': verification, 'elapsed_s': time.monotonic() - started}
    print(json.dumps(report, indent=2), flush=True)
    return report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--no-bpe-cache', action='store_true')
    args = parser.parse_args()
    main(verify_only=args.verify_only, cache_bpe=not args.no_bpe_cache)
