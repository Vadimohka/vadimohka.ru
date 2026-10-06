#!/usr/bin/env python3
"""Offline checks for metadata, real portrait, current role and local navigation."""
import hashlib
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
PAGES = {'index.html': BASE, **{f'{s}/index.html': BASE + s + '/' for s in ('projects', 'background', 'approach', 'context')}}
IMAGE = 'assets/vadim-vladymtsev-2026.jpg'
COM = re.compile(r'vadimohka\.com\b', re.I)


def require(ok, message):
    if not ok:
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
        self.name, self.tags, self.ids = name, [], set()
        self.title, self.title_count, self.h1_count = '', 0, 0
        self.in_title = self.in_head = False
        self.json_text, self.anchor = None, None
        self.json_blocks = []
        self.feed(text)
        self.close()

    def handle_starttag(self, tag, pairs):
        attrs = dict(pairs)
        self.tags.append((tag, attrs))
        if tag == 'head': self.in_head = True
        if tag == 'title': self.in_title = True; self.title_count += 1
        if tag == 'h1': self.h1_count += 1
        if attrs.get('id'):
            require(attrs['id'] not in self.ids, f'{self.name}: duplicate ID {attrs["id"]}')
            self.ids.add(attrs['id'])
        if self.in_head:
            require(tag not in ('div', 'img', 'p'), f'{self.name}: invalid head child {tag}')
        if tag == 'link' and attrs.get('rel') == 'canonical':
            require(self.in_head, f'{self.name}: canonical outside head')
        if tag == 'script' and attrs.get('type') == 'application/ld+json': self.json_text = ''
        if tag == 'a': self.anchor = {'attrs': attrs, 'text': ''}
        for key, value in pairs:
            if value and COM.search(value):
                require(tag == 'a' and key == 'href', f'{self.name}: .com outside English link')
                require(value == 'https://vadimohka.com/', f'{self.name}: unexpected English target')
                require(attrs.get('hreflang') == 'en' and attrs.get('lang') == 'en', f'{self.name}: English link missing language')

    def handle_endtag(self, tag):
        if tag == 'head': self.in_head = False
        if tag == 'title': self.in_title = False
        if tag == 'script' and self.json_text is not None:
            self.json_blocks.append(json.loads(self.json_text, object_pairs_hook=unique_json))
            self.json_text = None
        if tag == 'a' and self.anchor:
            if COM.search(self.anchor['attrs'].get('href', '')):
                require(self.anchor['text'].strip() == 'EN', f'{self.name}: unlabeled English link')
            self.anchor = None

    def handle_data(self, text):
        require(not COM.search(text), f'{self.name}: unexpected .com in text or script')
        if self.in_title: self.title += text
        if self.json_text is not None: self.json_text += text
        if self.anchor: self.anchor['text'] += text

    def meta(self, key):
        values = [a.get('content', '') for t, a in self.tags if t == 'meta' and (a.get('name') == key or a.get('property') == key)]
        require(len(values) == 1 and values[0].strip(), f'{self.name}: missing or duplicate {key}')
        return values[0]


def local_target(value, canonical):
    url = urlsplit(urljoin(canonical, value))
    if url.scheme not in ('http', 'https') or url.hostname != 'vadimohka.ru': return None, None
    path = unquote(url.path).lstrip('/')
    if not path or path.endswith('/'): path += 'index.html'
    target = (ROOT / path).resolve()
    require(target.is_relative_to(ROOT), f'Path escapes root: {value}')
    require(target.is_file(), f'Missing local target: {value}')
    return target, unquote(url.fragment)


def jpeg_dimensions(data):
    require(data[:2] == b'\xff\xd8' and data[-2:] == b'\xff\xd9', 'Invalid portrait JPEG')
    offset = 2
    while offset + 4 < len(data):
        require(data[offset] == 255, 'Invalid JPEG marker')
        while data[offset] == 255: offset += 1
        marker = data[offset]; offset += 1
        size = struct.unpack_from('>H', data, offset)[0]
        if marker in (0xc0, 0xc1, 0xc2):
            height, width = struct.unpack_from('>HH', data, offset + 3)
            return width, height
        require(size >= 2, 'Invalid JPEG segment')
        offset += size
    raise ValueError('Missing JPEG dimensions')


