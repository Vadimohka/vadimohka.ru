#!/usr/bin/env python3
"""Generate public text-only HTML alternatives and page-scoped llms indexes.

Called by sync-discovery.py. Only the existing <main> content is used. All
readers receive the same documents; there is no User-Agent detection.
"""
import html
import re
from urllib.parse import urljoin, urlsplit

LABELS = {
    'index.html': 'Главная',
    'background/index.html': 'Путь и образование',
    'projects/index.html': 'Проекты',
    'approach/index.html': 'Подход',
    'context/index.html': 'Публикации и материалы',
}
SKIP = {'script', 'style', 'noscript', 'nav', 'svg', 'img', 'figure', 'button'}
KEEP = {'h1','h2','h3','h4','h5','h6','p','a','strong','em','b','i','code','pre',
        'blockquote','ul','ol','li','dl','dt','dd','table','thead','tbody','tfoot',
        'tr','th','td','caption','small','sup','sub','section','article','header',
        'footer','div','span','time','br','hr'}
BLOCKS = {'h1','h2','h3','h4','h5','h6','p','li','dt','dd','summary','blockquote'}
STYLE = '''body{font:18px/1.65 system-ui,sans-serif;max-width:74ch;margin:auto;padding:24px;color:#1d1d1f;background:#fff;overflow-wrap:anywhere}nav{display:flex;flex-wrap:wrap;gap:8px 20px;margin-bottom:28px}nav a[aria-current]{font-weight:700}a{color:#0759ad}h1,h2,h3{line-height:1.2;letter-spacing:-.02em}h1{font-size:clamp(2rem,6vw,3rem)}h2{margin-top:2em}h3{margin-top:1.5em}section,article{margin:1.5em 0}dl{margin:1em 0}dt{font-weight:650}dd{margin:0 0 1em}li{margin:.35em 0}footer{margin-top:3em;border-top:1px solid #ddd;padding-top:1em}pre,table{max-width:100%;overflow:auto}pre{white-space:pre-wrap}.formats{font-size:.9em}'''


def lite_path(path):
    return 'llm/' + path


def index_path(path):
    return path.removesuffix('index.html') + 'llms.txt'


def visible(node):
    return node.tag not in SKIP and node.attrs.get('aria-hidden') != 'true' and 'hidden' not in node.attrs


def plain(node):
    if isinstance(node, str):
        return node
    if not visible(node):
        return ''
    if node.tag == 'br':
        return ' '
    return ' '.join(plain(child) for child in node.children)


def normalized(value):
    return re.sub(r'\s+', ' ', value).strip()


def content_blocks(node):
    """Text assertions ignore whitespace and decorative SVG/image content."""
    if isinstance(node, str) or not visible(node):
        return []
    result = [normalized(plain(node))] if node.tag in BLOCKS else []
    for child in node.children:
        result.extend(content_blocks(child))
    return [value for value in result if value]


def render(node, canonical):
    if isinstance(node, str):
        return html.escape(node, quote=False)
    if not visible(node):
        return ''
    content = ''.join(render(child, canonical) for child in node.children)
    tag = node.tag
    if tag == 'details':
        tag = 'section'
    elif tag == 'summary':
        tag, content = 'p', '<strong>' + content + '</strong>'
    if tag not in KEEP:
        return content
    attrs = {key: node.attrs[key] for key in ('id','lang','title','datetime','colspan','rowspan') if key in node.attrs}
    if tag == 'a' and node.attrs.get('href'):
        href = urljoin(canonical, node.attrs['href'])
        if urlsplit(href).scheme in ('https','http','mailto'):
            attrs['href'] = href
    encoded = ''.join(' ' + key + '="' + html.escape(value, quote=True) + '"' for key,value in attrs.items())
    if tag in ('br','hr'):
        return '<' + tag + encoded + '>'
    return '<' + tag + encoded + '>' + content + '</' + tag + '>\n'


