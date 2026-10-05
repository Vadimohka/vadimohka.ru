#!/usr/bin/env python3
"""Validate metadata, local navigation, content coverage and domain boundaries.

Uses only the Python standard library, so it runs locally and in Pages CI.
"""
import json
import re
import struct
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://vadimohka.ru/'
PAGES = {'index.html': BASE, **{f'{s}/index.html': BASE + s + '/' for s in ('projects', 'background', 'context', 'approach')}}
COM = re.compile(r'vadimohka\.com\b', re.I)
IMAGE = 'assets/vadim-vladymtsev-2026.jpg'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f'Duplicate JSON key: {key}')
        result[key] = value
    return result


class Page(HTMLParser):
    def __init__(self, text, name):
        super().__init__(convert_charrefs=True)
        self.name = name
        self.tags, self.json_blocks = [], []
        self.ids = set()
        self.title = ''
        self.title_count = self.h1_count = 0
        self.in_title = self.in_head = False
        self.json_text = self.anchor = None
        self.feed(text)
        self.close()

    def handle_starttag(self, tag, pairs):
        attrs = dict(pairs)
        require(len(attrs) == len(pairs), f'{self.name}: duplicate HTML attribute on {tag}')
        self.tags.append((tag, attrs))
        if tag == 'head':
            self.in_head = True
        if tag == 'title':
            self.in_title = True
            self.title_count += 1
        if tag == 'h1':
            self.h1_count += 1
        if attrs.get('id'):
            require(attrs['id'] not in self.ids, f'{self.name}: duplicate id {attrs["id"]}')
            self.ids.add(attrs['id'])
        if tag == 'link' and attrs.get('rel') == 'canonical':
            require(self.in_head, f'{self.name}: canonical must be in head')
        if self.in_head:
            require(tag not in ('div', 'img', 'p'), f'{self.name}: invalid element in head: {tag}')
        if tag == 'script' and attrs.get('type') == 'application/ld+json':
            self.json_text = ''
        if tag == 'a':
            self.anchor = {'attrs': attrs, 'text': ''}
        for key, value in pairs:
            if value and COM.search(value):
                require(tag == 'a' and key == 'href', f'{self.name}: .com is only allowed in English links')
                require(urlsplit(value).hostname == 'vadimohka.com' and value.startswith('https://'), f'{self.name}: invalid English URL')

    def handle_endtag(self, tag):
        if tag == 'head':
            self.in_head = False
        if tag == 'title':
            self.in_title = False
        if tag == 'script' and self.json_text is not None:
            self.json_blocks.append(json.loads(self.json_text, object_pairs_hook=unique_json))
            self.json_text = None
        if tag == 'a' and self.anchor:
            attrs = self.anchor['attrs']
            if COM.search(attrs.get('href', '')):
                text = ' '.join(self.anchor['text'].lower().split())
                label = attrs.get('aria-label', '').lower()
                require(text in ('en', 'english', 'english version', 'английская версия') or 'английская версия' in label,
                        f'{self.name}: .com link must explicitly identify the English version')
                require(attrs.get('hreflang') == 'en', f'{self.name}: English link needs hreflang')
            self.anchor = None

    def handle_data(self, data):
        require(not COM.search(data), f'{self.name}: unexpected .com in text or script')
        if self.in_title:
            self.title += data
        if self.json_text is not None:
            self.json_text += data
        if self.anchor:
            self.anchor['text'] += data

    def meta(self, key):
        values = [a.get('content', '') for tag, a in self.tags if tag == 'meta' and (a.get('name') == key or a.get('property') == key)]
        require(len(values) == 1 and values[0].strip(), f'{self.name}: expected one nonempty {key}')
        return values[0]


def local_file(value, canonical):
    url = urlsplit(urljoin(canonical, value))
    if url.scheme not in ('http', 'https') or url.hostname != 'vadimohka.ru':
        return None
    path = unquote(url.path).lstrip('/')
    if not path or path.endswith('/'):
        path += 'index.html'
    resolved = (ROOT / path).resolve()
    require(resolved.is_relative_to(ROOT), f'Asset escapes site root: {value}')
    require(resolved.is_file(), f'Missing local target: {value}')
    return resolved


