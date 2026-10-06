#!/usr/bin/env python3
"""Offline checks for site metadata, domain boundaries, role and approved image."""
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
ROLE = 'Co-Founder Century | CTO StackLevel GROUP'
IMAGE = 'assets/hero-vadim-2026.webp'
IMAGE_SHA256 = '7861caaa5608ecbc2bcebc4760fd30c79eeb08f035bfee48456f6428db87ff13'
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
                require(tag == 'a' and key == 'href' and value == 'https://vadimohka.com/', f'{self.name}: .com outside English link')
                require(attrs.get('hreflang') == 'en' and attrs.get('lang') == 'en', f'{self.name}: missing English language')

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
    require(target.is_relative_to(ROOT) and target.is_file(), f'Missing or unsafe local target: {value}')
    return target, unquote(url.fragment)


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
        require(page.meta('og:url') == canonical and page.meta('twitter:card') == 'summary_large_image', f'{name}: wrong social metadata')
        for key in ('og:image','twitter:image'):
            require(page.meta(key) == BASE + IMAGE, f'{name}: wrong social image')
            local_target(page.meta(key), canonical)
        require(page.meta('og:image:type') == 'image/webp' and page.meta('og:image:width') == '1448' and page.meta('og:image:height') == '1086', f'{name}: wrong image metadata')
        require('© 2026' in text and page.json_blocks, f'{name}: missing copyright or structured data')
        if name != 'approach/index.html': require(ROLE in text, f'{name}: missing approved role')
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
    require(len(heroes) == 1, 'Expected one hero image')
    hero = heroes[0]
    require(hero['src'] == '/' + IMAGE and hero.get('loading') == 'eager' and hero.get('fetchpriority') == 'high', 'Wrong hero or priority')
    data = (ROOT / IMAGE).read_bytes()
    require(hashlib.sha256(data).hexdigest() == IMAGE_SHA256, 'Portrait differs from approved asset')
    require(data[:4] == b'RIFF' and data[8:12] == b'WEBP' and data[12:16] == b'VP8 ', 'Invalid WebP')
    require(len(data) == int.from_bytes(data[4:8], 'little') + 8, 'Truncated image')
    dimensions = tuple(v & 0x3fff for v in struct.unpack('<HH', data[26:30]))
    require((int(hero['width']),int(hero['height'])) == dimensions == (1448,1086), 'Wrong native portrait dimensions')
    require(len(data) < 200000, 'Portrait exceeds size budget')
    require(any(t == 'link' and a.get('rel') == 'preload' and a.get('href') == '/'+IMAGE for t,a in home.tags), 'Missing hero preload')
    require(not any(t == 'img' and 'portrait-note' in a.get('src','') for t,a in home.tags), 'Obsolete caption overlay')
    profile = json.loads((ROOT/'llm-profile.json').read_text(), object_pairs_hook=unique_json)
    person = json.loads((ROOT/'person.jsonld').read_text(), object_pairs_hook=unique_json)
    require(home.json_blocks == [profile], 'Inline and standalone profiles differ')
    people = [n for doc in (profile,person) for n in doc['@graph'] if n.get('@type') == 'Person']
    require(len(people) == 2 and people[0] == people[1], 'Person records differ')
    require(people[0]['url'] == BASE and people[0]['@id'] == BASE+'#person' and people[0]['image'] == BASE+IMAGE and people[0]['jobTitle'] == ROLE, 'Incorrect person identity or role')
    root = ET.parse(ROOT/'sitemap.xml'); ns={'s':'http://www.sitemaps.org/schemas/sitemap/0.9','image':'http://www.google.com/schemas/sitemap-image/1.1'}
    urls = [n.text for n in root.findall('s:url/s:loc',ns)]
    require(len(urls) == len(PAGES) and set(urls) == set(PAGES.values()), 'Sitemap differs from Russian pages')
    for image in root.findall('s:url/image:image/image:loc',ns): local_target(image.text,BASE)
    robots = (ROOT/'robots.txt').read_text().splitlines()
    require(all(s in robots for s in ('User-agent: *','Allow: /','Sitemap: '+BASE+'sitemap.xml')), 'Wrong robots.txt')
    require((ROOT/'CNAME').read_text().strip() == 'vadimohka.ru' and (ROOT/'.nojekyll').is_file(), 'Wrong domain or missing .nojekyll')
    for p in ROOT.rglob('*'):
        if not p.is_file(): continue
        parts = p.relative_to(ROOT).parts
        if parts[0].startswith('.') or parts[0] in ('scripts','en','dist'): continue
        if p.suffix in ('.txt','.json','.jsonld','.md','.xml','.css','.js'):
            require(not COM.search(p.read_text()), f'{p}: unexpected .com reference')
        elif p.suffix == '.html' and str(p.relative_to(ROOT)) not in PAGES: Page(p.read_text(),str(p))
    for p in ('index.html','projects/index.html','context/index.html','approach/index.html'):
        text=(ROOT/'en'/p).read_text()
        require('noindex' in text and 'https://vadimohka.com/' in text, f'en/{p}: invalid English handoff')
    require({'century','knowledge','ecommerce'} <= pages['projects/index.html'].ids, 'Missing case')
    require({'stacklevel','bsuir-dev','teach-it','startlab','senior-lecturer','assistant','icpc','student-projects','education','awards'} <= pages['background/index.html'].ids, 'Missing biography section')
    print('SEO validation passed: five pages, exact role, approved portrait, links, metadata, JSON-LD and English-only domain links.')


if __name__ == '__main__':
    try: main()
    except (ValueError,OSError,KeyError,IndexError,struct.error,ET.ParseError) as error:
        print(f'SEO validation failed: {error}',file=sys.stderr); sys.exit(1)