def generate(docs, outputs, base):
    result = {}
    for path, doc in docs.items():
        canonical = base + path.removesuffix('index.html')
        md_url = base + path + '.md'
        llm_url = base + lite_path(path).removesuffix('index.html')
        title = doc.first('title').text()
        main = doc.first('main')
        if main is None:
            raise ValueError('Missing main content: ' + path)
        nav = ' '.join('<a href="/' + lite_path(p).removesuffix('index.html') + '"' +
                       (' aria-current="page"' if p == path else '') + '>' + label + '</a>'
                       for p,label in LABELS.items())
        result[lite_path(path)] = (
            '<!doctype html>\n<html lang="ru">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            '<meta name="robots" content="noindex,follow">\n'
            '<meta name="author" content="Вадим Владымцев">\n'
            '<title>' + html.escape(title) + ' — текстовая версия</title>\n'
            '<link rel="canonical" href="' + canonical + '">\n'
            '<link rel="alternate" type="text/markdown" href="' + md_url + '">\n'
            '<link rel="describedby" type="text/plain" href="' + base + index_path(path) + '">\n'
            '<link rel="icon" type="image/svg+xml" href="/favicon.svg">\n'
            '<style>' + STYLE + '</style>\n</head>\n<body>\n'
            '<nav aria-label="Текстовые страницы">' + nav + '</nav>\n'
            '<p class="formats"><a href="' + canonical + '">Обычная версия</a> · '
            '<a href="' + md_url + '">Markdown</a></p>\n'
            '<main>' + render(main, canonical) + '</main>\n'
            '<footer><a href="mailto:vadimohkav@gmail.com">Написать мне</a> · '
            '<a href="/llms.txt">Оглавление</a></footer>\n</body>\n</html>\n'
        )
        # Root llms.txt is generated by sync-discovery; subpaths describe their own page.
        if path != 'index.html':
            lead = main.first('header')
            lead = next((n for n in lead.all('p') if 'lead' in n.attrs.get('class', '').split()), None) if lead else None
            summary = (lead.text() if lead else LABELS[path])
            result[index_path(path)] = (
                '# ' + LABELS[path] + ' — Вадим Владымцев\n\n> ' + summary + '\n\n'
                '## Страница\n\n- [Полный текст в Markdown](' + md_url + ')\n'
                '- [Текстовая HTML-версия](' + llm_url + ')\n'
                '- [Основная страница](' + canonical + ')\n\n'
                '## Optional\n\n- [Все разделы](https://vadimohka.ru/llms.txt)\n'
                '- [Профиль](https://vadimohka.ru/person.jsonld)\n'
            )
    return result


def validate(docs, outputs, base, parse):
    """Fail generation if an alternative drops content or changes link targets."""
    for path, doc in docs.items():
        text = outputs[lite_path(path)]
        alternate = parse(text).root
        body = alternate.first('main')
        canonical = base + path.removesuffix('index.html')
        if normalized(plain(doc.first('main'))) != normalized(plain(body)):
            raise ValueError('Text-only content mismatch: ' + path)
        if any(n.tag in ('script','details','img') for n in alternate.all()):
            raise ValueError('Non-text dependency: ' + path)
        links = [n.attrs for n in alternate.all('link')]
        if sum(n.get('rel') == 'canonical' and n.get('href') == canonical for n in links) != 1:
            raise ValueError('Wrong text-only canonical: ' + path)
        if not any(n.attrs.get('name') == 'robots' and n.attrs.get('content') == 'noindex,follow' for n in alternate.all('meta')):
            raise ValueError('Missing alternative indexing guard: ' + path)
        source_links = {urljoin(canonical,n.attrs['href']) for n in doc.first('main').all('a') if n.attrs.get('href')}
        # Main navigation is intentionally omitted in the reading representation.
        nav_links = {urljoin(canonical,n.attrs['href']) for nav in doc.first('main').all('nav') for n in nav.all('a') if n.attrs.get('href')}
        actual = {n.attrs['href'] for n in body.all('a') if n.attrs.get('href')}
        if not (source_links - nav_links) <= actual:
            raise ValueError('Missing source links: ' + path)
