#!/usr/bin/env python3
"""Read the published discovery surface through HTTP, without importing the generator.

This reference client checks discovery and the availability of evidence. It does
not claim to evaluate an LLM answer or prove indexing by an external registry.
Use --serve-dir dist for a self-contained local check, or --base-url for a site.
"""
import argparse
import functools
import hashlib
import json
import re
import sys
import threading
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from math import isfinite
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

CANONICAL_BASE = 'https://vadimohka.ru/'
PERSON_ID = CANONICAL_BASE + '#person'
MAX_RESPONSE_BYTES = 2_000_000
CLIENT_ID = 'vadimohka-reference-reader-v1'
CLIENT_ERRORS = (OSError, ValueError, KeyError, TypeError, HTTPError, URLError)
TRANSPORT_TYPES = {
    'text/html': {'text/html'},
    'application/json': {'application/json'},
    'application/ai-catalog+json': {'application/ai-catalog+json', 'application/json'},
    'application/ld+json': {'application/ld+json', 'application/json'},
    'text/plain': {'text/plain'},
    'text/markdown': {'text/markdown', 'text/x-markdown', 'text/plain'},
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate JSON member: ' + key)
        result[key] = value
    return result


def invalid_constant(value):
    raise ValueError('Non-JSON number: ' + value)


def parse_json(text):
    return json.loads(text, object_pairs_hook=unique_json, parse_constant=invalid_constant)


def markdown_links(text):
    # The published Markdown uses ordinary inline links. A source URL must be
    # a complete link destination, not a substring of prose or another host.
    return set(re.findall(r'(?<!!)\[[^\]]*\]\(([^\s)]+)\)', text))


def has_link(text, expected):
    return any(target == expected for target in markdown_links(text))


def new_report(base_url):
    return {
        'client': CLIENT_ID,
        'baseUrl': base_url,
        'status': 'running',
        'catalogs': [],
        'requests': [],
        'evidenceChecks': [],
        'scope': 'HTTP discovery and evidence availability; not an LLM evaluation or external indexing claim.',
    }


class HeadLinks(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.in_head = False
        self.links = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag == 'head':
            self.in_head = True
        if tag == 'link' and self.in_head:
            self.links.append(dict(attrs))

    def handle_endtag(self, tag):
        if tag == 'head':
            self.in_head = False


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        # A catalog reference must resolve at its declared address. In particular,
        # never follow an unexpected external redirect from a preview server.
        return None


class Reader:
    def __init__(self, base_url, timeout):
        base = urlsplit(base_url)
        require(base.scheme in ('http', 'https') and base.netloc,
                'Expected an absolute HTTP(S) base URL')
        require(not base.query and not base.fragment and not base.username,
                'Base URL must not have credentials, a query or a fragment')
        self.base_url = base_url.rstrip('/') + '/'
        self.timeout = timeout
        self.opener = build_opener(NoRedirect())
        self.cache = {}
        self.report = new_report(self.base_url)

    def fetch(self, reference, media_type):
        canonical = urljoin(CANONICAL_BASE, reference)
        parts = urlsplit(canonical)
        require(parts.scheme == 'https' and parts.netloc == 'vadimohka.ru',
                'Unexpected resource origin: ' + canonical)
        require(not parts.query and not parts.fragment,
                'Expected a document URL without query or fragment: ' + canonical)
        require(media_type in TRANSPORT_TYPES, 'Unsupported document type: ' + media_type)
        cache_key = (canonical, media_type)
        if cache_key in self.cache:
            return self.cache[cache_key]
        target = self.base_url + parts.path.lstrip('/')
        attempt = {'url': target, 'canonicalUrl': canonical, 'status': 'pending'}
        self.report['requests'].append(attempt)
        try:
            request = Request(target, headers={
                'Accept': ', '.join(sorted(TRANSPORT_TYPES[media_type])),
                'User-Agent': 'vadimohka-discovery-check/1.0',
            })
            with self.opener.open(request, timeout=self.timeout) as response:
                attempt['httpStatus'] = response.status
                require(response.status == 200, 'Expected HTTP 200: ' + target)
                actual_type = response.headers.get_content_type()
                attempt['contentType'] = actual_type
                require('Content-Type' in response.headers and actual_type in TRANSPORT_TYPES[media_type],
                        'Unexpected Content-Type for ' + target + ': ' + actual_type)
                body = response.read(MAX_RESPONSE_BYTES + 1)
                require(len(body) <= MAX_RESPONSE_BYTES, 'Response exceeds client size limit: ' + target)
            attempt.update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
            text = body.decode('utf-8')
            if media_type != 'text/html':
                require(not re.match(r'\s*(?:<!doctype\s+html|<html\b)', text, re.I),
                        'HTML fallback at document URL: ' + target)
        except CLIENT_ERRORS as error:
            attempt.update(status='failed', error=str(error))
            if isinstance(error, HTTPError):
                attempt['httpStatus'] = error.code
            raise
        attempt['status'] = 'pass'
        self.cache[cache_key] = text
        return text

    def check(self):
        home = HeadLinks(self.fetch(CANONICAL_BASE, 'text/html'))
        catalogs = {}
        for relation in ('ai-catalog', 'ard'):
            links = [link for link in home.links if relation in link.get('rel', '').split()]
            require(len(links) == 1, 'Expected exactly one head relation: ' + relation)
            link = links[0]
            allowed_types = ({'application/json', 'application/ai-catalog+json'}
                             if relation == 'ai-catalog' else {'application/json'})
            require(link.get('type') in allowed_types and link.get('href'),
                    'Invalid discovery relation: ' + relation)
            media_type = 'application/ai-catalog+json' if relation == 'ai-catalog' else 'application/json'
            document = parse_json(self.fetch(link['href'], media_type))
            require(isinstance(document, dict), 'Expected a catalog object: ' + relation)
            if relation == 'ai-catalog':
                require(document.get('specVersion') == '1.0', 'Unsupported AI Catalog version')
            entries = document.get('entries')
            require(isinstance(entries, list) and entries, 'Empty or invalid catalog: ' + relation)
            indexed = {}
            for entry in entries:
                require(isinstance(entry, dict), 'Expected a catalog entry object')
                require(all(isinstance(entry.get(key), str) and entry[key]
                            for key in ('identifier', 'type', 'url', 'displayName')),
                        'Missing resource metadata in ' + relation)
                require('data' not in entry, 'This site publishes URL resources, not inline data')
                require(entry['identifier'] not in indexed, 'Duplicate resource identifier')
                if relation == 'ard':
                    queries = entry.get('representativeQueries', [])
                    require(isinstance(queries, list) and 2 <= len(queries) <= 5
                            and all(isinstance(query, str) and query.strip() for query in queries),
                            'Expected 2–5 representative queries for ' + entry['identifier'])
                indexed[entry['identifier']] = entry
            catalogs[relation] = indexed
            self.report['catalogs'].append({
                'relation': relation,
                'url': urljoin(CANONICAL_BASE, link['href']),
                'identifiers': sorted(indexed),
            })
        primary, alternate = catalogs['ai-catalog'], catalogs['ard']
        require(set(primary) == set(alternate), 'Catalog resource sets differ')
        for identifier, entry in primary.items():
            for field in ('identifier', 'type', 'url', 'displayName', 'description'):
                require(entry.get(field) == alternate[identifier].get(field),
                        'Catalogs disagree on ' + field + ': ' + identifier)
        resources = {}
        for identifier, entry in primary.items():
            resources[identifier] = (entry, self.fetch(entry['url'], entry['type']))
        self.check_evidence(resources)
        self.report['status'] = 'pass'
        return self.report

    def check_evidence(self, resources):
        def resource(suffix):
            identifier = 'urn:air:vadimohka.ru:' + suffix
            require(identifier in resources, 'Missing acceptance resource: ' + identifier)
            return resources[identifier]

        def record(name, question, entries):
            self.report['evidenceChecks'].append({
                'name': name, 'question': question, 'status': 'pass',
                'sources': [entry['url'] for entry in entries],
            })

        def section(text, heading):
            match = re.search(r'^## ' + re.escape(heading) + r'\s*$', text, re.M)
            require(match is not None, 'Missing project section: ' + heading)
            rest = text[match.end():]
            return re.split(r'^## ', rest, maxsplit=1, flags=re.M)[0]

        profile_entry, profile_text = resource('profile:vadim-vladymtsev')
        profile = parse_json(profile_text)
        require(isinstance(profile, dict) and isinstance(profile.get('@graph'), list)
                and all(isinstance(node, dict) for node in profile['@graph']),
                'Expected a profile object with a JSON-LD graph')
        people = [node for node in profile.get('@graph', []) if node.get('@id') == PERSON_ID]
        require(len(people) == 1, 'Expected the canonical person identity')
        person = people[0]
        require(person.get('@type') == 'Person' and person.get('name') == 'Вадим Владымцев',
                'Expected the approved person name and type')
        require(person.get('jobTitle') == 'Co-Founder Century | CTO StackLevel GROUP',
                'Approved current role is unavailable')
        record('identity', 'Кто автор и чем занимается сейчас?', [profile_entry])

        background_entry, background = resource('docs:background')
        projects_entry, projects = resource('docs:projects')
        require(person['jobTitle'] in background and person['jobTitle'] in projects,
                'Current role is inconsistent across evidence documents')
        require('### Архитектура и быстродействие' in background
                and '### Процессы и автоматизация' in background
                and has_link(projects, 'https://century-ai.by'),
                'Missing experience or product evidence')
        record('experience', 'Какой опыт относится к архитектуре и автоматизации?',
               [background_entry, projects_entry])

        belka = section(projects, 'Belka')
        require(all(re.search(pattern, belka, re.I) for pattern in
                    (r'научн\w* хобби', r'разработк', r'тестирован'))
                and has_link(belka, 'https://github.com/Vadimohka/belka'),
                'Belka evidence loses its research status or source')
        record('belka', 'Что известно о готовности Belka?', [projects_entry])

        multiverse = section(projects, 'Multiverse')
        require(all(re.search(pattern, multiverse, re.I) for pattern in
                    (r'ранний MVP', r'локальн\w* установк'))
                and has_link(multiverse, 'https://github.com/Vadimohka/Multiverse'),
                'Multiverse evidence loses its early/local status or source')
        record('multiverse', 'Что доступно для использования Multiverse?', [projects_entry])

        approach_entry, approach = resource('docs:ai-automation-approach')
        steps = re.findall(r'^### (0[1-5])\. [^\n]+\n(.*?)(?=^#{1,3} |\Z)',
                           approach, re.M | re.S)
        require([number for number, _ in steps] == ['01', '02', '03', '04', '05']
                and all(body.strip() for _, body in steps),
                'Author workflow needs distinct steps 01–05 with explanatory text')
        record('approach', 'Как автор предлагает подходить к автоматизации?', [approach_entry])

        context_entry, context = resource('docs:context')
        evidence_urls = {
            'https://www.researchgate.net/publication/376775533_Heart_Rate_Measurement_Algorithm_in_the_Monitoring_System_of_Human_Body_Condition',
            'https://t.me/bsuir_official/7104', 'https://stepik.org/course/86957/promo',
        }
        require('соавтор' in context and evidence_urls <= markdown_links(context),
            'Research or teaching evidence links are unavailable')
        record('sources', 'Чем подтверждаются исследования и преподавание?', [context_entry])

        contact = person.get('email', '')
        require(isinstance(contact, str) and re.fullmatch(r'mailto:[^\s@]+@[^\s@]+', contact)
                and has_link(approach, contact),
                'Profile and approach contact differ')
        index_entry, index = resource('docs:index')
        expected_links = {entry['url'] for entry in
                          (background_entry, projects_entry, approach_entry, context_entry)}
        require(expected_links <= markdown_links(index),
                'Reading index does not link to the evidence documents')
        record('contact-and-navigation', 'Как найти подходящий материал и обратиться с задачей?',
               [profile_entry, index_entry, approach_entry])


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--base-url', default=CANONICAL_BASE)
    source.add_argument('--serve-dir', type=Path)
    parser.add_argument('--request-timeout', type=float, default=5)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(argv)
    server, thread = None, None
    base_url = args.base_url
    report = new_report(base_url)
    exit_code = 1
    try:
        require(isfinite(args.request_timeout) and args.request_timeout > 0,
                'Request timeout must be finite and positive')
        if args.serve_dir is not None:
            require(args.serve_dir.is_dir(), 'Missing site directory: ' + str(args.serve_dir))
            handler = functools.partial(QuietHandler, directory=str(args.serve_dir.resolve()))
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = 'http://127.0.0.1:' + str(server.server_port) + '/'
        reader = Reader(base_url, args.request_timeout)
        report = reader.report
        reader.check()
        print('Reference discovery reader passed: ' + str(len(report['catalogs']))
              + ' catalogs, ' + str(len(report['requests'])) + ' HTTP documents, '
              + str(len(report['evidenceChecks'])) + ' evidence scenarios.')
        exit_code = 0
    except CLIENT_ERRORS as error:
        report.update(status='failed', error=str(error))
        print('Reference discovery reader failed: ' + str(error), file=sys.stderr)
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                                   encoding='utf-8')
    return exit_code


if __name__ == '__main__':
    try:
        sys.exit(main())
    except CLIENT_ERRORS as error:
        print('Reference discovery reader failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
