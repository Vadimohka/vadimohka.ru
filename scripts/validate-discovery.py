#!/usr/bin/env python3
"""Offline discovery contracts, source fidelity and pinned schema validation.

ARD uses the official pinned JSON Schema at #/$defs/ArdManifest. AI Catalog
uses a clearly labelled local transcription of its normative CDDL, plus this
site's narrower read-only document contract. No schema/context is fetched here.
"""
import argparse
import copy
import hashlib
import json
import re
import sys
from datetime import datetime
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError as error:
    raise SystemExit(
        'Discovery validation needs its pinned dependencies. Run '
        'python3 -m pip install -r scripts/requirements-validation.txt '
        '(Python 3.11 or newer).'
    ) from error

from site_model import (
    ARD_CONTEXT, BASE, CATALOG_MEDIA_TYPES, CATALOG_PATHS, CONTACT, LANGUAGE,
    NAME, PAGES, PERSON_ID, RESOURCES, ROOT, canonical, index_path, lite_path,
)

SCHEMAS = Path(__file__).resolve().parent / 'schemas'
READ_TYPES = {'application/ld+json', 'text/plain', 'text/markdown'}
URN = re.compile(r'^urn:air:vadimohka\.ru(:[a-zA-Z0-9._-]+)+$')
COMMON_FIELDS = {'identifier', 'displayName', 'type', 'url', 'description', 'tags'}
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
        'meta', 'param', 'source', 'track', 'wbr'}
IGNORED = {'nav', 'script', 'style', 'noscript', 'svg'}
FORMATS = FormatChecker(formats=[])


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f'Duplicate JSON key: {key}')
        result[key] = value
    return result


def invalid_constant(value):
    raise ValueError(f'Non-JSON number: {value}')


def parse_json(text):
    return json.loads(text, object_pairs_hook=unique_json, parse_constant=invalid_constant)


def read_json(path):
    return parse_json(path.read_text(encoding='utf-8'))


@FORMATS.checks('uri', raises=ValueError)
def absolute_uri(value):
    """Check an absolute URI; stricter exact HTTPS URLs are checked below."""
    if not isinstance(value, str):
        return True
    if re.search(r'[\s<>"{}|\\^`]', value):
        return False
    parts = urlsplit(value)
    return bool(re.fullmatch(r'[A-Za-z][A-Za-z0-9+.-]*', parts.scheme))


@FORMATS.checks('date-time', raises=ValueError)
def timestamp(value):
    """Validate the JSON date-time shape used by this site without format extras."""
    if not isinstance(value, str):
        return True
    if not re.fullmatch(r'\d{4}-\d\d-\d\d[Tt]\d\d:\d\d:\d\d(?:\.\d+)?(?:[Zz]|[+-]\d\d:\d\d)', value):
        return False
    return datetime.fromisoformat(value.replace('t', 'T').replace('z', '+00:00').replace('Z', '+00:00')).tzinfo is not None


def validate_schema_pins(directory):
    provenance = read_json(directory / 'provenance.json')
    for filename, digest in provenance['sha256'].items():
        target = directory / filename
        require(target.is_file(), f'Missing pinned specification file: {filename}')
        require(hashlib.sha256(target.read_bytes()).hexdigest() == digest,
                f'Pinned specification changed: {filename}; review provenance before updating')
    schema = (directory / 'ard-entry.schema.json').read_bytes()
    blob = hashlib.sha1(b'blob ' + str(len(schema)).encode() + b'\0' + schema).hexdigest()
    require(blob == provenance['ard']['blob'], 'ARD schema differs from the pinned upstream Git blob')


@lru_cache(maxsize=1)
def validators():
    validate_schema_pins(SCHEMAS)
    ard = copy.deepcopy(read_json(SCHEMAS / 'ard-entry.schema.json'))
    # The upstream file defaults to a single entry. Override that root reference
    # to validate the complete publication, including its mandatory entries array.
    ard['$ref'] = '#/$defs/ArdManifest'
    ai = read_json(SCHEMAS / 'ai-catalog.local.schema.json')
    for schema in (ard, ai):
        Draft202012Validator.check_schema(schema)
    return {
        CATALOG_PATHS['ard']: Draft202012Validator(ard, format_checker=FORMATS),
        CATALOG_PATHS['ai-catalog']: Draft202012Validator(ai, format_checker=FORMATS),
    }


