"""Shared source metadata and read-only resource contracts for the static site.

HTML remains the editorial source. The approved identity lives in data/profile.json;
person.jsonld and the discovery catalogs are generated outputs, never inputs.
This module uses only the Python standard library.
"""
import copy
import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE_SOURCE = ROOT / 'scripts/data/profile.json'
_PROFILE = json.loads(PROFILE_SOURCE.read_text(encoding='utf-8'))
_PERSON = next(node for node in _PROFILE['@graph'] if node.get('@type') == 'Person')

BASE = _PERSON['url']
ROLE = _PERSON['jobTitle']
PERSON_ID = _PERSON['@id']
IMAGE = _PERSON['image']
NAME = _PERSON['name']
CONTACT = _PERSON['email']
LANGUAGE = 'ru'
SCHEMA_LANGUAGE = 'ru-RU'


def load_profile():
    """Return an independent copy of the approved profile for each generation."""
    return copy.deepcopy(_PROFILE)


def canonical(path):
    return BASE + path.removesuffix('index.html')


def lite_path(path):
    return 'llm/' + path


def index_path(path):
    return path.removesuffix('index.html') + 'llms.txt'


@dataclass(frozen=True)
class PageSpec:
    path: str
    label: str
    breadcrumb: str
    schema_type: str

    @property
    def markdown_path(self):
        return self.path + '.md'


# One page inventory supplies navigation, schema selection and all text formats.
# Titles, descriptions, dates and visible text are read from the approved HTML.
PAGE_SPECS = (
    PageSpec('index.html', 'Главная', 'Главная', 'ProfilePage'),
    PageSpec('background/index.html', 'Путь и образование', 'Путь', 'ProfilePage'),
    PageSpec('projects/index.html', 'Проекты', 'Проекты', 'CollectionPage'),
    PageSpec('approach/index.html', 'Подход', 'Подход', 'WebPage'),
    PageSpec('context/index.html', 'Публикации и материалы', 'Профили и материалы', 'CollectionPage'),
)
PAGES = [page.path for page in PAGE_SPECS]
PAGE_BY_PATH = {page.path: page for page in PAGE_SPECS}

CATALOG_PATHS = {
    'ai-catalog': '.well-known/ai-catalog.json',
    'ard': '.well-known/ard.json',
}
CATALOG_MEDIA_TYPES = {
    'ai-catalog': 'application/ai-catalog+json',
    'ard': 'application/json',
}
ARD_CONTEXT = 'https://agenticresourcediscovery.org/context/v1'


def catalog_links():
    """HTML discovery links shared by primary and text-only pages."""
    return [
        '<link rel="' + relation + '" type="' + CATALOG_MEDIA_TYPES[relation]
        + '" href="/' + path + '">'
        for relation, path in CATALOG_PATHS.items()
    ]


def catalog_index_lines():
    """Optional links to the two independent catalog projections."""
    return [
        '- [AI Catalog — каталог материалов](' + BASE + CATALOG_PATHS['ai-catalog'] + ')',
        '- [ARD — каталог материалов для поиска](' + BASE + CATALOG_PATHS['ard'] + ')',
    ]


@dataclass(frozen=True)
class ResourceSpec:
    identifier: str
    path: str
    media_type: str
    source_page: str | None
    display_name: str | None
    description: str | None
    tags: tuple[str, ...]
    representative_queries: tuple[str, ...]
    # Internal classification; it is not an invented AI Catalog/ARD property.
    interaction: str = 'read'

    def entry(self, page_metadata):
        """Project a resource into the common catalog fields.

        Page resources use their HTML metadata, so edits do not leave a second
        independent description behind. Only actual published documents belong
        here; human expertise and project plans are not callable capabilities.
        """
        if self.source_page is not None:
            title, description = page_metadata[self.source_page]
        else:
            title, description = self.display_name, self.description
        return {
            'identifier': self.identifier,
            'displayName': title,
            'type': self.media_type,
            'url': BASE + self.path,
            'description': description,
            'tags': list(self.tags),
        }


# Preserve the identifiers from the reviewed four-resource prototype. Additional
# entries describe the existing background and publications pages, not new tools.
RESOURCES = (
    ResourceSpec(
        'urn:air:vadimohka.ru:profile:vadim-vladymtsev',
        'person.jsonld', 'application/ld+json', None,
        NAME + ' — публичный профиль',
        'Структурированные сведения об авторе: текущие роли, области работы, публичные профили и контакт.',
        ('profile', LANGUAGE),
        ('Кто такой ' + NAME + ' и как с ним связаться?',
         'Какие роли и области экспертизы указаны в профиле Вадима Владымцева?'),
    ),
    ResourceSpec(
        'urn:air:vadimohka.ru:docs:index',
        'llms.txt', 'text/plain', None,
        'Навигация по материалам Вадима Владымцева',
        'Индекс официальных материалов на русском языке: биография, проекты, подход, публикации и ссылки на текстовые версии.',
        ('documentation', 'portfolio', LANGUAGE),
        ('Где найти официальные материалы Вадима Владымцева о его работе?',
         'Где прочитать биографию, проекты и публикации Вадима Владымцева?'),
    ),
    ResourceSpec(
        'urn:air:vadimohka.ru:docs:background',
        PAGE_BY_PATH['background/index.html'].markdown_path, 'text/markdown', 'background/index.html',
        None, None, ('background', 'education', LANGUAGE),
        ('Какой профессиональный путь прошёл Вадим Владымцев?',
         'Какое образование и преподавательский опыт указаны у Вадима Владымцева?'),
    ),
    ResourceSpec(
        'urn:air:vadimohka.ru:docs:projects',
        PAGE_BY_PATH['projects/index.html'].markdown_path, 'text/markdown', 'projects/index.html',
        None, None, ('projects', LANGUAGE),
        ('Над какими проектами работает Вадим Владымцев?',
         'Что такое Century, Belka и Multiverse и на какой стадии эти проекты?'),
    ),
    ResourceSpec(
        'urn:air:vadimohka.ru:docs:ai-automation-approach',
        PAGE_BY_PATH['approach/index.html'].markdown_path, 'text/markdown', 'approach/index.html',
        None, None, ('ai', 'automation', LANGUAGE),
        ('Как Вадим Владымцев подходит к внедрению ИИ в бизнес-процессы?',
         'С чего начинать автоматизацию процесса и как оценивать её результат?'),
    ),
    ResourceSpec(
        'urn:air:vadimohka.ru:docs:context',
        PAGE_BY_PATH['context/index.html'].markdown_path, 'text/markdown', 'context/index.html',
        None, None, ('publications', 'teaching', LANGUAGE),
        ('Где найти научные публикации и учебные материалы Вадима Владымцева?',
         'Какие публичные материалы связаны с преподаванием и исследованиями Вадима Владымцева?'),
    ),
)


def build_catalogs(page_metadata):
    """Return separate AI Catalog and ARD documents from the same resources."""
    entries = [resource.entry(page_metadata) for resource in RESOURCES]
    ard_entries = []
    for resource, entry in zip(RESOURCES, entries):
        ard_entry = {'@context': ARD_CONTEXT, **copy.deepcopy(entry)}
        ard_entry['representativeQueries'] = list(resource.representative_queries)
        ard_entries.append(ard_entry)
    return {
        CATALOG_PATHS['ai-catalog']: {
            'specVersion': '1.0',
            'host': {'displayName': NAME, 'documentationUrl': BASE + 'llms.txt'},
            'entries': entries,
        },
        CATALOG_PATHS['ard']: {'entries': ard_entries},
    }
