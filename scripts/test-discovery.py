#!/usr/bin/env python3
"""Focused regressions for discovery contracts and source/export drift.

Mutations happen only in temporary copies. No network access, deployment or
model calls are involved. These tests exercise actual rejected failures rather
than rebuilding the expected catalogs with the production generator.
"""
import copy
import hashlib
import json
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
CHECKS = runpy.run_path(str(ROOT / 'scripts/validate-discovery.py'))
ESSAY_CHECKS = runpy.run_path(str(ROOT / 'scripts/validate-essays.py'))
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

    def test_new_hierarchical_identifier_requires_explicit_registration(self):
        template = next(resource for resource in CHECKS['RESOURCES']
                        if resource.media_type == 'text/markdown')
        resource = replace(template, identifier='urn:air:vadimohka.ru:docs:home:summary',
                           path='index.html.md', source_page='index.html')
        for path in (AI, ARD):
            with self.subTest(path=path):
                document = read_json(ROOT / path)
                entry = copy.deepcopy(next(entry for entry in document['entries']
                                           if entry['identifier'] == template.identifier))
                entry.update(identifier=resource.identifier,
                             url=CHECKS['BASE'] + resource.path)
                document['entries'].append(entry)
                with self.assertRaisesRegex(ValueError, 'resource inventory differs'):
                    CHECKS['validate_catalog_document'](path, document)
                with patch.dict(CHECKS['validate_catalog_document'].__globals__,
                                RESOURCES=CHECKS['RESOURCES'] + (resource,)):
                    CHECKS['validate_catalog_document'](path, document)


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

    def mutate_graph(self, path, mutate):
        target = self.root / path
        source = target.read_text(encoding='utf-8')
        pattern = r'(<script type="application/ld\+json">)(.*?)(</script>)'
        match = re.search(pattern, source, re.S)
        self.assertIsNotNone(match)
        graph = json.loads(match[2])
        mutate(graph['@graph'])
        replacement = match[1] + json.dumps(graph, ensure_ascii=False, separators=(',', ':')) + match[3]
        target.write_text(source[:match.start()] + replacement + source[match.end():], encoding='utf-8')

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

    def test_llms_indexes_require_their_page_and_support_navigation(self):
        cases = (
            ('llms.txt', 'background/index.html.md', 'projects/index.html.md'),
            ('llms.txt', 'llms-full.txt', 'llms.txt'),
            ('projects/llms.txt', 'projects/index.html.md', 'context/index.html.md'),
            ('projects/llms.txt', 'projects/', 'approach/'),
        )
        for path, before, after in cases:
            with self.subTest(path=path, target=before):
                target = self.root / path
                original = target.read_text(encoding='utf-8')
                try:
                    self.replace(path, f'({CHECKS["BASE"]}{before})',
                                 f'({CHECKS["BASE"]}{after})')
                    with self.assertRaisesRegex(ValueError, 'missing navigation target'):
                        CHECKS['validate_site'](self.root)
                finally:
                    target.write_text(original, encoding='utf-8')

    def test_llms_indexes_check_additional_local_links(self):
        for path in ('llms.txt', 'projects/llms.txt'):
            with self.subTest(path=path):
                target = self.root / path
                original = target.read_text(encoding='utf-8')
                try:
                    target.write_text(original + '\n- [Дополнительный раздел]('
                                      + CHECKS['BASE'] + 'missing-page.md)\n', encoding='utf-8')
                    with self.assertRaisesRegex(ValueError, 'Missing or unsafe resource'):
                        CHECKS['validate_site'](self.root)
                    target.write_text(original + '\n- [Дополнительный раздел]('
                                      + CHECKS['BASE'] + 'context/)\n', encoding='utf-8')
                    CHECKS['validate_site'](self.root)
                finally:
                    target.write_text(original, encoding='utf-8')

    def test_representation_navigation_stays_with_its_source_page(self):
        for path in ('projects/index.html', 'llm/projects/index.html'):
            original = (self.root / path).read_text(encoding='utf-8')
            prefix = CHECKS['BASE'] if path.startswith('llm/') else '/'
            cases = [
                ('canonical',
                 f'<link rel="canonical" href="{CHECKS["BASE"]}projects/">',
                 f'<link rel="canonical" href="{CHECKS["BASE"]}approach/">'),
                ('canonical without target',
                 f'<link rel="canonical" href="{CHECKS["BASE"]}projects/">',
                 '<link rel="canonical">'),
                ('Markdown',
                 f'<link rel="alternate" type="text/markdown" href="{prefix}projects/index.html.md">',
                 f'<link rel="alternate" type="text/markdown" href="{prefix}approach/index.html.md">'),
                ('scoped index',
                 f'<link rel="describedby" type="text/plain" href="{prefix}projects/llms.txt">',
                 f'<link rel="describedby" type="text/plain" href="{prefix}approach/llms.txt">'),
            ]
            if not path.startswith('llm/'):
                cases.append(('text HTML', 'href="/llm/projects/"', 'href="/llm/approach/"'))
            for label, before, after in cases:
                with self.subTest(path=path, relation=label):
                    try:
                        self.replace(path, before, after)
                        with self.assertRaisesRegex(ValueError, 'wrong .* target'):
                            CHECKS['validate_site'](self.root)
                    finally:
                        (self.root / path).write_text(original, encoding='utf-8')

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
        sources = CHECKS['PAGES']
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

    def test_essay_article_body_count_and_attribution_are_verified_from_html(self):
        path = 'essays/revising-my-architecture/index.html'
        target = self.root / path
        original = target.read_text(encoding='utf-8')
        cases = (
            ('body', lambda article: article.update(articleBody='Текст был потерян.'), 'body differs'),
            ('count', lambda article: article.update(wordCount=1), 'wordCount differs'),
            ('author', lambda article: article.update(author={'@id': 'https://example.invalid/person'}), 'author or publisher'),
            ('date', lambda article: article.update(datePublished='2020-01-01'), 'date differs'),
        )
        for label, mutate, error in cases:
            with self.subTest(label=label):
                try:
                    self.mutate_graph(path, lambda graph: mutate(next(node for node in graph if node.get('@type') == 'Article')))
                    with self.assertRaisesRegex(ValueError, error):
                        ESSAY_CHECKS['validate_essays'](self.root)
                finally:
                    target.write_text(original, encoding='utf-8')

    def test_visible_essay_date_cannot_drift_from_structured_data(self):
        path = 'essays/revising-my-architecture/index.html'
        target = self.root / path
        source = target.read_text(encoding='utf-8')
        changed, count = re.subn(r'(<time\b[^>]*\bdatetime=")[^"]+', r'\g<1>2020-01-01', source, count=1)
        self.assertEqual(count, 1)
        target.write_text(changed, encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'visible publication date'):
            ESSAY_CHECKS['validate_essays'](self.root)

    def test_visible_essay_date_label_must_agree_with_its_iso_date(self):
        path = 'essays/revising-my-architecture/index.html'
        target = self.root / path
        source = target.read_text(encoding='utf-8')
        changed, count = re.subn(r'(<time\b[^>]*>).*?(</time>)',
                                 r'\g<1>31 декабря 1999\g<2>', source, count=1, flags=re.S)
        self.assertEqual(count, 1)
        target.write_text(changed, encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'visible publication label'):
            ESSAY_CHECKS['validate_essays'](self.root)
        result = self.run_generator('--write', expect_ok=False)
        self.assertIn('visible publication label', result.stderr)

    def test_archive_card_date_must_belong_to_its_article(self):
        target = self.root / 'essays/index.html'
        original = target.read_text(encoding='utf-8')
        for change_label_too in (False, True):
            with self.subTest(change_label_too=change_label_too):
                try:
                    changed, count = re.subn(r'(<time\b[^>]*\bdatetime=")[^"]+',
                                             r'\g<1>1999-12-31', original, count=1)
                    self.assertEqual(count, 1)
                    if change_label_too:
                        changed = re.sub(r'(<time\b[^>]*>).*?(</time>)',
                                         r'\g<1>31 декабря 1999\g<2>', changed, count=1, flags=re.S)
                    target.write_text(changed, encoding='utf-8')
                    with self.assertRaisesRegex(ValueError, 'archive card publication date differs from article'):
                        ESSAY_CHECKS['validate_essays'](self.root)
                finally:
                    target.write_text(original, encoding='utf-8')

    def test_archive_card_date_label_must_agree_with_its_iso_date(self):
        target = self.root / 'essays/index.html'
        source = target.read_text(encoding='utf-8')
        changed, count = re.subn(r'(<time\b[^>]*>).*?(</time>)',
                                 r'\g<1>31 декабря 1999\g<2>', source, count=1, flags=re.S)
        self.assertEqual(count, 1)
        target.write_text(changed, encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'archive card publication label'):
            ESSAY_CHECKS['validate_essays'](self.root)

    def test_consistent_archive_exports_cannot_hide_wrong_chronological_order(self):
        target = self.root / 'essays/index.html'
        source = target.read_text(encoding='utf-8')
        cards = list(re.finditer(r'<article\b[^>]*class="essay-card"[^>]*>.*?</article>', source, re.S))
        self.assertGreaterEqual(len(cards), 2)
        first, second = cards[:2]
        dates = [re.search(r'<time\b[^>]*datetime="([^"]+)"', card[0])[1]
                 for card in (first, second)]
        self.assertGreater(dates[0], dates[1], 'Fixture needs different publication dates in descending order')
        target.write_text(source[:first.start()] + second[0] + source[first.end():second.start()]
                          + first[0] + source[second.end():], encoding='utf-8')
        # Regenerate ItemList, hasPart and RSS in the same wrong order. A check
        # against another export would pass; the independent date check must fail.
        self.run_generator('--write')
        self.run_generator('--check')
        with self.assertRaisesRegex(ValueError, 'publication date descending'):
            ESSAY_CHECKS['validate_essays'](self.root)

    def test_essay_breadcrumb_requires_the_archive_level(self):
        path = 'essays/revising-my-architecture/index.html'
        def mutate(graph):
            crumb = next(node for node in graph if node.get('@type') == 'BreadcrumbList')
            crumb['itemListElement'].pop(1)
        self.mutate_graph(path, mutate)
        with self.assertRaisesRegex(ValueError, 'breadcrumb hierarchy'):
            ESSAY_CHECKS['validate_essays'](self.root)

    def test_essay_itemlist_cannot_silently_drop_a_visible_article(self):
        def mutate(graph):
            listing = next(node for node in graph if node.get('@type') == 'ItemList')
            listing['itemListElement'].pop()
            listing['numberOfItems'] -= 1
        self.mutate_graph('essays/index.html', mutate)
        with self.assertRaisesRegex(ValueError, 'ItemList differs'):
            ESSAY_CHECKS['validate_essays'](self.root)

    def test_essay_feed_preserves_inventory_and_date_precision(self):
        target = self.root / 'essays/feed.xml'
        original = target.read_text(encoding='utf-8')
        dc_date = '{http://purl.org/dc/elements/1.1/}date'
        for mutation in ('missing', 'invented-time', 'missing-dc-date', 'wrong-dc-date',
                         'datetime-in-dc-date', 'duplicate-dc-date', 'unnamespaced-date'):
            with self.subTest(mutation=mutation):
                try:
                    tree = ET.fromstring(original)
                    channel = tree.find('channel')
                    item = channel.find('item')
                    if mutation == 'missing':
                        channel.remove(item)
                    elif mutation == 'invented-time':
                        ET.SubElement(item, 'pubDate').text = 'Mon, 02 Nov 2026 12:00:00 +0300'
                    else:
                        published = item.find(dc_date)
                        self.assertIsNotNone(published, 'Fixture needs a day-precision dc:date')
                        if mutation == 'missing-dc-date':
                            item.remove(published)
                        elif mutation == 'wrong-dc-date':
                            published.text = '1999-12-31'
                        elif mutation == 'datetime-in-dc-date':
                            published.text += 'T00:00:00+03:00'
                        elif mutation == 'duplicate-dc-date':
                            item.append(copy.deepcopy(published))
                        elif mutation == 'unnamespaced-date':
                            published.tag = 'date'
                    target.write_text(ET.tostring(tree, encoding='unicode'), encoding='utf-8')
                    with self.assertRaisesRegex(ValueError, 'RSS items differ|RSS invents|RSS dc:date differs'):
                        ESSAY_CHECKS['validate_essays'](self.root)
                finally:
                    target.write_text(original, encoding='utf-8')

    def test_essay_archive_index_must_reach_every_full_text(self):
        self.replace('essays/llms.txt',
                     '(https://vadimohka.ru/essays/shared-understanding/index.html.md)',
                     '(https://vadimohka.ru/essays/index.html.md)')
        with self.assertRaisesRegex(ValueError, 'missing navigation target'):
            CHECKS['validate_site'](self.root)

    def test_essay_source_update_reaches_all_reading_formats_and_schema(self):
        path = 'essays/revising-my-architecture/index.html'
        target = self.root / path
        marker = 'Контрольный абзац для проверки полного текста эссе.'
        source, count = re.subn(r'(<div\b[^>]*\bid="essay-body"[^>]*>)',
                                lambda match: match[1] + '<p>' + marker + '</p>',
                                target.read_text(encoding='utf-8'), count=1)
        self.assertEqual(count, 1)
        target.write_text(source, encoding='utf-8')
        self.run_generator('--check', expect_ok=False)
        self.run_generator('--write')
        for name in (path, path + '.md', 'llm/' + path, 'llms-full.txt'):
            self.assertIn(marker, (self.root / name).read_text(encoding='utf-8'))
        ESSAY_CHECKS['validate_essays'](self.root)
        CHECKS['validate_site'](self.root)


if __name__ == '__main__':
    unittest.main(verbosity=2)