def validate_catalog_document(path, document):
    """Validate a downloaded or local catalog; raise ValueError on a violation.

    This API does not fetch targets or compare HTTP headers. Delivery checks must
    separately verify the published bytes and target responses. It deliberately
    accepts only the reviewed document resources in the shared source registry.
    """
    path = str(path).lstrip('/')
    require(path in CATALOG_PATHS.values(), f'Unknown catalog path: {path}')
    errors = sorted(validators()[path].iter_errors(document),
                    key=lambda error: '/'.join(map(str, error.absolute_path)))
    if errors:
        error = errors[0]
        location = '/'.join(map(str, error.absolute_path)) or '(root)'
        raise ValueError(f'{path}: schema violation at {location}: {error.message}')

    is_ard = path == CATALOG_PATHS['ard']
    if is_ard:
        require(set(document) == {'entries'}, f'{path}: unexpected transport fields')
    else:
        require(set(document) == {'specVersion', 'host', 'entries'}, f'{path}: unexpected top-level fields')
        require(document['specVersion'] == '1.0', f'{path}: unsupported specVersion')
        host = document['host']
        require(host == {'displayName': NAME, 'documentationUrl': BASE + 'llms.txt'},
                f'{path}: host must identify the actual public documentation')
    expected = {resource.identifier: resource for resource in RESOURCES}
    require(bool(expected) and len(expected) == len(RESOURCES),
            'Expected a nonempty registry of distinct reviewed resource contracts')
    entries = document['entries']
    identifiers = [entry['identifier'] for entry in entries]
    require(len(identifiers) == len(set(identifiers)), f'{path}: duplicate resource identifier')
    require(set(identifiers) == set(expected), f'{path}: resource inventory differs from the reviewed registry')
    for entry in entries:
        identifier = entry['identifier']
        resource = expected[identifier]
        fields = COMMON_FIELDS | ({'@context', 'representativeQueries'} if is_ard else set())
        require(set(entry) == fields, f'{identifier}: unexpected runtime, trust or extension fields')
        require(URN.fullmatch(identifier), f'{identifier}: invalid domain-anchored identifier')
        require(resource.interaction == 'read' and resource.media_type in READ_TYPES,
                f'{identifier}: only existing read-only document resources are approved')
        require(entry['type'] == resource.media_type, f'{identifier}: wrong document media type')
        require(entry['url'] == BASE + resource.path, f'{identifier}: wrong resource URL')
        url = urlsplit(entry['url'])
        require(url.scheme == 'https' and url.netloc == 'vadimohka.ru'
                and not url.query and not url.fragment,
                f'{identifier}: expected an exact public HTTPS document URL')
        for field in ('displayName', 'description'):
            require(isinstance(entry[field], str) and entry[field].strip(),
                    f'{identifier}: empty {field}')
        require(LANGUAGE in entry['tags'] and len(set(entry['tags'])) == len(entry['tags'])
                and all(tag.strip() for tag in entry['tags']), f'{identifier}: invalid language/tags')
        if is_ard:
            require(entry['@context'] == ARD_CONTEXT, f'{identifier}: wrong ARD context')
            queries = entry['representativeQueries']
            require(2 <= len(queries) <= 5 and all(query.strip() for query in queries)
                    and len(set(queries)) == len(queries),
                    f'{identifier}: expected 2–5 distinct representative queries')


class HTMLFacts(HTMLParser):
    """An independent source reader, not the exporter used to generate Markdown."""
    def __init__(self, source, url):
        super().__init__(convert_charrefs=True)
        self.url, self.stack = url, []
        self.head_links, self.links, self.ids, self.blocks = [], set(), set(), []
        self.title_parts, self.main_parts, self.descriptions = [], [], []
        self.anchors, self.paragraphs, self.jsonld = [], [], []
        self.json_buffer = None
        self.feed(source)
        self.close()

    def visible_main(self):
        return (any(tag == 'main' for tag, _ in self.stack)
                and not any(tag in IGNORED or attrs.get('aria-hidden') == 'true'
                            for tag, attrs in self.stack))

    def handle_starttag(self, tag, pairs):
        attrs = dict(pairs)
        in_head = any(name == 'head' for name, _ in self.stack)
        if attrs.get('id'):
            require(attrs['id'] not in self.ids, f'{self.url}: duplicate HTML id {attrs["id"]}')
            self.ids.add(attrs['id'])
        if tag == 'link' and in_head:
            self.head_links.append(attrs)
        if tag == 'meta' and in_head and attrs.get('name') == 'description':
            self.descriptions.append(attrs.get('content', ''))
        if tag not in VOID:
            self.stack.append((tag, attrs))
        if tag == 'script' and attrs.get('type') == 'application/ld+json':
            self.json_buffer = []
        if self.visible_main():
            if tag == 'a' and attrs.get('href'):
                self.anchors.append([len(self.stack), attrs['href'], []])
            if tag in ('p', 'li'):
                self.paragraphs.append([len(self.stack), []])

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == 'script' and self.json_buffer is not None:
            self.jsonld.append(parse_json(''.join(self.json_buffer)))
            self.json_buffer = None
        index = next((i for i in range(len(self.stack)-1, -1, -1)
                      if self.stack[i][0] == tag), None)
        if index is None:
            return
        for depth, href, parts in self.anchors:
            if depth > index and ''.join(parts).strip():
                self.links.add(urljoin(self.url, href))
        self.anchors = [frame for frame in self.anchors if frame[0] <= index]
        for depth, parts in self.paragraphs:
            if depth > index:
                text = ' '.join(''.join(parts).split())
                if text:
                    self.blocks.append(text)
        self.paragraphs = [frame for frame in self.paragraphs if frame[0] <= index]
        del self.stack[index:]

    def handle_data(self, data):
        if self.json_buffer is not None:
            self.json_buffer.append(data)
        if any(tag == 'title' for tag, _ in self.stack):
            self.title_parts.append(data)
        if self.visible_main():
            self.main_parts.append(data + ' ')
            for frame in self.anchors:
                frame[2].append(data + ' ')
            for frame in self.paragraphs:
                frame[1].append(data + ' ')

    @property
    def title(self):
        return ''.join(self.title_parts).strip()

    @property
    def text(self):
        return ' '.join(''.join(self.main_parts).split())