def main():
    pages, titles, descriptions = {}, set(), set()
    for name, canonical in PAGES.items():
        text = (ROOT / name).read_text(encoding='utf-8')
        page = Page(text, name); pages[name] = page
        require([a.get('href') for t,a in page.tags if t == 'link' and a.get('rel') == 'canonical'] == [canonical], f'{name}: wrong canonical')
        require(any(t == 'html' and a.get('lang') == 'ru' for t,a in page.tags), f'{name}: wrong language')
        require(page.title_count == 1 and page.h1_count == 1 and page.title.strip(), f'{name}: expected one title and H1')
        require(page.title not in titles, f'{name}: duplicate title'); titles.add(page.title)
        desc = page.meta('description'); require(desc not in descriptions, f'{name}: duplicate description'); descriptions.add(desc)
        robots = set(page.meta('robots').split(','))
        require({'index','follow'} <= robots and 'noindex' not in robots, f'{name}: wrong robots')
        require(page.meta('og:url') == canonical, f'{name}: wrong Open Graph URL')
        require(page.meta('twitter:card') == 'summary_large_image', f'{name}: wrong social card')
        for key in ('og:image','twitter:image'):
            require(page.meta(key) == BASE + IMAGE, f'{name}: wrong social image')
        require('© 2026' in text, f'{name}: wrong copyright year')
        require(page.json_blocks, f'{name}: missing structured data')
        require('portrait-note-2026.webp' not in text, f'{name}: low-quality mockup screenshot returned')
        require(not re.search(r'Заместитель директора по R(?:&amp;|&)D|R&D Director', text), f'{name}: obsolete current title')
        for tag, attrs in page.tags:
            require(not (tag == 'meta' and attrs.get('http-equiv','').lower() == 'refresh'), f'{name}: unexpected redirect')
            if tag == 'img': require('alt' in attrs, f'{name}: image without alt')
    for name, page in pages.items():
        for tag, attrs in page.tags:
            for key in ('href','src'):
                if not attrs.get(key): continue
                target, fragment = local_target(attrs[key], PAGES[name])
                if target and fragment:
                    rel = str(target.relative_to(ROOT))
                    if rel in pages: require(fragment in pages[rel].ids, f'{name}: broken fragment {attrs[key]}')
    home = pages['index.html']
    heroes = [a for t,a in home.tags if t == 'img' and 'hero-img' in a.get('class','').split()]
    require(len(heroes) == 1, 'Expected one photographic hero image')
    hero = heroes[0]
    require(hero['src'] == '/' + IMAGE, 'Hero must use the photograph, not a mockup')
    require(hero.get('loading') == 'eager' and hero.get('fetchpriority') == 'high', 'Hero must be prioritized')
    image_data = (ROOT / IMAGE).read_bytes()
    require((int(hero['width']), int(hero['height'])) == jpeg_dimensions(image_data) == (1200,800), 'Wrong portrait dimensions')
    # Keep the existing photographic source byte-for-byte, without another lossy encode.
    require(hashlib.sha1(b'blob ' + str(len(image_data)).encode() + b'\0' + image_data).hexdigest() == '1d6d73beae40f0edd1ecd35c8b5e6c1dbe32a09c', 'Portrait was replaced or recompressed')
    require(any(t == 'link' and a.get('rel') == 'preload' and a.get('href') == '/'+IMAGE for t,a in home.tags), 'Missing portrait preload')
    for name in ('assets/portrait-mask.svg', 'assets/portrait-note.svg'):
        ET.parse(ROOT/name)
    css = (ROOT/'assets/studio.css').read_text() + (ROOT/'assets/portrait.css').read_text()
    for value in re.findall(r"url\(['\"]?(/[^)'\"]+)['\"]?\)", css): local_target(value, BASE)
    profile = json.loads((ROOT/'llm-profile.json').read_text(), object_pairs_hook=unique_json)
    person = json.loads((ROOT/'person.jsonld').read_text(), object_pairs_hook=unique_json)
    require(home.json_blocks == [profile], 'Inline and standalone profiles differ')
    people = [n for doc in (profile,person) for n in doc['@graph'] if n.get('@type') == 'Person']
    require(len(people) == 2 and people[0] == people[1], 'Person records differ')
    require(people[0]['url'] == BASE and people[0]['@id'] == BASE+'#person' and people[0]['image'] == BASE+IMAGE, 'Incorrect person identity')
    require(people[0]['jobTitle'] == 'Технический директор (CTO)', 'Incorrect current position')
    root = ET.parse(ROOT/'sitemap.xml'); ns={'s':'http://www.sitemaps.org/schemas/sitemap/0.9'}
    urls = [n.text for n in root.findall('s:url/s:loc',ns)]
    require(len(urls) == len(PAGES) and set(urls) == set(PAGES.values()), 'Sitemap differs from Russian pages')
    for node in root.findall('.//{http://www.google.com/schemas/sitemap-image/1.1}loc'): local_target(node.text, BASE)
    robots = (ROOT/'robots.txt').read_text().splitlines()
    require(all(s in robots for s in ('User-agent: *','Allow: /','Sitemap: '+BASE+'sitemap.xml')), 'Wrong robots.txt')
    require((ROOT/'CNAME').read_text().strip() == 'vadimohka.ru', 'Wrong domain')
    require((ROOT/'.nojekyll').is_file(), 'Missing .nojekyll')
    for path in ROOT.rglob('*'):
        if not path.is_file(): continue
        parts = path.relative_to(ROOT).parts
        if parts[0].startswith('.') or parts[0] in ('scripts','en','dist'): continue
        if path.suffix in ('.txt','.json','.jsonld','.md','.xml','.css','.js'):
            require(not COM.search(path.read_text()), f'{path}: unexpected .com reference')
        elif path.suffix == '.html' and str(path.relative_to(ROOT)) not in PAGES: Page(path.read_text(),str(path))
    for path in ('index.html','projects/index.html','context/index.html','approach/index.html'):
        text = (ROOT/'en'/path).read_text()
        require('noindex' in text, f'en/{path}: invalid English handoff')
        en_page = Page(text, f'en/{path}')
        handoff_links = [a.get('href', '') for t, a in en_page.tags if t == 'a' and a.get('href')]
        require(any(
            (u.scheme, u.hostname, u.path, u.query, u.fragment) == ('https', 'vadimohka.com', '/', '', '')
            for u in (urlsplit(href) for href in handoff_links)
        ), f'en/{path}: invalid English handoff')
    require({'century','knowledge','ecommerce'} <= pages['projects/index.html'].ids, 'Missing case')
    require({'stacklevel','bsuir-dev','teach-it','startlab','senior-lecturer','assistant','icpc','student-projects','education','awards'} <= pages['background/index.html'].ids, 'Missing biography section')
    print('SEO validation passed: five pages, real portrait, CTO role, JSON-LD, local links, sitemap, English-only domain links and retained cases/career.')


if __name__ == '__main__':
    try: main()
    except (ValueError,OSError,KeyError,IndexError,struct.error,ET.ParseError) as error:
        print(f'SEO validation failed: {error}',file=sys.stderr); sys.exit(1)
