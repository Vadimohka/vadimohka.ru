#!/usr/bin/env python3
"""Synchronize SEO metadata and text representations with the five public pages.

Run with --write after editing the site, or --check in CI. Page bodies and the
owner's approach text are never rewritten. Uses only the Python standard library.
"""
import argparse
import copy
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://vadimohka.ru/'
ROLE = 'Co-Founder Century | CTO StackLevel GROUP'
PERSON_ID = BASE + '#person'
IMAGE = BASE + 'assets/hero-vadim-2026.webp'
PAGES = ['index.html', 'background/index.html', 'projects/index.html',
         'approach/index.html', 'context/index.html']
# The author's approach title and description are read unchanged from its HTML.
META = {
    'index.html': (
        'Вадим Владымцев — архитектор ИИ и автоматизации, CTO',
        'Я — Вадим Владымцев, Co-Founder Century | CTO StackLevel GROUP. Проектирую ИИ-системы, пишу код, руковожу разработкой и тренирую команды ICPC.'),
    'background/index.html': (
        'Путь, навыки и образование — Вадим Владымцев',
        'Мой путь в разработке и управлении: Century, АСПЗиЗ БГУИР, iTechArt и Teach IT. Тренерство ICPC, преподавание, повышение квалификации в МФТИ и НовГУ.'),
    'projects/index.html': (
        'Проекты и исследования — Вадим Владымцев',
        'Моя работа над Century, Belka и Multiverse. Руководство АСПЗиЗ, медицинский мониторинг и патент BY 24499 C1, телематика МАЗ × БГУИР.'),
    'context/index.html': (
        'Публикации, патент и учебные материалы — Вадим Владымцев',
        'Мои научные публикации, патент BY 24499 C1, курс C++, тренерство ICPC и бесплатные консультации GenAI.by. Канал «Кайдзен AI» и открытый код.'),
}
VOID = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}


class Node:
    def __init__(self, tag='', attrs=None):
        self.tag, self.attrs, self.children = tag, dict(attrs or []), []

    def all(self, tag=None):
        result = []
        for child in self.children:
            if isinstance(child, Node):
                if tag is None or child.tag == tag:
                    result.append(child)
                result.extend(child.all(tag))
        return result

    def first(self, tag):
        return next(iter(self.all(tag)), None)

    def by_id(self, name):
        return next((n for n in self.all() if n.attrs.get('id') == name), None)

    def text(self):
        if self.tag in ('script','style','svg','noscript') or self.attrs.get('aria-hidden') == 'true':
            return ''
        parts = []
        for child in self.children:
            parts.append(child.text() if isinstance(child, Node) else child)
        return re.sub(r'\s+', ' ', ' '.join(parts)).strip()


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(source)
        self.close()

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def ref(identifier):
    return {'@id': identifier}


def canonical(path):
    return BASE + path.removesuffix('index.html')


def metadata(doc, name):
    return next(n.attrs['content'] for n in doc.all('meta')
                if n.attrs.get('name', n.attrs.get('property')) == name)


def script_json(source):
    return json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', source, re.S)[1])


def markdown(node, url):
    if isinstance(node, str):
        return re.sub(r'\s+', ' ', node)
    tag, attrs = node.tag, node.attrs
    if tag in ('svg','script','style','noscript','nav') or attrs.get('aria-hidden') == 'true':
        return ''
    if tag == 'br':
        return ' '
    body = ''.join(markdown(c, url) for c in node.children)
    if re.fullmatch('h[1-6]', tag):
        return '\n\n' + '#' * int(tag[1]) + ' ' + body.strip() + '\n\n'
    if tag == 'summary':
        return '\n\n**' + body.strip() + '**\n\n'
    if tag in ('p','dd','dt'):
        return '\n\n' + body.strip() + '\n\n'
    if tag == 'li':
        return '\n- ' + body.strip() + '\n'
    if tag == 'a' and attrs.get('href'):
        href = urljoin(url, attrs['href'])
        headings = node.all('h2') + node.all('h3')
        if headings:
            h = headings[0]
            label = '#' * int(h.tag[1]) + ' ' + h.text()
            return body.replace(label, '#' * int(h.tag[1]) + ' [' + h.text() + '](' + href + ')', 1)
        return '[' + body.strip() + '](' + href + ') '
    if tag in ('span','time'):
        return ' ' + body.strip() + ' '
    if tag == 'img':
        return '\n\n![' + attrs.get('alt','') + '](' + urljoin(url,attrs.get('src','')) + ')\n\n'
    if tag in ('section','article','header','details','ul','ol','dl','div','figure'):
        return '\n' + body.strip() + '\n'
    return body


