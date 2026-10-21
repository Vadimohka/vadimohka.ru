#!/usr/bin/env python3
"""Focused delivery regressions: stale edges, corrupt responses and dotfiles."""
import hashlib
import importlib.util
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('delivery_checker_tests', ROOT / 'scripts/check-live-discovery.py')
checker = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = checker
spec.loader.exec_module(checker)
build_spec = importlib.util.spec_from_file_location('delivery_builder_tests', ROOT / 'scripts/build-site.py')
builder = importlib.util.module_from_spec(build_spec)
sys.modules[build_spec.name] = builder
build_spec.loader.exec_module(builder)


def record(body=b'{"version":2}', path='payload.json'):
    return {'path': path, 'role': 'test-resource', 'public_url_path': '/' + path,
            'transport_mime_types': ['application/json'], 'format': 'json',
            'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}


class Clock:
    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class DeliveryTests(unittest.TestCase):
    def test_stale_body_retries_the_normal_url_until_it_matches(self):
        item, clock, urls = record(), Clock(), []

        def fetch(url, timeout, expected_bytes):
            urls.append(url)
            body = b'{"version":1}' if len(urls) == 1 else b'{"version":2}'
            return checker.Response(200, 'application/json; charset=utf-8', body, url)

        report = checker.check_inventory({'files': [item]}, 'https://example.test', fetch=fetch,
                                         clock=clock.time, sleep=clock.sleep, retry_interval=0.1,
                                         progress=lambda message: None)
        self.assertEqual(urls, ['https://example.test/payload.json'] * 2)
        self.assertEqual(report['resources'][0]['attempts'], 2)
        self.assertEqual(report['resources'][0]['sha256'], item['sha256'])

    def test_wrong_mime_and_html_fallback_are_not_success(self):
        item = record()
        url = 'https://example.test/payload.json'
        for content_type, body, reason in (
            ('text/html', b'<html>fallback</html>', 'Content-Type'),
            ('application/json', b'<!doctype html><html>fallback</html>', 'HTML fallback'),
            ('application/json', b'{"version":', 'invalid json'),
            ('application/json', b'{"version":2,"version":3}', 'Duplicate JSON key'),
        ):
            with self.subTest(reason=reason), self.assertRaisesRegex(checker.DeliveryError, reason):
                checker.validate_response(item, checker.Response(200, content_type, body, url), url)

    def test_persistent_stale_body_has_one_shared_deadline(self):
        clock, timeouts = Clock(), []

        def fetch(url, timeout, expected_bytes):
            timeouts.append(timeout)
            return checker.Response(200, 'application/json', b'{"version":1}', url)

        with self.assertRaisesRegex(checker.DeliveryError, 'Overall deadline exceeded'):
            checker.check_inventory({'files': [record()]}, 'https://example.test', fetch=fetch,
                                    deadline=0.25, request_timeout=10, retry_interval=0.1,
                                    clock=clock.time, sleep=clock.sleep, progress=lambda message: None)
        self.assertAlmostEqual(clock.now, 0.25)
        self.assertEqual(len(timeouts), 3)
        self.assertTrue(all(value <= 0.25 for value in timeouts))
        self.assertLess(timeouts[-1], timeouts[0])

    def test_missing_resource_can_appear_during_propagation(self):
        clock, attempts = Clock(), []

        def fetch(url, timeout, expected_bytes):
            attempts.append(url)
            if len(attempts) == 1:
                return checker.Response(404, 'text/html', b'not found', url)
            return checker.Response(200, 'application/json', b'{"version":2}', url)

        report = checker.check_inventory({'files': [record()]}, 'https://example.test', fetch=fetch,
                                         clock=clock.time, sleep=clock.sleep, progress=lambda message: None)
        self.assertEqual(report['checked_resources'], 1)
        self.assertEqual(len(attempts), 2)

    def test_matching_hash_still_requires_the_catalog_schema(self):
        item = record(b'{}', '.well-known/ai-catalog.json')
        url = 'https://example.test/' + item['path']

        def invalid_schema(path, document):
            raise ValueError('entries is required')

        with self.assertRaisesRegex(checker.DeliveryError, 'schema or resource contract failed'):
            checker.validate_response(item, checker.Response(200, 'application/json', b'{}', url),
                                      url, invalid_schema)

    def test_redirect_does_not_hide_a_wrong_public_path(self):
        with self.assertRaisesRegex(checker.DeliveryError, 'unexpected redirect'):
            checker.validate_response(record(), checker.Response(200, 'application/json', b'{"version":2}',
                                      'https://example.test/other.json'), 'https://example.test/payload.json')

    def test_snapshot_must_include_hidden_catalog_files(self):
        (ROOT / '_dist').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / '_dist') as name:
            directory = Path(name)
            item = record(path='.well-known/ai-catalog.json')
            with self.assertRaisesRegex(checker.DeliveryError, 'missing: .well-known/ai-catalog.json'):
                checker.verify_artifact({'files': [item]}, directory)
            (directory / '.well-known').mkdir()
            (directory / item['path']).write_bytes(b'{"version":2}')
            checker.verify_artifact({'files': [item]}, directory)


    def test_linked_asset_omitted_from_dist_is_a_build_error(self):
        (ROOT / '_dist').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / '_dist') as name:
            directory = Path(name)
            (directory / 'index.html').write_text('<link rel="stylesheet" href="/assets/new.css">')
            with self.assertRaisesRegex(ValueError, 'absent from dist: /assets/new.css'):
                builder.validate_staged_references(directory)
            (directory / 'assets').mkdir()
            (directory / 'assets/new.css').write_text('body {background-image: url("new.webp")}')
            with self.assertRaisesRegex(ValueError, 'absent from dist: new.webp'):
                builder.validate_staged_references(directory)
            (directory / 'assets/new.webp').write_bytes(b'image fixture')
            builder.validate_staged_references(directory)


    def test_build_never_replaces_a_symlink_destination(self):
        (ROOT / '_dist').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / '_dist') as name:
            directory = Path(name)
            target = directory / 'keep'
            target.mkdir()
            (target / 'sentinel').write_text('preserve')
            link = directory / 'linked-dist'
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'symbolic links'):
                builder.build(link, directory / 'inventory.json')
            self.assertEqual((target / 'sentinel').read_text(), 'preserve')


class HttpDeliveryTests(unittest.TestCase):
    def test_real_http_get_and_curl_transport_retry_stale_content(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(('GET', self.path))
                body = b'{"version":1}' if len(requests) == 1 else b'{"version":2}'
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_HEAD(self):
                requests.append(('HEAD', self.path))
                self.send_error(405)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            report = checker.check_inventory({'files': [record()]},
                                             'http://127.0.0.1:' + str(server.server_port),
                                             deadline=5, request_timeout=2, retry_interval=0.05,
                                             progress=lambda message: None)
            self.assertEqual(report['checked_resources'], 1)
            self.assertEqual(requests, [('GET', '/payload.json')] * 2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
