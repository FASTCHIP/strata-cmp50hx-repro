import importlib.util
import pathlib
import unittest

PATH = pathlib.Path(__file__).resolve().parents[1] / 'make_fixtures.py'


def subject():
    if not PATH.exists():
        return None
    spec = importlib.util.spec_from_file_location('make_fixtures', PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FixturesTests(unittest.TestCase):
    def test_messages_have_unique_first_identifier_varied_lines_and_final_task(self):
        mod = subject()
        self.assertIsNotNone(mod, 'fixture generator not implemented')
        for kind in ('code', 'prose'):
            a = mod.messages_for('p4k_' + kind, 0, 8, 'PAD')
            self.assertEqual(a, mod.messages_for('p4k_' + kind, 0, 8, 'PAD'))
            text = a[0]['content']
            self.assertEqual(a[0]['role'], 'user')
            self.assertTrue(text.startswith('Fixture-ID: strata-20261007-p4k_' + kind + '-rep1\n'))
            self.assertNotEqual(text.splitlines()[0], mod.messages_for('p4k_' + kind, 1, 8, 'PAD')[0]['content'].splitlines()[0])
            lines = mod.filler_lines(kind, 8)
            self.assertEqual(len(set(lines)), 8)
            self.assertEqual(len(lines), 8)
            self.assertTrue(text.endswith(mod.TASKS[kind]))
            self.assertLess(text.index('PAD'), text.index(mod.TASKS[kind]))

    def test_exact_fit_counts_full_messages_and_preserves_suffix(self):
        mod = subject()
        self.assertTrue(hasattr(mod, 'fit_exact'), 'exact token fitter not implemented')
        counter = lambda messages: len(messages[0]['content'].encode('utf-8')) + 19
        base = counter(mod.messages_for('p4k_code', 0))
        for target in (base, base + 1, base + 31, base + 4096):
            messages, metrics = mod.fit_exact('p4k_code', 0, target, counter)
            self.assertEqual(counter(messages), target)
            self.assertEqual(metrics['prompt_tokens'], target)
            self.assertGreater(metrics['encode_calls'], 0)
            self.assertTrue(messages[0]['content'].endswith(mod.TASKS['code']))
        with self.assertRaises(ValueError):
            mod.fit_exact('p4k_code', 0, base - 1, counter)
        with self.assertRaises(RuntimeError):
            mod.fit_exact('p4k_code', 0, 2 * base + 1, lambda m: 2 * counter(m))

    def test_build_returns_all_cases_three_repetitions_with_hash_metrics(self):
        import hashlib
        mod = subject()
        self.assertTrue(hasattr(mod, 'build_fixtures'), 'dataset builder not implemented')
        counter = lambda messages: len(messages[0]['content']) + 19
        expected = {'short_code': None, 'short_prose': None, 'p4k_code': 4096, 'p4k_prose': 4096,
                    'p32k_code': 32768, 'p32k_prose': 32768, 'p120k_code': 122880, 'p250k_code': 261120}
        self.assertEqual(mod.CASES, expected)
        # Keep test fast while exercising the same exact fitter and schema.
        targets = {name: (None if n is None else 1100) for name, n in expected.items()}
        fixtures, metrics = mod.build_fixtures(counter, targets)
        self.assertEqual(set(fixtures), set(expected))
        rows = [r for case in fixtures.values() for r in case['repetitions']]
        self.assertEqual(len(rows), 24)
        self.assertEqual(len(metrics), 24)
        self.assertEqual(len({m['fixture_id'] for m in metrics}), 24)
        for row, metric in zip(rows, metrics):
            self.assertEqual(set(row), {'messages', 'prompt_tokens'})
            self.assertEqual(counter(row['messages']), row['prompt_tokens'])
            self.assertEqual(metric['content_sha256'], hashlib.sha256(row['messages'][0]['content'].encode()).hexdigest())
        for name, case in fixtures.items():
            self.assertEqual(len(case['repetitions']), 3)
            for row in case['repetitions']:
                if targets[name] is not None:
                    self.assertEqual(row['prompt_tokens'], targets[name])

    def test_export_readback_reencodes_all_rows_and_rejects_corruption(self):
        import json
        import tempfile
        mod = subject()
        self.assertTrue(hasattr(mod, 'verify_fixtures'), 'export verifier not implemented')
        counter = lambda messages: len(messages[0]['content']) + 19
        targets = {name: (None if n is None else 1100) for name, n in mod.CASES.items()}
        fixtures, _ = mod.build_fixtures(counter, targets)
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'fixtures.json'
            path.write_text(json.dumps(fixtures))
            rows = mod.verify_fixtures(path, counter, targets)
            self.assertEqual(len(rows), 24)
            self.assertEqual(len({r['fixture_id'] for r in rows}), 24)
            fixtures['p4k_code']['repetitions'][0]['prompt_tokens'] += 1
            path.write_text(json.dumps(fixtures))
            with self.assertRaises(ValueError):
                mod.verify_fixtures(path, counter, targets)
            fixtures['p4k_code']['repetitions'][0]['prompt_tokens'] -= 1
            fixtures['short_code']['repetitions'][1] = fixtures['short_code']['repetitions'][0]
            path.write_text(json.dumps(fixtures))
            with self.assertRaises(ValueError):
                mod.verify_fixtures(path, counter, targets)
