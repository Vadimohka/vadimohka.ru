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
        self.ids = []
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
            self.ids.append(attrs['id'])
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
    biography = (ROOT / 'background/index.html').read_text(encoding='utf-8')
    projects = (ROOT / 'projects/index.html').read_text(encoding='utf-8')
    checks = {
        'Three equally structured project introductions': home.cards == 3,
        'The person, not the product, is the main heading': not home.product_stage and 'Вадим' in home.h1 and 'Владымцев' in home.h1,
        'Current project destinations': home.case_links == {'/projects/#century', '/projects/#belka', '/projects/#multiverse'},
        'Expertise, experience and contact remain on the homepage': {'services', 'projects', 'background', 'education', 'contact'} <= set(home.ids),
        'Path and skills precede projects': home.ids.index('background') < home.ids.index('projects') and home.ids.index('services') < home.ids.index('projects'),
        'Personal background remains visible': all(s in text for s in ('Вадим', 'Владымцев', 'StackLevel Group', 'БГУИР', 'ICPC', 'Teach IT', 'МФТИ')),
        'Current teaching and MIPT professional development': all(s in biography for s in ('Готовлю и тренирую', 'ROZUM', 'Спортивное программирование для тренеров', 'Повышение квалификации')),
        'Research maturity remains explicit': 'научным хобби' in projects and 'ранний MVP' in projects,
    }
    for label, ok in checks.items():
        if not ok:
            raise ValueError(label)
    print('Personal profile validation passed: person-first structure, skills, teaching, MIPT and current project status.')
except (OSError, ValueError) as error:
    print(f'Personal profile validation failed: {error}', file=sys.stderr)
    sys.exit(1)
