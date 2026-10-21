#!/usr/bin/env python3
"""Focused regressions for discovery contracts and source/export drift.

Mutations happen only in temporary copies. No network access, deployment or
model calls are involved. These tests exercise actual rejected failures rather
than rebuilding the expected catalogs with the production generator.
"""
import copy
import hashlib
import json
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKS = runpy.run_path(str(ROOT / 'scripts/validate-discovery.py'))
AI = '.well-known/ai-catalog.json'
ARD = '.well-known/ard.json'


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


class CatalogContracts(unittest.TestCase):
    def test_whole_ard_manifest_is_validated(self):
        valid = read_json(ROOT / ARD)
        CHECKS['validate_catalog_document'](ARD, valid)
        with self.assertRaisesRegex(ValueError, 'schema violation'):
            CHECKS['validate_catalog_document'](ARD, valid['entries'][0])

    def test_structural_and_resource_contract_mutations(self):
        cases = (
            (AI, 'URL and inline payload', lambda doc: doc['entries'][0].update(data={})),
            (AI, 'runtime masquerading as document',
             lambda doc: doc['entries'][0].update(type='application/mcp-server-card+json')),
            (AI, 'off-domain resource',
             lambda doc: doc['entries'][0].update(url='https://example.invalid/person.jsonld')),
            (AI, 'duplicate resource',
             lambda doc: doc['entries'].append(copy.deepcopy(doc['entries'][0]))),
            (AI, 'unreviewed resource', lambda doc: doc['entries'][0].update(identifier='urn:air:vadimohka.ru:mcp:invented')),
            (ARD, 'missing required displayName', lambda doc: doc['entries'][0].pop('displayName')),
            (ARD, 'missing representative queries', lambda doc: doc['entries'][0].pop('representativeQueries')),
            (ARD, 'invalid query count', lambda doc: doc['entries'][0].update(representativeQueries=['Один вопрос?'])),
        )
        for path, label, mutate in cases:
            with self.subTest(label=label):
                document = read_json(ROOT / path)
                mutate(document)
                with self.assertRaises(ValueError):
                    CHECKS['validate_catalog_document'](path, document)

    def test_json_parser_rejects_duplicate_keys_and_non_json_numbers(self):
        for payload in ('{"entries": [], "entries": []}', '{"data": NaN}'):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                CHECKS['parse_json'](payload)


class SourceFidelity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='discovery-regression-', dir=ROOT.parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'site'
        shutil.copytree(ROOT, self.root, ignore=shutil.ignore_patterns(
            '.git', 'dist', '_dist', '_live', '__pycache__', '.venv', '.pytest_cache'))

    def replace(self, path, before, after):
        target = self.root / path
        text = target.read_text(encoding='utf-8')
        self.assertIn(before, text, f'Mutation fixture missing from {path}')
        target.write_text(text.replace(before, after), encoding='utf-8')

    def write_json(self, path, data):
        (self.root / path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def run_generator(self, mode, expect_ok=True):
        result = subprocess.run([sys.executable, 'scripts/sync-discovery.py', mode],
                                cwd=self.root, capture_output=True, text=True, timeout=30)
        if expect_ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, 'Stale source unexpectedly passed --check')
        return result

    def snapshot(self):
        return {str(path.relative_to(self.root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.root.rglob('*')
                if path.is_file() and '__pycache__' not in path.parts}

    def test_missing_resource_is_rejected(self):
        (self.root / 'background/index.html.md').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing or unsafe resource'):
            CHECKS['validate_site'](self.root)

    def test_missing_discovery_link_in_either_html_representation(self):
        for path in ('projects/index.html', 'llm/projects/index.html'):
            with self.subTest(path=path):
                target = self.root / path
                original = target.read_text(encoding='utf-8')
                target.write_text(original.replace('rel="ard"', 'rel="unrelated"'), encoding='utf-8')
                try:
                    with self.assertRaisesRegex(ValueError, 'expected one ard relation'):
                        CHECKS['validate_site'](self.root)
                finally:
                    target.write_text(original, encoding='utf-8')

    def test_source_link_must_survive_full_corpus(self):
        self.replace('llms-full.txt', 'https://stepik.org/course/86957/promo',
                     'https://example.invalid/removed-source')
        with self.assertRaisesRegex(ValueError, 'llms-full.txt: lost source link'):
            CHECKS['validate_site'](self.root)

    def test_two_consistently_stale_catalogs_do_not_override_editorial_html(self):
        for path in (AI, ARD):
            document = read_json(self.root / path)
            entry = next(entry for entry in document['entries']
                         if entry['url'] == 'https://vadimohka.ru/projects/index.html.md')
            entry['description'] = 'Несогласованное описание проектов.'
            self.write_json(path, document)
        with self.assertRaisesRegex(ValueError, 'catalog description is stale'):
            CHECKS['validate_site'](self.root)

    def test_changed_source_requires_regeneration_then_survives_exports(self):
        marker = 'Контрольная фраза проверки обновления.'
        self.replace('projects/index.html', 'Развиваю Century вместе с командой.',
                     'Развиваю Century вместе с командой. ' + marker)
        before_check = self.snapshot()
        self.run_generator('--check', expect_ok=False)
        self.assertEqual(self.snapshot(), before_check, '--check must not mutate the site')
        self.run_generator('--write')
        self.run_generator('--check')
        for name in ('projects/index.html.md', 'llms-full.txt', 'llm/projects/index.html'):
            self.assertIn(marker, (self.root / name).read_text(encoding='utf-8'))
        CHECKS['validate_site'](self.root)

    def test_project_maturity_cannot_be_silently_upgraded(self):
        self.replace('projects/index.html', 'Belka остаётся научным хобби',
                     'Belka остаётся готовым промышленным продуктом')
        self.run_generator('--write')
        with self.assertRaisesRegex(ValueError, 'Project maturity qualifier changed'):
            CHECKS['validate_site'](self.root)

    def test_schema_files_are_pinned(self):
        schema = self.root / 'scripts/schemas/ard-entry.schema.json'
        schema.write_text(schema.read_text(encoding='utf-8') + '\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Pinned specification changed'):
            CHECKS['validate_site'](self.root)

    def test_generation_is_idempotent_and_preserves_editorial_bodies(self):
        sources = ('index.html', 'background/index.html', 'projects/index.html',
                   'approach/index.html', 'context/index.html')
        bodies = {name: (self.root / name).read_text(encoding='utf-8').split('</head>', 1)[1]
                  for name in sources}
        protected = {name: (self.root / name).read_bytes() for name in
                     ('scripts/content/approach.md', 'assets/hero-vadim-2026.webp')}
        self.run_generator('--write')
        first = self.snapshot()
        self.run_generator('--write')
        self.assertEqual(first, self.snapshot(), 'Repeated generation changed files')
        self.run_generator('--check')
        for name, body in bodies.items():
            self.assertEqual(body, (self.root / name).read_text(encoding='utf-8').split('</head>', 1)[1], name)
        for name, data in protected.items():
            self.assertEqual(data, (self.root / name).read_bytes(), name)


if __name__ == '__main__':
    unittest.main(verbosity=2)