def title_description(path, doc):
    return META.get(path, (doc.first('title').text(), metadata(doc,'description')))


def replace_head(source, title, description, graph, path):
    head, body = source.split('</head>', 1)
    head = re.sub(r'<title>.*?</title>', lambda _: '<title>'+html.escape(title)+'</title>', head, count=1, flags=re.S)
    for key, value in [('description',description),('og:title',title),('twitter:title',title),
                       ('og:description',description),('twitter:description',description)]:
        pattern = r'<meta (name|property)="' + re.escape(key) + r'" content="[^"]*">'
        head, count = re.subn(pattern, lambda m: '<meta '+m[1]+'="'+key+'" content="'+html.escape(value,quote=True)+'">',head)
        if count != 1:
            raise ValueError('Expected one '+key+' in '+path)
    head = re.sub(r'<script type="application/ld\+json">.*?</script>',
                  lambda _: '<script type="application/ld+json">'+json.dumps(graph,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')+'</script>',
                  head, count=1, flags=re.S)
    # Replace only discovery links. All visible markup, assets and scripts remain unchanged.
    head = re.sub(r'<link rel="(?:icon|apple-touch-icon)"[^>]*>\s*', '', head)
    head = re.sub(r'<link rel="(?:alternate|describedby)"[^>]*type="(?:text/markdown|application/ld\+json)"[^>]*>\s*', '', head)
    head = re.sub(r'<meta name="twitter:url"[^>]*>\s*', '', head)
    links = [
        '<link rel="icon" href="/favicon.ico" sizes="16x16 32x32 48x48" type="image/x-icon">',
        '<link rel="icon" href="/favicon.svg" sizes="any" type="image/svg+xml">',
        '<link rel="apple-touch-icon" href="/apple-touch-icon.png" sizes="180x180">',
        '<link rel="alternate" type="text/markdown" href="/'+path+'.md">',
        '<link rel="describedby" type="application/ld+json" href="/person.jsonld">',
        '<meta name="twitter:url" content="'+canonical(path)+'">',
    ]
    head = head.rstrip() + '\n' + '\n'.join(links) + '\n'
    return head + '</head>' + body


def generate():
    sources = {p: (ROOT/p).read_text(encoding='utf-8') for p in PAGES}
    docs = {p: Document(s).root for p,s in sources.items()}
    profile = json.loads((ROOT/'person.jsonld').read_text(encoding='utf-8'))
    person = copy.deepcopy(next(n for n in profile['@graph'] if n.get('@type') == 'Person'))
    if person['jobTitle'] != ROLE or person['@id'] != PERSON_ID:
        raise ValueError('Unexpected personal identity or approved role')
    person['name'] = 'Вадим Владымцев'
    person['alternateName'] = ['Владымцев Вадим Денисович','Vadim Vladymtsev','Vladymtsev Vadim Denisovich','Vadimohka']
    person['givenName'], person['familyName'] = 'Вадим', 'Владымцев'
    person['description'] = ('Я — сооснователь Century и CTO StackLevel GROUP. Проектирую системы, '
                             'пишу код и организую разработку. Преподаю и тренирую команды ICPC.')
    person['hasCredential'] = [
        {
            '@type':'EducationalOccupationalCredential',
            'name':'Спортивное программирование для тренеров',
            'credentialCategory':'Повышение квалификации',
            'recognizedBy':{'@type':'CollegeOrUniversity','name':'МФТИ'},
            'url':BASE+'background/#mipt',
        },
        {
            '@type':'EducationalOccupationalCredential',
            'name':'Методика разработки программ ДПО инженерной направленности',
            'credentialCategory':'Повышение квалификации',
            'recognizedBy':{'@type':'CollegeOrUniversity',
                            'name':'Новгородский государственный университет имени Ярослава Мудрого',
                            'alternateName':'НовГУ'},
            'url':BASE+'background/#novsu',
        },
    ]
    organization = copy.deepcopy(next(n for n in profile['@graph'] if n.get('@type') == 'Organization'))
    website = {'@type':'WebSite','@id':BASE+'#website','url':BASE,'name':'Вадим Владымцев',
               'alternateName':'Vadimohka','inLanguage':'ru-RU','publisher':ref(PERSON_ID)}
    image = {'@type':'ImageObject','url':IMAGE,'width':1448,'height':1086}
    outputs, texts = {}, []
    for path, source in sources.items():
        doc, url = docs[path], canonical(path)
        title, description = title_description(path, doc)
        old_page = next(n for n in script_json(source)['@graph'] if n.get('@id') == url+'#webpage')
        page = {'@type':'WebPage','@id':url+'#webpage','url':url,'name':title,'description':description,
                'inLanguage':'ru-RU','isPartOf':ref(BASE+'#website'),'about':ref(PERSON_ID),
                'author':ref(PERSON_ID),'primaryImageOfPage':image,
                'dateModified':old_page['dateModified']}
        nodes = [page, person, organization, website]
        if path in ('index.html','background/index.html'):
            page['@type'] = 'ProfilePage'
            page['mainEntity'] = ref(PERSON_ID)
        elif path in ('projects/index.html','context/index.html'):
            page['@type'] = 'CollectionPage'
            listing = {'@type':'ItemList','@id':url+'#items','name':doc.first('h1').text(),'itemListElement':[]}
            page['mainEntity'] = ref(listing['@id'])
            if path == 'projects/index.html':
                keys = ['century','belka','multiverse','admissions','medical-monitoring',
                        'vehicle-telematics','territorial-platform','knowledge','ecommerce']
                entries = [(doc.by_id(k).first('h2').text(),url+'#'+k) for k in keys]
            else:
                articles = doc.first('main').all('article')
                entries = [(a.first('h2').text(),urljoin(url,a.first('h2').first('a').attrs['href'])) for a in articles]
            listing['numberOfItems'] = len(entries)
            listing['itemListElement'] = [{'@type':'ListItem','position':i,'name':name,'url':link}
                                         for i,(name,link) in enumerate(entries,1)]
            nodes.append(listing)
        else:
            article = {'@type':'Article','@id':url+'#article','url':url,'headline':doc.first('h1').text(),
                       'description':description,'inLanguage':'ru-RU','author':ref(PERSON_ID),
                       'publisher':ref(PERSON_ID),'mainEntityOfPage':ref(page['@id']),
                       'dateModified':page['dateModified'],'image':image,
                       'articleSection':[n.text() for n in doc.first('main').all('h2')]}
            page['mainEntity'] = ref(article['@id'])
            nodes.append(article)
        if path == 'context/index.html':
            paper = doc.by_id('heart-rate-paper')
            paper_text = paper.text()
            headline = re.search('«(Алгоритм.*?)»', paper_text)[1]
            publication = {'@type':'ScholarlyArticle','@id':url+'#heart-rate-publication',
                           'name':headline,'headline':headline,'url':paper.first('h2').first('a').attrs['href'],
                           'inLanguage':'ru','author':[{'@type':'Person','name':n} for n in
                           ['А. Н. Осипов','О. Ч. Ролич','А. П. Клюев']]+[ref(PERSON_ID)]+
                           [{'@type':'Person','name':n} for n in ['С. А. Мигалевич','И. О. Хазановский']]}
            patent = {'@type':'CreativeWork','@id':BASE+'projects/#medical-patent',
                      'url':BASE+'projects/#medical-patent','name':'Патент BY 24499 C1',
                      'identifier':'BY 24499 C1','contributor':ref(PERSON_ID)}
            page['mentions'] = [ref(publication['@id']),ref(patent['@id'])]
            nodes.extend([publication,patent])
        if path != 'index.html':
            crumb = {'@type':'BreadcrumbList','@id':url+'#breadcrumb','itemListElement':[
                {'@type':'ListItem','position':1,'name':'Главная','item':BASE},
                {'@type':'ListItem','position':2,'name':{'background/index.html':'Путь',
                    'projects/index.html':'Проекты','approach/index.html':'Подход',
                    'context/index.html':'Профили и материалы'}[path],'item':url}]}
            page['breadcrumb'] = ref(crumb['@id'])
            nodes.append(crumb)
        else:
            page['hasPart'] = [ref(BASE+s+'/#webpage') for s in ('background','projects','approach','context')]
        graph = {'@context':'https://schema.org','@graph':nodes}
        outputs[path] = replace_head(source,title,description,graph,path)
        if path == 'index.html':
            outputs['llm-profile.json'] = json.dumps(graph,ensure_ascii=False,separators=(',',':'))+'\n'
        main = markdown(doc.first('main'),url)
        main = re.sub(r'[ \t]+\n','\n',main)
        main = re.sub(r'\n{3,}','\n\n',main).strip()
        text = '['+title+']('+url+')\n\n'+main+'\n\n[Написать мне](mailto:vadimohkav@gmail.com)\n'
        outputs[path+'.md'] = text
        texts.append(text)
    outputs['person.jsonld'] = json.dumps({'@context':'https://schema.org','@graph':[person,organization]},ensure_ascii=False,separators=(',',':'))+'\n'
    outputs['llms-full.txt'] = '\n\n---\n\n'.join(texts)
    lines = ['# Вадим Владымцев','', '> '+ROLE+'. Проектирую системы, пишу код, организую разработку, преподаю и тренирую команды ICPC.',
             '', '## Обо мне, моём пути и работе','']
    for path in PAGES:
        title, description = title_description(path,docs[path])
        lines.append('- ['+title+']('+canonical(path)+'): '+description)
    lines += ['', '## Текстовые версии страниц','']
    for path in PAGES:
        title = title_description(path,docs[path])[0]
        lines.append('- ['+title+']('+BASE+path+'.md)')
    lines += ['', '## Дополнительные форматы','',
              '- [Полный текст](https://vadimohka.ru/llms-full.txt)',
              '- [Структурированный профиль](https://vadimohka.ru/llm-profile.json)',
              '- [Person](https://vadimohka.ru/person.jsonld)',
              '- [Карта сайта](https://vadimohka.ru/sitemap.xml)', '']
    outputs['llms.txt'] = '\n'.join(lines)
    # Use genuine page edit dates, not today's build time. Keep only canonical Russian pages.
    sitemap = ['<?xml version="1.0" encoding="UTF-8"?>',
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">']
    for path in PAGES:
        url = canonical(path)
        page = next(n for n in script_json(outputs[path])['@graph'] if n['@id'] == url+'#webpage')
        sitemap += ['  <url>','    <loc>'+url+'</loc>','    <lastmod>'+page['dateModified']+'</lastmod>']
        if path == 'index.html':
            sitemap += ['    <image:image><image:loc>'+IMAGE+'</image:loc></image:image>']
        sitemap += ['  </url>']
    outputs['sitemap.xml'] = '\n'.join(sitemap+['</urlset>',''])
    return outputs


def validate(outputs):
    robots = RobotFileParser()
    robots.parse((ROOT/'robots.txt').read_text().splitlines())
    for bot in ('Googlebot','Bingbot','Yandex','OAI-SearchBot','ChatGPT-User','PerplexityBot','Claude-SearchBot'):
        for path in PAGES + ['llms.txt','assets/hero-vadim-2026.webp','assets/studio.css']:
            if not robots.can_fetch(bot,canonical(path) if path in PAGES else BASE+path):
                raise ValueError('Blocked crawler: '+bot+' '+path)
    for path in PAGES:
        source = outputs[path]
        if source.split('</head>',1)[1] != (ROOT/path).read_text().split('</head>',1)[1]:
            raise ValueError('Visible content changed: '+path)
        graph = script_json(source)['@graph']
        ids = [n['@id'] for n in graph]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate JSON-LD identifiers: '+path)
        person = next(n for n in graph if n['@id'] == PERSON_ID)
        if person['jobTitle'] != ROLE or person['image'] != IMAGE:
            raise ValueError('Person mismatch: '+path)
        for n in graph:
            for item in n.get('itemListElement',[]):
                if item.get('position',0) < 1:
                    raise ValueError('Invalid list position')
        doc = Document(source).root
        md_links = [n for n in doc.all('link') if n.attrs.get('type') == 'text/markdown']
        if len(md_links) != 1 or md_links[0].attrs['href'] != '/'+path+'.md':
            raise ValueError('Wrong Markdown discovery link: '+path)
    for path, text in outputs.items():
        if not path.endswith('.html') and re.search(r'vadimohka\.com\b',text,re.I):
            raise ValueError('Unexpected English domain in '+path)
    ET.fromstring(outputs['sitemap.xml'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--write',action='store_true')
    mode.add_argument('--check',action='store_true')
    args = parser.parse_args()
    outputs = generate()
    validate(outputs)
    changed = [p for p,v in outputs.items() if not (ROOT/p).exists() or (ROOT/p).read_text(encoding='utf-8') != v]
    if args.write:
        for path in changed:
            (ROOT/path).parent.mkdir(parents=True,exist_ok=True)
            (ROOT/path).write_text(outputs[path],encoding='utf-8')
        print('Updated '+str(len(changed))+' files: '+', '.join(changed))
    elif changed:
        raise ValueError('Discovery files are stale; run python3 scripts/sync-discovery.py --write: '+', '.join(changed))
    else:
        print('SEO/GEO sync passed: five pages, consistent Person, ProfilePage/Article/collections, canonical links, faithful Markdown and crawler rules.')


if __name__ == '__main__':
    try:
        main()
    except (OSError,ValueError,KeyError,StopIteration,AttributeError) as exc:
        print(str(exc),file=sys.stderr)
        sys.exit(1)
