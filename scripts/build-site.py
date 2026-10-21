#!/usr/bin/env python3
"""Build the static site from an explicit inventory, without publishing tooling.

The inventory is written outside dist and is also the input to the live checker.
Page-derived files come from site_model; the remaining files are site runtime
assets, verification files, or retained English handoffs.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

from site_model import BASE, CATALOG_PATHS, PAGES, RESOURCES, ROOT, canonical, index_path, lite_path


FIXED_FILES = {
    'robots.txt': 'crawler-rules',
    'sitemap.xml': 'sitemap',
    'llms-full.txt': 'reading-document',
    'llm-profile.json': 'profile',
    'person.jsonld': 'profile',
    'favicon.ico': 'runtime-asset',
    'favicon.svg': 'runtime-asset',
    'apple-touch-icon.png': 'runtime-asset',
    'assets/studio.css': 'runtime-asset',
    'assets/profile.css': 'runtime-asset',
    'assets/approach.css': 'runtime-asset',
    'assets/portrait.css': 'runtime-asset',
    'assets/studio.js': 'runtime-asset',
    'assets/hero-vadim-2026.webp': 'runtime-asset',
    'yandex_98b0fe03a0ad0233.html': 'site-verification',
    'en/index.html': 'legacy-handoff',
    'en/index.html.md': 'legacy-handoff',
    'en/projects/index.html': 'legacy-handoff',
    'en/context/index.html': 'legacy-handoff',
    'en/approach/index.html': 'legacy-handoff',
    'CNAME': 'hosting-control',
    '.nojekyll': 'hosting-control',
}

MIME_TYPES = {
    '.html': ['text/html'],
    '.md': ['text/markdown', 'text/x-markdown', 'text/plain'],
    '.txt': ['text/plain'],
    '.json': ['application/json'],
    '.jsonld': ['application/ld+json', 'application/json'],
    '.xml': ['application/xml', 'text/xml'],
    '.css': ['text/css'],
    '.js': ['text/javascript', 'application/javascript'],
    '.svg': ['image/svg+xml'],
    '.ico': ['image/x-icon', 'image/vnd.microsoft.icon'],
    '.png': ['image/png'],
    '.webp': ['image/webp'],
}


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key: ' + key)
        result[key] = value
    return result


def invalid_constant(value):
    raise ValueError('Non-JSON number: ' + value)


def catalog_validator():
    spec = importlib.util.spec_from_file_location('delivery_catalog_validation', ROOT / 'scripts/validate-discovery.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.validate_catalog_document


def public_files():
    files = dict(FIXED_FILES)
    for path in PAGES:
        files[path] = 'canonical-page'
        files[path + '.md'] = 'reading-document'
        files[lite_path(path)] = 'reading-page'
        files[index_path(path)] = 'reading-index'
    for resource in RESOURCES:
        files.setdefault(resource.path, 'catalog-resource')
    for path in CATALOG_PATHS.values():
        files[path] = 'discovery-catalog'
    return files


def representation(path, role):
    if role == 'hosting-control':
        return None, [], 'text'
    suffix = Path(path).suffix
    if suffix not in MIME_TYPES:
        raise ValueError('No transport MIME policy for ' + path)
    content_types = list(MIME_TYPES[suffix])
    if path == CATALOG_PATHS['ai-catalog']:
        content_types.insert(0, 'application/ai-catalog+json')
    if path == CATALOG_PATHS['ard']:
        content_types.append('application/ld+json')
    if suffix in ('.json', '.jsonld'):
        payload_format = 'json'
    elif suffix == '.xml':
        payload_format = 'xml'
    elif suffix == '.html':
        payload_format = 'html'
    elif suffix in ('.txt', '.md', '.css', '.js', '.svg'):
        payload_format = 'text'
    else:
        payload_format = 'binary'
    url_path = urlsplit(canonical(path)).path if path.endswith('index.html') else '/' + path
    return url_path, content_types, payload_format


def validate_staged_references(staging):
    """Catch new linked assets that were not added to the publication inventory."""
    def check(value, document_path):
        url = urlsplit(urljoin(BASE + document_path, value))
        if url.scheme not in ('http', 'https') or url.hostname != urlsplit(BASE).hostname:
            return
        path = unquote(url.path).lstrip('/')
        if not path or path.endswith('/'):
            path += 'index.html'
        target = (staging / path).resolve()
        if not target.is_relative_to(staging.resolve()) or not target.is_file():
            raise ValueError(document_path + ': local reference is absent from dist: ' + value)

    def check_css(source, document_path):
        source = re.sub(r'/\*.*?\*/', '', source, flags=re.S)
        for match in re.finditer(r'url\(\s*([\'"]?)(.*?)\1\s*\)', source, re.I):
            check(match[2].strip(), document_path)
        for match in re.finditer(r'@import\s+[\'"]([^\'"]+)[\'"]', source, re.I):
            check(match[1], document_path)

    class References(HTMLParser):
        def __init__(self, document_path):
            super().__init__(convert_charrefs=True)
            self.document_path = document_path

        def handle_starttag(self, tag, pairs):
            attrs = dict(pairs)
            for key in ('href', 'src', 'poster'):
                if attrs.get(key):
                    check(attrs[key], self.document_path)
            if attrs.get('style'):
                check_css(attrs['style'], self.document_path)

    for source in staging.rglob('*'):
        if source.suffix not in ('.html', '.css'):
            continue
        document_path = source.relative_to(staging).as_posix()
        text = source.read_text(encoding='utf-8')
        if source.suffix == '.html':
            parser = References(document_path)
            parser.feed(text)
            parser.close()
        else:
            check_css(text, document_path)


def build(output, inventory_path):
    for destination in (output.absolute(), inventory_path.absolute()):
        if not destination.is_relative_to(ROOT):
            raise ValueError('Build outputs must be inside this repository')
        for candidate in (destination, *destination.parents):
            if candidate == ROOT:
                break
            if candidate.is_symlink():
                raise ValueError('Build destinations and their parents cannot be symbolic links')
    output, inventory_path = output.resolve(), inventory_path.resolve()
    # Only designated ignored build folders may be replaced. In particular,
    # --output . or --output assets must never delete source content.
    try:
        relative_output = output.relative_to(ROOT)
        relative_inventory = inventory_path.relative_to(ROOT)
    except ValueError as error:
        raise ValueError('Build outputs must be inside this repository') from error
    if not relative_output.parts or relative_output.parts[0] not in ('dist', '_dist', '_live'):
        raise ValueError('Output must be in dist, _dist, or _live')
    if not relative_inventory.parts or relative_inventory.parts[0] not in ('_dist', '_live'):
        raise ValueError('Keep the inventory in _dist or _live, outside public dist')
    if inventory_path.is_relative_to(output) or output.is_relative_to(inventory_path):
        raise ValueError('The inventory must be outside the published directory')
    files = public_files()
    validate_catalog = catalog_validator()
    resources = []
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.site-staging-', dir=output.parent) as staging_name:
        staging = Path(staging_name)
        for path, role in sorted(files.items()):
            source = ROOT / path
            if not source.is_file() or source.is_symlink() or not source.resolve().is_relative_to(ROOT):
                raise ValueError('Missing or unsafe published source: ' + path)
            # A symlinked parent must not smuggle a different tree into dist.
            if any(parent.is_symlink() for parent in source.parents if parent.is_relative_to(ROOT)):
                raise ValueError('Symlinked source directory: ' + path)
            body = source.read_bytes()
            url_path, content_types, payload_format = representation(path, role)
            if payload_format == 'json':
                document = json.loads(body, object_pairs_hook=unique_json, parse_constant=invalid_constant)
                if path in CATALOG_PATHS.values():
                    validate_catalog(path, document)
            elif payload_format == 'xml':
                ET.fromstring(body)
            if path == 'CNAME' and body.decode('utf-8').strip() != urlsplit(BASE).hostname:
                raise ValueError('CNAME differs from the canonical site domain')
            destination = staging / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(body)
            resources.append({
                'path': path,
                'role': role,
                'public_url_path': url_path,
                'transport_mime_types': content_types,
                'format': payload_format,
                'bytes': len(body),
                'sha256': hashlib.sha256(body).hexdigest(),
            })

        actual = {p.relative_to(staging).as_posix() for p in staging.rglob('*') if p.is_file()}
        if actual != set(files):
            raise ValueError('Published files differ from the generated inventory')
        validate_staged_references(staging)
        if output.exists():
            shutil.rmtree(output)
        os.replace(staging, output)

    inventory = {'schema_version': 1, 'source_base_url': BASE, 'files': resources}
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    inventory_path.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    public_count = sum(row['public_url_path'] is not None for row in resources)
    print(f'Built {len(resources)} files: {public_count} public resources and {len(resources) - public_count} hosting controls.')
    print('Inventory: ' + str(inventory_path.relative_to(ROOT)))
    return inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('dist'))
    parser.add_argument('--inventory', type=Path, default=Path('_dist/inventory.json'))
    args = parser.parse_args()
    build(ROOT / args.output, ROOT / args.inventory)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, ImportError) as error:
        print('Build failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
