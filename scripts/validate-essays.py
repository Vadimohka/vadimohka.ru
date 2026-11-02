#!/usr/bin/env python3
"""Independently verify essay HTML, structured data, archive and RSS fidelity.

The parser deliberately does not import the generator: a stale or internally
consistent but incorrect export must still fail against the visible HTML.
"""
import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

from site_model import (
    BASE, ROOT, PERSON_ID, ESSAY_INDEX_PATH, ESSAY_FEED_PATH, ESSAY_SPECS,
    canonical, lite_path,
)

VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
        'meta', 'param', 'source', 'track', 'wbr'}
BLOCKS = {'h2', 'h3', 'h4', 'p', 'li', 'pre'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def normalized(value):
    return ' '.join(value.split())


def russian_date_label(value):
    """Check the displayed date independently from the production generator."""
    parsed = date.fromisoformat(value)
    months = {1: 'января', 2: 'февраля', 3: 'марта', 4: 'апреля',
              5: 'мая', 6: 'июня', 7: 'июля', 8: 'августа',
              9: 'сентября', 10: 'октября', 11: 'ноября', 12: 'декабря'}
    return f'{parsed.day} {months[parsed.month]} {parsed.year}'


class EssayHTML(HTMLParser):
    def __init__(self, source, url):
        super().__init__(convert_charrefs=True)
        self.url = url
        self.stack = []
        self.head_links = []
        self.meta = {}
        self.h1 = []
        self.h1_count = 0
        self.body_count = 0
        self.body_blocks = []
        self.frames = []
        self.times = []
        self.time_frames = []
        self.heading_links = []
        self.link_frames = []
        self.cards = []
        self.card_frames = []
        self.json_text = None
        self.graph = []
        self.feed(source)
        self.close()

    def handle_starttag(self, tag, pairs):
        attrs = dict(pairs)
        in_head = any(t == 'head' for t, _ in self.stack)
        if tag == 'link' and in_head:
            self.head_links.append(attrs)
        if tag == 'meta' and in_head:
            key = attrs.get('name', attrs.get('property'))
            self.meta.setdefault(key, []).append(attrs.get('content', ''))
        if tag not in VOID:
            self.stack.append((tag, attrs))
        if tag == 'script' and attrs.get('type') == 'application/ld+json':
            self.json_text = []
        if tag == 'h1':
            self.h1_count += 1
        if attrs.get('id') == 'essay-body':
            self.body_count += 1
        in_main = any(t == 'main' for t, _ in self.stack)
        in_body = any(a.get('id') == 'essay-body' for _, a in self.stack)
        if in_main and tag == 'article' and 'essay-card' in attrs.get('class', '').split():
            self.card_frames.append((len(self.stack), {'links': [], 'times': []}))
        card = self.card_frames[-1][1] if self.card_frames else None
        if in_body and tag in BLOCKS:
            self.frames.append((len(self.stack), []))
        if in_main and tag == 'time' and (card is not None or 'essay-date' in attrs.get('class', '').split()):
            self.time_frames.append((len(self.stack), attrs.get('datetime'), [], card))
        if in_main and tag == 'a' and attrs.get('href') and any(t == 'h2' for t, _ in self.stack):
            self.link_frames.append((len(self.stack), urljoin(self.url, attrs['href']), [], card))

    def handle_startendtag(self, tag, pairs):
        self.handle_starttag(tag, pairs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == 'script' and self.json_text is not None:
            document = json.loads(''.join(self.json_text))
            self.graph.extend(document.get('@graph', []))
            self.json_text = None
        index = next((i for i in range(len(self.stack) - 1, -1, -1)
                      if self.stack[i][0] == tag), None)
        if index is None:
            return
        for depth, parts in self.frames:
            if depth > index:
                self.body_blocks.append(normalized(''.join(parts)))
        self.frames = [frame for frame in self.frames if frame[0] <= index]
        for depth, value, parts, card in self.time_frames:
            if depth > index:
                times = self.times if card is None else card['times']
                times.append((value, normalized(''.join(parts))))
        self.time_frames = [frame for frame in self.time_frames if frame[0] <= index]
        for depth, url, parts, card in self.link_frames:
            if depth > index:
                entry = (url, normalized(''.join(parts)))
                self.heading_links.append(entry)
                if card is not None:
                    card['links'].append(entry)
        self.link_frames = [frame for frame in self.link_frames if frame[0] <= index]
        for depth, card in self.card_frames:
            if depth > index:
                self.cards.append(card)
        self.card_frames = [frame for frame in self.card_frames if frame[0] <= index]
        del self.stack[index:]

    def handle_data(self, text):
        if self.json_text is not None:
            self.json_text.append(text)
            return
        if any(tag in ('script', 'style', 'nav', 'svg', 'noscript')
               or attrs.get('aria-hidden') == 'true' or 'hidden' in attrs
               for tag, attrs in self.stack):
            return
        if any(tag == 'h1' for tag, _ in self.stack):
            self.h1.append(text + ' ')
        for _, parts in self.frames:
            parts.append(text + ' ')
        for _, _, parts, _ in self.time_frames:
            parts.append(text + ' ')
        for _, _, parts, _ in self.link_frames:
            parts.append(text + ' ')

    @property
    def headline(self):
        return normalized(''.join(self.h1))

    def node(self, identifier, schema_type):
        nodes = [node for node in self.graph if node.get('@id') == identifier]
        require(len(nodes) == 1 and nodes[0].get('@type') == schema_type,
                self.url + ': missing or ambiguous ' + schema_type)
        return nodes[0]


def check_feed_link(facts):
    links = [link for link in facts.head_links if link.get('type') == 'application/rss+xml']
    require(len(links) == 1 and links[0].get('rel') == 'alternate'
            and urljoin(facts.url, links[0].get('href', '')) == BASE + ESSAY_FEED_PATH,
            facts.url + ': missing or wrong RSS discovery link')


def validate_essays(root=ROOT):
    root = Path(root)
    archive_url = canonical(ESSAY_INDEX_PATH)
    archive = EssayHTML((root / ESSAY_INDEX_PATH).read_text(encoding='utf-8'), archive_url)
    check_feed_link(archive)
    collection = archive.node(archive_url + '#webpage', 'CollectionPage')
    listing = archive.node(archive_url + '#items', 'ItemList')
    require(collection.get('mainEntity') == {'@id': listing['@id']},
            'Essay archive mainEntity does not identify its list')
    expected_urls = {canonical(spec.path) for spec in ESSAY_SPECS}
    ordered_urls = [url for url, _ in archive.heading_links]
    require(len(ordered_urls) == len(expected_urls) and set(ordered_urls) == expected_urls,
            'Essay archive must contain every essay link exactly once')
    expected_entries = [{'@type': 'ListItem', 'position': i, 'name': label, 'url': url}
                        for i, (url, label) in enumerate(archive.heading_links, 1)]
    require(listing.get('itemListElement') == expected_entries
            and listing.get('numberOfItems') == len(expected_entries),
            'Essay ItemList differs from visible archive order or titles')
    require(collection.get('hasPart') == [{'@id': url + '#article'} for url in ordered_urls],
            'Essay archive hasPart differs from published essays')
    facts_by_url, published_by_url = {}, {}
    for spec in ESSAY_SPECS:
        url = canonical(spec.path)
        facts = EssayHTML((root / spec.path).read_text(encoding='utf-8'), url)
        facts_by_url[url] = facts
        check_feed_link(facts)
        lite = EssayHTML((root / lite_path(spec.path)).read_text(encoding='utf-8'),
                         BASE + lite_path(spec.path))
        check_feed_link(lite)
        require(facts.h1_count == 1 and facts.headline, spec.path + ': expected one essay headline')
        require(facts.body_count == 1 and len(facts.body_blocks) >= 2
                and all(facts.body_blocks), spec.path + ': missing or empty essay body')
        require(facts.meta.get('og:type') == ['article'], spec.path + ': essay og:type must be article')
        page = facts.node(url + '#webpage', 'WebPage')
        article = facts.node(url + '#article', 'Article')
        require(article.get('headline') == facts.headline, spec.path + ': Article headline differs from H1')
        require(page.get('mainEntity') == {'@id': article['@id']}
                and article.get('mainEntityOfPage') == {'@id': page['@id']},
                spec.path + ': Article and WebPage identity links differ')
        require(article.get('author') == {'@id': PERSON_ID}
                and article.get('publisher') == {'@id': PERSON_ID},
                spec.path + ': Article author or publisher differs from the canonical person')
        require(page.get('isPartOf') == article.get('isPartOf') == {'@id': archive_url + '#webpage'},
                spec.path + ': essay is not part of its archive')
        for field in ('datePublished', 'dateModified'):
            value = page.get(field)
            require(isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value),
                    spec.path + ': missing editorial ' + field)
            date.fromisoformat(value)
            require(article.get(field) == value, spec.path + ': Article date differs from WebPage')
        require(page['datePublished'] <= page['dateModified'], spec.path + ': invalid publication chronology')
        require(len(facts.times) == 1 and facts.times[0][0] == page['datePublished'],
                spec.path + ': visible publication date differs from structured data')
        require(facts.times[0][1] == russian_date_label(page['datePublished']),
                spec.path + ': visible publication label differs from the ISO date')
        published_by_url[url] = page['datePublished']
        body = '\n\n'.join(facts.body_blocks)
        require(article.get('articleBody') == body, spec.path + ': Article body differs from visible prose')
        words = len(re.findall(r"\b\w+(?:[-’']\w+)*\b", body))
        require(type(article.get('wordCount')) is int and article['wordCount'] == words,
                spec.path + ': Article wordCount differs from visible prose')
        crumb = facts.node(url + '#breadcrumb', 'BreadcrumbList')
        require(page.get('breadcrumb') == {'@id': crumb['@id']}
                and crumb.get('itemListElement') == [
                    {'@type': 'ListItem', 'position': 1, 'name': 'Главная', 'item': BASE},
                    {'@type': 'ListItem', 'position': 2, 'name': 'Эссе', 'item': archive_url},
                    {'@type': 'ListItem', 'position': 3, 'name': facts.headline, 'item': url}],
                spec.path + ': essay breadcrumb hierarchy is incomplete')
    require(all(facts_by_url[url].headline == label for url, label in archive.heading_links),
            'Essay archive title differs from article H1')
    require(len(archive.cards) == len(ordered_urls)
            and all(len(card['links']) == 1 for card in archive.cards)
            and [card['links'][0][0] for card in archive.cards] == ordered_urls,
            'Essay archive links must belong to their corresponding cards')
    for card in archive.cards:
        url = card['links'][0][0]
        published = published_by_url[url]
        require(len(card['times']) == 1 and card['times'][0][0] == published,
                url + ': archive card publication date differs from article')
        require(card['times'][0][1] == russian_date_label(published),
                url + ': archive card publication label differs from the ISO date')
    ordered_dates = [published_by_url[url] for url in ordered_urls]
    require(ordered_dates == sorted(ordered_dates, reverse=True),
            'Essay archive is not ordered by publication date descending')
    feed = ET.parse(root / ESSAY_FEED_PATH).getroot()
    require(feed.tag == 'rss' and feed.attrib == {'version': '2.0'}, 'Expected RSS 2.0 essay feed')
    channels = feed.findall('channel')
    require(len(channels) == 1, 'Expected one RSS channel')
    channel = channels[0]
    require(channel.findtext('link') == archive_url and channel.findtext('language') == 'ru',
            'RSS channel differs from the Russian essay archive')
    self_link = channel.find('{http://www.w3.org/2005/Atom}link')
    require(self_link is not None and self_link.attrib == {
        'href': BASE + ESSAY_FEED_PATH, 'rel': 'self', 'type': 'application/rss+xml'},
        'RSS self link is missing or incorrect')
    items = channel.findall('item')
    require([item.findtext('link') for item in items] == ordered_urls,
            'RSS items differ from visible archive order or inventory')
    for item in items:
        facts = facts_by_url[item.findtext('link')]
        require(item.findtext('title') == facts.headline
                and item.findtext('description') == facts.meta['description'][0],
                'RSS title or description differs from editorial HTML')
        guid = item.find('guid')
        require(guid is not None and guid.text == facts.url and guid.get('isPermaLink') == 'true',
                'RSS item has an unstable or incorrect GUID')
        dates = item.findall('{http://purl.org/dc/elements/1.1/}date')
        require(len(dates) == 1 and dates[0].text == published_by_url[facts.url],
                'RSS dc:date differs from the article publication date or loses day precision')
        require(item.find('pubDate') is None, 'RSS invents a publication time for a date-only source')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    validate_essays(args.root)
    print(f'Essay validation passed: {len(ESSAY_SPECS)} complete articles, Russian date labels, attribution, '
          'articleBody, wordCount, hierarchical breadcrumbs, chronological archive and dated RSS.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, ET.ParseError) as error:
        print('Essay validation failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
