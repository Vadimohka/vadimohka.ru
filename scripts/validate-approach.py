#!/usr/bin/env python3
"""Check the rendered approach copy against the user's Markdown, without rewriting."""
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class Copy(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.in_main = False
        self.current = None
        self.blocks = []
        self.links = []
        self.meta = {}
        self.title = ''
        self.in_title = False
        self.feed(text)

    def handle_starttag(self, tag, pairs):
        attrs = dict(pairs)
        if tag == 'main': self.in_main = True
        if tag == 'title': self.in_title = True
        if tag == 'meta': self.meta[attrs.get('name') or attrs.get('property')] = attrs.get('content')
        if self.in_main:
            if tag in ('h1','h2','h3','p'): self.current = [tag, '']
            if tag == 'a': self.links.append(attrs.get('href'))

    def handle_endtag(self, tag):
        if tag == 'title': self.in_title = False
        if tag == 'main': self.in_main = False
        if self.current and tag == self.current[0]:
            self.blocks.append(tuple(self.current)); self.current = None

    def handle_data(self, text):
        if self.current: self.current[1] += text
        if self.in_title: self.title += text

try:
    source = (ROOT/'scripts/content/approach.md').read_text(encoding='utf-8')
    body, meta = source.split('## Метаданные страницы', 1)
    body = body.rstrip().removesuffix('---').rstrip()
    expected = []
    for text in re.split(r'\n\s*\n', body):
        match = re.match(r'^(#{1,3}) (.*)$', text.strip(), re.S)
        tag, text = ('h'+str(len(match[1])), match[2]) if match else ('p', text.strip())
        text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1', text)
        expected.append((tag,text))
    actual = Copy((ROOT/'approach/index.html').read_text(encoding='utf-8'))
    if actual.blocks != expected: raise ValueError('Approach headings or paragraphs differ from author copy')
    if actual.links != re.findall(r'\[[^\]]+\]\(([^)]+)\)',body): raise ValueError('Approach links differ from author copy')
    title = re.search(r'\*\*Title:\*\*\s*(.*)',meta)[1]
    desc = re.search(r'\*\*Description:\*\*\s*(.*)',meta)[1]
    if actual.title != title or actual.meta['description'] != desc: raise ValueError('Author metadata differs')
    if actual.meta['og:title'] != title or actual.meta['twitter:title'] != title: raise ValueError('Social titles differ')
    if actual.meta['og:description'] != desc or actual.meta['twitter:description'] != desc: raise ValueError('Social descriptions differ')
    print(f'Approach source validation passed: {len(expected)} exact blocks, all links and author metadata.')
except (ValueError,OSError,KeyError,TypeError) as error:
    print(f'Approach source validation failed: {error}',file=sys.stderr);sys.exit(1)
