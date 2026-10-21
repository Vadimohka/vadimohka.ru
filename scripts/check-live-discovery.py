#!/usr/bin/env python3
"""Verify every public build resource with GET, MIME, body and digest checks.

Uses ordinary URLs without cache-busting parameters. Missing or stale resources
are retried within one deadline; malformed responses fail without being mistaken
for a successful deployment. curl supplies connect and total request timeouts.
"""
import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from site_model import CATALOG_PATHS, ROOT


class DeliveryError(ValueError):
    def __init__(self, message, *, report=None):
        super().__init__(message)
        self.report = report


class RetryableError(Exception):
    pass


@dataclass
class Response:
    status: int
    content_type: str
    body: bytes
    effective_url: str


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DeliveryError('Duplicate JSON key: ' + key)
        result[key] = value
    return result


def invalid_constant(value):
    raise DeliveryError('Non-JSON number: ' + value)


def load_inventory(path):
    inventory = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_json, parse_constant=invalid_constant)
    if inventory.get('schema_version') != 1 or not isinstance(inventory.get('files'), list):
        raise DeliveryError('Unsupported or invalid inventory')
    seen_paths, seen_urls = set(), set()
    for item in inventory['files']:
        path = item.get('path', '')
        if not path or path.startswith('/') or '..' in Path(path).parts or path in seen_paths:
            raise DeliveryError('Unsafe or repeated inventory path: ' + path)
        seen_paths.add(path)
        if not re.fullmatch(r'[0-9a-f]{64}', item.get('sha256', '')):
            raise DeliveryError('Invalid digest in inventory: ' + path)
        if not isinstance(item.get('bytes'), int) or item['bytes'] < 0:
            raise DeliveryError('Invalid size in inventory: ' + path)
        url_path = item.get('public_url_path')
        if url_path is None:
            if path not in ('CNAME', '.nojekyll') or item.get('role') != 'hosting-control':
                raise DeliveryError('Only CNAME and .nojekyll can skip public GET checks')
            continue
        url = urlsplit(url_path)
        if not url_path.startswith('/') or url_path.startswith('//') or url.query or url.fragment or url.netloc:
            raise DeliveryError('Invalid public URL path: ' + url_path)
        if url_path in seen_urls:
            raise DeliveryError('Duplicate public URL in inventory: ' + url_path)
        seen_urls.add(url_path)
        if not item.get('transport_mime_types') or item.get('format') not in ('json', 'xml', 'html', 'text', 'binary'):
            raise DeliveryError('Missing transport contract: ' + path)
    if not seen_urls:
        raise DeliveryError('Inventory has no public resources')
    return inventory


def verify_artifact(inventory, directory):
    """Check the downloaded snapshot, including .well-known and hosting files."""
    expected = {item['path'] for item in inventory['files']}
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()}
    if actual != expected:
        raise DeliveryError('Snapshot differs from inventory; missing: ' + ', '.join(sorted(expected - actual))
                            + '; unexpected: ' + ', '.join(sorted(actual - expected)))
    for item in inventory['files']:
        path = directory / item['path']
        if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
            raise DeliveryError('Unsafe snapshot file: ' + item['path'])
        body = path.read_bytes()
        if len(body) != item['bytes'] or hashlib.sha256(body).hexdigest() != item['sha256']:
            raise DeliveryError('Snapshot digest mismatch: ' + item['path'])


class CurlFetcher:
    def __init__(self, connect_timeout):
        self.connect_timeout = connect_timeout
        if not shutil.which('curl'):
            raise DeliveryError('curl is required for bounded HTTP requests')

    def __call__(self, url, timeout, expected_bytes):
        work = ROOT / '_live'
        work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='request-', dir=work) as directory:
            body_path = Path(directory) / 'body'
            command = [
                'curl', '--silent', '--show-error', '--location', '--max-redirs', '3',
                '--proto', '=http,https', '--proto-redir', '=http,https', '--compressed',
                '--connect-timeout', str(min(self.connect_timeout, timeout)),
                '--max-time', str(timeout),
                '--max-filesize', str(max(65536, expected_bytes * 2)),
                '--output', str(body_path),
                '--write-out', '%{http_code}\n%{content_type}\n%{url_effective}', url,
            ]
            try:
                process = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
            except subprocess.TimeoutExpired as error:
                raise RetryableError('request deadline exceeded') from error
            if process.returncode:
                message = process.stderr.strip() or 'curl exited ' + str(process.returncode)
                if process.returncode == 63:
                    raise DeliveryError('Response exceeds its build size budget: ' + message)
                raise RetryableError(message)
            fields = process.stdout.split('\n', 2)
            if len(fields) != 3 or not fields[0].isdigit():
                raise DeliveryError('Invalid curl response metadata')
            return Response(int(fields[0]), fields[1], body_path.read_bytes(), fields[2])