def jpeg_dimensions(path):
    data = path.read_bytes()
    require(data.startswith(b'\xff\xd8') and data.endswith(b'\xff\xd9'), 'Invalid JPEG file')
    offset = 2
    while offset < len(data):
        require(data[offset] == 255, 'Invalid JPEG marker')
        while data[offset] == 255:
            offset += 1
        marker = data[offset]
        offset += 1
        size = struct.unpack_from('>H', data, offset)[0]
        if marker in (0xC0, 0xC1, 0xC2):
            height, width = struct.unpack_from('>HH', data, offset + 3)
            return width, height
        offset += size
    raise ValueError('JPEG dimensions not found')


def main():
    pages = {name: Page((ROOT / name).read_text(encoding='utf-8'), name) for name in PAGES}
    titles, descriptions = set(), set()
    for name, canonical in PAGES.items():
        page = pages[name]
        canonicals = [a['href'] for t, a in page.tags if t == 'link' and a.get('rel') == 'canonical']
        require(canonicals == [canonical], f'{name}: wrong canonical')
        require(any(t == 'html' and a.get('lang', '').startswith('ru') for t, a in page.tags), f'{name}: wrong language')
        require(page.title_count == 1 and page.title.strip() and page.h1_count == 1, f'{name}: expected one title and H1')
        require(page.title not in titles, f'{name}: duplicate title')
        titles.add(page.title)
        description = page.meta('description')
        require(description not in descriptions, f'{name}: duplicate description')
        descriptions.add(description)
        robots = {p.strip() for p in page.meta('robots').split(',')}
        require({'index', 'follow'} <= robots and 'noindex' not in robots, f'{name}: wrong robots directive')
        require(page.meta('og:url') == canonical, f'{name}: wrong og:url')
        require(page.meta('twitter:card') == 'summary_large_image', f'{name}: wrong Twitter card')
        for key in ('og:image', 'twitter:image'):
            require(page.meta(key) == BASE + IMAGE, f'{name}: use the supplied portrait on .ru')
        require(page.json_blocks, f'{name}: missing structured data')
        hrefs = {a.get('href') for t, a in page.tags if t == 'a'}
        require({'/', '/projects/', '/background/', '/approach/', '/context/'} <= hrefs, f'{name}: incomplete site navigation')
        for tag, attrs in page.tags:
            require(not (tag == 'meta' and attrs.get('http-equiv', '').lower() == 'refresh'), f'{name}: unexpected redirect')
            if tag == 'img':
                require('alt' in attrs, f'{name}: image without alt')
            if tag == 'a' and attrs.get('target') == '_blank':
                require('noopener' in attrs.get('rel', '').split(), f'{name}: unsafe external link')
            for key in ('href', 'src'):
                if not attrs.get(key):
                    continue
                target = local_file(attrs[key], canonical)
                fragment = unquote(urlsplit(attrs[key]).fragment)
                if target and fragment and target.suffix == '.html':
                    target_name = target.relative_to(ROOT).as_posix()
                    target_page = pages.get(target_name) or Page(target.read_text(encoding='utf-8'), target_name)
                    require(fragment in target_page.ids, f'{name}: broken cross-page anchor {attrs[key]}')
        require('© 2026' in (ROOT / name).read_text(encoding='utf-8'), f'{name}: copyright must show 2026')

    home = pages['index.html']
    heroes = [a for t, a in home.tags if t == 'img' and 'hero-img' in a.get('class', '').split()]
    require(len(heroes) == 1, 'Expected exactly one hero image')
    hero = heroes[0]
    require(hero.get('src') == '/' + IMAGE and hero.get('alt'), 'Wrong hero image or missing alt')
    require(hero.get('loading') == 'eager' and hero.get('fetchpriority') == 'high', 'Hero must load eagerly at high priority')
    require((int(hero['width']), int(hero['height'])) == jpeg_dimensions(ROOT / IMAGE), 'Hero dimensions differ from JPEG')
    profiles = {}
    for name in ('person.jsonld', 'llm-profile.json'):
        text = (ROOT / name).read_text(encoding='utf-8')
        require(not COM.search(text), f'{name}: .com is not allowed in entity data')
        profiles[name] = json.loads(text, object_pairs_hook=unique_json)
    require(home.json_blocks == [profiles['llm-profile.json']], 'Inline and standalone JSON-LD must stay synchronized')
    people = [node for doc in profiles.values() for node in doc['@graph'] if node.get('@type') == 'Person']
    require(len(people) == 2 and people[0] == people[1], 'Person data must stay synchronized')
    require(people[0]['@id'] == BASE + '#person' and people[0]['url'] == BASE and people[0]['image'] == BASE + IMAGE, 'Person must use .ru identity and the new image')
    # The redesign must not silently drop the case studies or career sections.
    require({'century', 'knowledge', 'ecommerce', 'high-risk'} <= pages['projects/index.html'].ids, 'Missing case study or legacy project anchor')
    require({'industry', 'academia', 'education', 'awards'} <= pages['background/index.html'].ids, 'Missing career section')
    require({'services', 'projects', 'background', 'education', 'contact'} <= home.ids, 'Broken legacy homepage section links')
    background = (ROOT / 'background/index.html').read_text(encoding='utf-8')
    for text in ('StackLevel Group', 'Teach IT', 'БГУИР', '2023 — 2026', '2017 — 2021', 'ICPC'):
        require(text in background, f'Career content lost: {text}')
    require('прототип' in (ROOT / 'projects/index.html').read_text(encoding='utf-8').lower(), 'E-commerce must still be labelled a prototype')

    sitemap = ET.parse(ROOT / 'sitemap.xml')
    ns = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9', 'image': 'http://www.google.com/schemas/sitemap-image/1.1'}
    locations = [n.text for n in sitemap.findall('s:url/s:loc', ns)]
    require(len(locations) == len(PAGES) and set(locations) == set(PAGES.values()), 'Sitemap must contain exactly the Russian canonical pages')
    for image in sitemap.findall('s:url/image:image/image:loc', ns):
        require(image.text.startswith(BASE), 'Sitemap image must be on .ru')
        local_file(image.text, BASE)
    robots = (ROOT / 'robots.txt').read_text(encoding='utf-8').splitlines()
    for line in ('User-agent: *', 'Allow: /', 'Sitemap: ' + BASE + 'sitemap.xml'):
        require(line in robots, f'robots.txt: missing {line}')
    require((ROOT / 'CNAME').read_text().strip() == 'vadimohka.ru', 'Wrong custom domain')
    require((ROOT / '.nojekyll').is_file(), 'Missing .nojekyll')
    for path in ROOT.rglob('*'):
        if not path.is_file():
            continue
        parts = path.relative_to(ROOT).parts
        if parts[0].startswith('.') or parts[0] in ('scripts', 'dist', 'en'):
            continue
        if path.suffix in ('.json', '.jsonld', '.txt', '.md', '.xml', '.css', '.js'):
            require(not COM.search(path.read_text(encoding='utf-8')), f'{path.relative_to(ROOT)}: unexpected .com reference')
        elif path.suffix == '.html' and path.relative_to(ROOT).as_posix() not in PAGES:
            Page(path.read_text(encoding='utf-8'), path.relative_to(ROOT).as_posix())
    for name in ('index.html', 'projects/index.html', 'context/index.html', 'approach/index.html'):
        text = (ROOT / 'en' / name).read_text(encoding='utf-8')
        require('noindex' in text and 'https://vadimohka.com/' in text, f'en/{name}: invalid English handoff')
    print(f'SEO validation passed: {len(PAGES)} Russian pages, local links and fragments, cases, career, portrait, JSON-LD and English-only .com links.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, IndexError, struct.error, ET.ParseError) as error:
        print(f'SEO validation failed: {error}', file=sys.stderr)
        sys.exit(1)