def tokens(text):
    return ' '.join(re.findall(r'\w+', text.casefold()))


def markdown_text(text):
    # Source material uses ordinary inline Markdown links; remove destinations
    # while retaining labels so a URL inserted inside a paragraph is not prose.
    text = re.sub(r'!?\[([^\]]*)\]\([^\n]*?\)', r'\1', text)
    return tokens(text)


def markdown_links(text):
    return set(re.findall(r'(?<!!)\[[^\]]*\]\(([^\s)]+)\)', text))


def local_file(root, url):
    parts = urlsplit(url)
    require(parts.scheme == 'https' and parts.netloc == 'vadimohka.ru', f'Not a local site resource: {url}')
    path = unquote(parts.path).lstrip('/')
    if not path or path.endswith('/'):
        path += 'index.html'
    target = (root / path).resolve()
    require(target.is_relative_to(root.resolve()) and target.is_file(), f'Missing or unsafe resource: {url}')
    return target


def check_head(facts, name, source_path, is_lite=False):
    for relation, path in CATALOG_PATHS.items():
        links = [attrs for attrs in facts.head_links if relation in attrs.get('rel', '').split()]
        require(len(links) == 1, f'{name}: expected one {relation} relation in head')
        require(urljoin(facts.url, links[0].get('href', '')) == BASE + path
                and links[0].get('type') == CATALOG_MEDIA_TYPES[relation],
                f'{name}: wrong {relation} target or media type')
    representations = [
        ('canonical', None, canonical(source_path)),
        ('alternate', 'text/markdown', BASE + source_path + '.md'),
        ('describedby', 'text/plain', BASE + index_path(source_path)),
    ]
    if not is_lite:
        representations.append(('alternate', 'text/html',
                                BASE + lite_path(source_path).removesuffix('index.html')))
    for relation, media_type, target in representations:
        # Language alternates may coexist with links to the same-language formats.
        links = [attrs for attrs in facts.head_links
                 if relation in attrs.get('rel', '').split()
                 and (media_type is None or attrs.get('type') == media_type)
                 and (relation != 'alternate' or not attrs.get('hreflang'))]
        label = relation + (' ' + media_type if media_type else '')
        require(len(links) == 1, f'{name}: expected one {label} relation in head')
        require(links[0].get('href') and urljoin(facts.url, links[0]['href']) == target,
                f'{name}: wrong {label} target; expected {target}')


def check_index(root, source_path):
    name = index_path(source_path)
    text = (root / name).read_text(encoding='utf-8')
    links = {urljoin(BASE + name, url) for url in markdown_links(text)}
    expected = {BASE + path for path in CATALOG_PATHS.values()}
    if source_path == 'index.html':
        expected.update(BASE + path + '.md' for path in PAGES)
        expected.update(BASE + lite_path(path).removesuffix('index.html') for path in PAGES)
        expected.update(BASE + path for path in
                        ('llms-full.txt', 'llm-profile.json', 'person.jsonld', 'sitemap.xml'))
    else:
        expected.update((BASE + source_path + '.md',
                         BASE + lite_path(source_path).removesuffix('index.html'),
                         canonical(source_path), BASE + 'llms.txt', BASE + 'person.jsonld'))
    missing = sorted(expected - links)
    require(not missing, f'{name}: missing navigation target(s): {", ".join(missing)}')
    # Additional useful links are allowed, but every local destination must exist.
    for url in sorted(links):
        if urlsplit(url).netloc == urlsplit(BASE).netloc:
            target = local_file(root, url)
            require(target.stat().st_size > 0, f'{name}: empty navigation target {url}')


