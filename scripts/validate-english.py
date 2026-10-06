#!/usr/bin/env python3
"""Validate legacy English handoffs without applying Russian-page restrictions."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]

class Handoff(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.robots = []
        self.feed(text)
        self.close()

    def handle_starttag(self, tag, pairs):
        attrs = dict(pairs)
        if tag == 'a' and attrs.get('href'):
            self.links.append(attrs['href'])
        if tag == 'meta' and attrs.get('name', '').lower() == 'robots':
            self.robots.extend(part.strip().lower() for part in attrs.get('content', '').split(','))

for name in ('index.html', 'projects/index.html', 'context/index.html', 'approach/index.html'):
    page = Handoff((ROOT/'en'/name).read_text(encoding='utf-8'))
    targets = [urlsplit(href) for href in page.links]
    valid = any((u.scheme, u.netloc, u.path, u.query, u.fragment) ==
                ('https', 'vadimohka.com', '/', '', '') for u in targets)
    if not valid or 'noindex' not in page.robots:
        raise SystemExit(f'Invalid English handoff: en/{name}')
print('English handoff validation passed: exact URL targets and noindex.')
