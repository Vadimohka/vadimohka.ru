#!/usr/bin/env python3
"""Regressions for false evidence and lost diagnostics in the HTTP reader.

Only transport is replaced with recorded public files. The actual parser,
discovery traversal, evidence checks and CLI report writer run unchanged.
CI also exercises the client against a real temporary HTTP server.
"""
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('discovery_client', ROOT / 'scripts/check-discovery-client.py')
CLIENT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLIENT)


class Response(io.BytesIO):
    status = 200

    def __init__(self, text, media_type):
        super().__init__(text.encode('utf-8'))
        self.headers = Message()
        self.headers['Content-Type'] = media_type + '; charset=utf-8'


class Transport:
    def __init__(self, files):
        self.files = files

    def open(self, request, timeout):
        path = urlsplit(request.full_url).path
        if path not in self.files:
            raise HTTPError(request.full_url, 404, 'Not Found', Message(), None)
        media_type, text = self.files[path]
        return Response(text, media_type)


class ReaderRegressions(unittest.TestCase):
    def setUp(self):
        self.files = {'/': ('text/html', (ROOT / 'index.html').read_text(encoding='utf-8'))}
        for path in ('.well-known/ai-catalog.json', '.well-known/ard.json'):
            self.files['/' + path] = ('application/json', (ROOT / path).read_text(encoding='utf-8'))
        entries = json.loads(self.files['/.well-known/ai-catalog.json'][1])['entries']
        for entry in entries:
            path = urlsplit(entry['url']).path
            self.files[path] = (entry['type'], (ROOT / path.lstrip('/')).read_text(encoding='utf-8'))

    def reader(self):
        reader = CLIENT.Reader('https://vadimohka.ru/', 1)
        reader.opener = Transport(self.files)
        return reader

    def mutate_json(self, path, mutate):
        media_type, text = self.files[path]
        document = json.loads(text)
        mutate(document)
        self.files[path] = (media_type, json.dumps(document, ensure_ascii=False))

    def test_current_public_documents_provide_all_seven_scenarios(self):
        report = self.reader().check()
        self.assertEqual(report['status'], 'pass')
        self.assertEqual(len(report['evidenceChecks']), 7)
        self.assertEqual(len(report['requests']), 9)

    def test_non_json_constants_are_rejected_in_catalogs_and_profile(self):
        for path in ('/.well-known/ai-catalog.json', '/.well-known/ard.json', '/person.jsonld'):
            original = self.files[path]
            for value in (float('nan'), float('inf'), float('-inf')):
                with self.subTest(path=path, value=value):
                    self.files[path] = original
                    self.mutate_json(path, lambda document: document.update(invalid=value))
                    with self.assertRaisesRegex(ValueError, 'Non-JSON number'):
                        self.reader().check()
            self.files[path] = original

    def test_canonical_id_and_role_do_not_prove_a_different_identity(self):
        original = self.files['/person.jsonld']
        for field, value in (('name', 'Другое лицо'), ('@type', 'Organization')):
            with self.subTest(field=field):
                self.files['/person.jsonld'] = original
                self.mutate_json('/person.jsonld', lambda doc: next(
                    node for node in doc['@graph'] if node['@id'] == CLIENT.PERSON_ID).update({field: value}))
                with self.assertRaisesRegex(ValueError, 'approved person name and type'):
                    self.reader().check()

    def test_source_urls_must_be_exact_markdown_destinations(self):
        cases = (
            ('/projects/index.html.md', 'https://century-ai.by', 'https://century-ai.by.example.invalid', 'experience'),
            ('/projects/index.html.md', 'https://github.com/Vadimohka/belka',
             'https://githubXcom/Vadimohka/belka-broken', 'Belka'),
            ('/projects/index.html.md', 'https://github.com/Vadimohka/Multiverse',
             'https://github.com/Vadimohka/Multiverse-unrelated', 'Multiverse'),
            ('/context/index.html.md', 'https://stepik.org/course/86957/promo',
             'https://example.invalid/?source=https://stepik.org/course/86957/promo', 'Research or teaching'),
            ('/llms.txt', 'https://vadimohka.ru/background/index.html.md',
             'https://vadimohka.ru/background/index.html.md-missing', 'Reading index'),
        )
        for path, original_url, wrong_url, error in cases:
            with self.subTest(path=path, url=wrong_url):
                original = self.files[path]
                self.assertIn(original_url, original[1])
                self.files[path] = (original[0], original[1].replace(original_url, wrong_url))
                try:
                    with self.assertRaisesRegex(ValueError, error):
                        self.reader().check()
                finally:
                    self.files[path] = original

    def test_workflow_needs_distinct_steps_with_explanations(self):
        path = '/approach/index.html.md'
        for text in (
            ''.join('### 01. Повтор\nОбъяснение.\n\n' for _ in range(5)),
            ''.join(f'### {number:02}. Шаг\n\n' for number in range(1, 6)),
        ):
            with self.subTest(text=text):
                self.files[path] = ('text/markdown', text)
                with self.assertRaisesRegex(ValueError, 'distinct steps 01–05'):
                    self.reader().check()

    def run_cli(self, report):
        with patch.object(CLIENT, 'build_opener', return_value=Transport(self.files)), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as stderr:
            result = CLIENT.main(['--report', str(report)])
        return result, stderr.getvalue(), json.loads(report.read_text(encoding='utf-8'))

    def test_http_failure_preserves_completed_requests_and_failed_url(self):
        self.files.pop('/.well-known/ard.json')
        with tempfile.TemporaryDirectory() as directory:
            result, stderr, report = self.run_cli(Path(directory) / 'trace.json')
        self.assertEqual(result, 1)
        self.assertIn('404', stderr)
        self.assertEqual(report['status'], 'failed')
        self.assertEqual([item['status'] for item in report['requests']], ['pass', 'pass', 'failed'])
        self.assertEqual(report['requests'][-1]['canonicalUrl'], 'https://vadimohka.ru/.well-known/ard.json')
        self.assertEqual(report['requests'][-1]['httpStatus'], 404)
        self.assertEqual(len(report['catalogs']), 1)

    def test_invalid_contact_is_a_reported_failure_with_partial_evidence(self):
        self.mutate_json('/person.jsonld', lambda doc: next(
            node for node in doc['@graph'] if node['@id'] == CLIENT.PERSON_ID).update(email=[]))
        with tempfile.TemporaryDirectory() as directory:
            result, stderr, report = self.run_cli(Path(directory) / 'trace.json')
        self.assertEqual(result, 1)
        self.assertIn('contact differ', stderr)
        self.assertEqual(report['status'], 'failed')
        self.assertIn('contact differ', report['error'])
        self.assertEqual(len(report['requests']), 9)
        self.assertEqual(len(report['evidenceChecks']), 6)


if __name__ == '__main__':
    unittest.main(verbosity=2)