def validate_site(root=ROOT):
    root = Path(root).resolve()
    validate_schema_pins(root / 'scripts/schemas')
    manifests = {relation: read_json(root / path) for relation, path in CATALOG_PATHS.items()}
    for relation, manifest in manifests.items():
        validate_catalog_document(CATALOG_PATHS[relation], manifest)
    ai_entries = {entry['identifier']: entry for entry in manifests['ai-catalog']['entries']}
    ard_entries = {entry['identifier']: entry for entry in manifests['ard']['entries']}
    for identifier, entry in ai_entries.items():
        require(entry == {key: value for key, value in ard_entries[identifier].items() if key in COMMON_FIELDS},
                f'{identifier}: the two catalog projections disagree')
    for resource in RESOURCES:
        target = local_file(root, BASE + resource.path)
        require(target.stat().st_size > 0, f'{resource.path}: empty resource')
        text = target.read_text(encoding='utf-8')
        require(not text.lstrip().lower().startswith(('<!doctype', '<html')),
                f'{resource.path}: expected a document payload, received HTML')
        if resource.media_type == 'application/ld+json':
            read_json(target)

    full = (root / 'llms-full.txt').read_text(encoding='utf-8')
    full_links, full_words = markdown_links(full), markdown_text(full)
    source_pages = {}
    for path in PAGES:
        facts = HTMLFacts((root / path).read_text(encoding='utf-8'), canonical(path))
        source_pages[path] = facts
        check_head(facts, path, path)
        lite_name = lite_path(path)
        lite = HTMLFacts((root / lite_name).read_text(encoding='utf-8'), BASE + lite_name.removesuffix('index.html'))
        check_head(lite, lite_name, path, is_lite=True)
        md_name = path + '.md'
        markdown = (root / md_name).read_text(encoding='utf-8')
        md_links, md_words = markdown_links(markdown), markdown_text(markdown)
        for url in facts.links:
            require(url in md_links, f'{md_name}: lost source link {url}')
            require(url in full_links, f'llms-full.txt: lost source link {url}')
            require(url in lite.links, f'{lite_name}: lost source link {url}')
        for paragraph in facts.blocks:
            words = tokens(paragraph)
            if len(words.split()) < 4:
                continue
            for name, output in ((md_name, md_words), ('llms-full.txt', full_words), (lite_name, tokens(lite.text))):
                require(words in output, f'{name}: source paragraph missing or changed: {paragraph[:100]}')
        check_index(root, path)

    for resource in RESOURCES:
        entry = ai_entries[resource.identifier]
        if resource.source_page:
            source = source_pages[resource.source_page]
            require(len(source.descriptions) == 1, f'{resource.source_page}: ambiguous source description')
            require(entry['displayName'] == source.title and entry['description'] == source.descriptions[0],
                    f'{resource.path}: catalog description is stale relative to editorial HTML')

    approved = read_json(root / 'scripts/data/profile.json')
    published = read_json(root / 'person.jsonld')
    require(published == approved, 'person.jsonld differs from the approved profile source')
    person = next(node for node in approved['@graph'] if node.get('@type') == 'Person')
    require(person['@id'] == PERSON_ID and person['email'] == CONTACT,
            'Profile identity/contact do not match the shared source')
    require(person['jobTitle'] == 'Co-Founder Century | CTO StackLevel GROUP', 'Approved role changed')
    require(CONTACT in source_pages['index.html'].links, 'Published contact does not match homepage contact')
    for path, facts in source_pages.items():
        people = [node for document in facts.jsonld for node in document.get('@graph', [])
                  if node.get('@type') == 'Person']
        require(people == [person], f'{path}: inline identity differs from the source profile')
    projects = tokens(source_pages['projects/index.html'].text)
    for qualifier in ('Belka остаётся научным хобби', 'разработкой и тестированием',
                      'ранний MVP для локальной установки'):
        require(tokens(qualifier) in projects, f'Project maturity qualifier changed: {qualifier}')
    # The retained qualifiers and every original paragraph must also survive all
    # generated formats above; no inference from a project name creates an API.


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT, help='Site tree to validate (default: this repository)')
    args = parser.parse_args(argv)
    validate_site(args.root)
    print('Discovery validation passed: pinned ARD manifest schema, local AI CDDL structural contract, '
          f'{len(RESOURCES)} document resources, {len(PAGES) * 2} discovery heads, '
          'format/index navigation, source links, profile and maturity fidelity.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, StopIteration) as error:
        print(f'Discovery validation failed: {error}', file=sys.stderr)
        sys.exit(1)