def validate_catalog(path, document):
    spec = importlib.util.spec_from_file_location('live_catalog_validation', ROOT / 'scripts/validate-discovery.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.validate_catalog_document(path, document)


def validate_response(item, response, requested_url, catalog_check=validate_catalog):
    path = item['path']
    if response.status in (404, 408, 425, 429) or response.status >= 500:
        raise RetryableError('HTTP ' + str(response.status))
    if response.status != 200:
        raise DeliveryError(path + ': expected HTTP 200, received ' + str(response.status))
    if response.effective_url != requested_url:
        raise DeliveryError(path + ': unexpected redirect to ' + response.effective_url)
    content_type = response.content_type.split(';', 1)[0].strip().lower()
    if content_type not in item['transport_mime_types']:
        raise DeliveryError(path + ': unexpected Content-Type ' + repr(content_type))
    body = response.body
    prefix = body.lstrip(b'\xef\xbb\xbf \t\r\n').lower()
    if item['format'] != 'html' and (prefix.startswith(b'<!doctype html') or prefix.startswith(b'<html')):
        raise DeliveryError(path + ': received an HTML fallback')
    document = None
    try:
        if item['format'] == 'json':
            document = json.loads(body, object_pairs_hook=unique_json, parse_constant=invalid_constant)
        elif item['format'] == 'xml':
            ET.fromstring(body)
        elif item['format'] in ('html', 'text'):
            body.decode('utf-8')
    except (ValueError, UnicodeError, ET.ParseError) as error:
        raise DeliveryError(path + ': invalid ' + item['format'] + ' response: ' + str(error)) from error
    digest = hashlib.sha256(body).hexdigest()
    if digest != item['sha256'] or len(body) != item['bytes']:
        raise RetryableError('stale body: expected ' + item['sha256'] + ', got ' + digest)
    # An older but parseable catalog can be normal propagation. Apply the new
    # schema/site contract only once the expected build body has arrived.
    if path in CATALOG_PATHS.values():
        try:
            catalog_check(path, document)
        except (ValueError, ImportError) as error:
            raise DeliveryError(path + ': schema or resource contract failed: ' + str(error)) from error
    return {'path': path, 'url': requested_url, 'status': response.status,
            'content_type': content_type, 'sha256': digest, 'bytes': len(body)}


def check_inventory(inventory, base_url, *, deadline=300, request_timeout=15,
                    retry_interval=5, fetch=None, clock=time.monotonic, sleep=time.sleep,
                    catalog_check=validate_catalog, progress=print):
    parsed = urlsplit(base_url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise DeliveryError('Base URL must be an HTTP(S) origin or path without credentials, query or fragment')
    if min(deadline, request_timeout, retry_interval) <= 0:
        raise DeliveryError('Deadline, request timeout and retry interval must be positive')
    if fetch is None:
        fetch = CurlFetcher(connect_timeout=min(5, request_timeout))
    base_url = base_url.rstrip('/')
    required = [item for item in inventory['files'] if item['public_url_path'] is not None]
    pending = list(required)
    verified, verified_paths, attempts, last_errors = [], set(), {}, {}
    started = clock()
    expires = started + deadline

    def make_report(error=None):
        report = {'ok': error is None, 'base_url': base_url,
                  'elapsed_seconds': round(clock() - started, 3),
                  'checked_resources': len(verified), 'resources': verified}
        if error is not None:
            report['error'] = str(error)
            report['pending_resources'] = [
                {'path': item['path'], 'url': base_url + item['public_url_path'],
                 'attempts': attempts.get(item['path'], 0),
                 'last_error': last_errors.get(item['path'])}
                for item in required if item['path'] not in verified_paths
            ]
        return report

    try:
        while pending:
            retry = []
            for item in pending:
                remaining = expires - clock()
                if remaining <= 0:
                    names = ', '.join(row['path'] for row in required if row['path'] not in verified_paths)
                    details = '; '.join(path + ': ' + error for path, error in last_errors.items())
                    raise DeliveryError('Overall deadline exceeded; pending: ' + names + ('. ' + details if details else ''))
                path = item['path']
                requested_url = base_url + item['public_url_path']
                attempts[path] = attempts.get(path, 0) + 1
                try:
                    response = fetch(requested_url, min(request_timeout, remaining), item['bytes'])
                    if clock() >= expires:
                        raise DeliveryError('Overall deadline exceeded while fetching ' + path)
                    result = validate_response(item, response, requested_url, catalog_check)
                except RetryableError as error:
                    last_errors[path] = str(error)
                    retry.append(item)
                    progress(path + ': waiting for current build (' + str(error) + ')')
                except (OSError, ValueError, ImportError) as error:
                    last_errors[path] = str(error)
                    raise
                else:
                    result['attempts'] = attempts[path]
                    verified.append(result)
                    verified_paths.add(path)
                    last_errors.pop(path, None)
            pending = retry
            if pending:
                remaining = expires - clock()
                if remaining > 0:
                    sleep(min(retry_interval, remaining))
    except (OSError, ValueError, ImportError) as error:
        if isinstance(error, DeliveryError):
            error.report = make_report(error)
            raise
        raise DeliveryError(str(error), report=make_report(error)) from error
    return make_report()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, default=ROOT / '_dist/inventory.json')
    parser.add_argument('--artifact-dir', type=Path, help='Also verify the downloaded build snapshot')
    parser.add_argument('--base-url', help='Override the origin, e.g. http://127.0.0.1:8000')
    parser.add_argument('--deadline', type=float, default=300)
    parser.add_argument('--request-timeout', type=float, default=15)
    parser.add_argument('--connect-timeout', type=float, default=5)
    parser.add_argument('--retry-interval', type=float, default=5)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    report = None
    try:
        if args.connect_timeout <= 0:
            raise DeliveryError('Connect timeout must be positive')
        inventory = load_inventory(args.inventory)
        if args.artifact_dir:
            verify_artifact(inventory, args.artifact_dir)
        report = check_inventory(inventory, args.base_url or inventory['source_base_url'],
                                 deadline=args.deadline, request_timeout=args.request_timeout,
                                 retry_interval=args.retry_interval, fetch=CurlFetcher(args.connect_timeout))
        print('Live delivery passed: ' + str(report['checked_resources']) + ' resources match the build, including both catalogs.')
    except (OSError, ValueError, ImportError) as error:
        report = getattr(error, 'report', None) or {'ok': False, 'error': str(error)}
        raise
    finally:
        if args.report and report is not None:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, ImportError) as error:
        print('Live delivery failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
