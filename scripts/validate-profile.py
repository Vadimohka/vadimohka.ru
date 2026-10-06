#!/usr/bin/env python3
"""Keep the homepage a personal portfolio while preserving its supporting pages."""
from html.parser import HTMLParser
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]

class Home(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.cards = 0
        self.case_links = set()
        self.ids = set()
        self.h1 = ''
        self.in_h1 = False
        self.product_stage = False
        self.feed(text)

    def handle_starttag(self, tag, pairs):
        attrs = dict(pairs)
        classes = attrs.get('class', '').split()
        self.cards += int(tag == 'article' and 'work-card' in classes)
        self.product_stage |= 'century-stage' in classes
        if attrs.get('id'):
            self.ids.add(attrs['id'])
        if tag == 'h1':
            self.in_h1 = True
        if tag == 'a' and attrs.get('href', '').startswith('/projects/#'):
            self.case_links.add(attrs['href'])

    def handle_endtag(self, tag):
        if tag == 'h1':
            self.in_h1 = False

    def handle_data(self, text):
        if self.in_h1:
            self.h1 += text

try:
    text = (ROOT / 'index.html').read_text(encoding='utf-8')
    home = Home(text)
    checks = {
        'Three equally structured case introductions': home.cards == 3,
        'No full-page Century promotion': not home.product_stage and 'century' not in home.h1.lower(),
        'All original case destinations': home.case_links == {'/projects/#century', '/projects/#knowledge', '/projects/#ecommerce'},
        'Expertise, experience and contact remain on the home page': {'services', 'projects', 'background', 'education', 'contact'} <= home.ids,
        'Personal professional background remains visible': all(s in text for s in ('Вадим Владымцев', 'StackLevel Group', 'БГУИР', 'ICPC', 'Teach IT')),
    }
    for label, ok in checks.items():
        if not ok:
            raise ValueError(label)
    print('Personal profile validation passed: expertise, three equal cases and professional background.')
except (OSError, ValueError) as error:
    print(f'Personal profile validation failed: {error}', file=sys.stderr)
    sys.exit(1)
