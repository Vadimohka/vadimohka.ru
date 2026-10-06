"""One-off, reviewable content edit. Run from the site root; not shipped with the site."""
from pathlib import Path
import re

root = Path.cwd()
path = root / 'background/index.html'
source = path.read_text(encoding='utf-8')
assert 'id="itechart"' not in source and 'id="novsu"' not in source

def section(name):
    match = re.search(r'<section class="timeline wrap" id="'+re.escape(name)+r'">.*?</section>', source, re.S)
    assert match, name
    return match.group()

def rows(text):
    return re.findall(r'<article class="timeline-row"[^>]*>.*?</article>', text, re.S)

def row_id(row):
    match = re.search(r'<article[^>]* id="([^"]+)"', row)
    return match[1] if match else None

industry = section('industry')
academia = section('academia')
education = section('education')
all_rows = rows(industry) + rows(academia)
by_id = {row_id(row): row for row in all_rows}
current_ids = ['stacklevel', 'icpc', 'rozum', 'consultations', 'research', 'startlab']
current = '<section class="timeline wrap" id="current"><h2>Сейчас</h2>\n' + '\n'.join(by_id[k] for k in current_ids) + '\n</section>\n'
past_work = [r for r in rows(industry) if row_id(r) not in current_ids]
itechart = ('<article class="timeline-row" id="itechart"><p class="timeline-date">Обучение и адаптация</p>'
            '<div><p class="eyebrow">iTechArt</p><h3>Student’s Lab Coordinator</h3>'
            '<p>Координировал обучение и адаптацию начинающих специалистов, помогал новым сотрудникам включаться в работу. '
            'Представлял компанию и участвовал в маркетинговых задачах.</p></div></article>')
insert_at = next(i for i,r in enumerate(past_work) if row_id(r) == 'teach-it') + 1
past_work.insert(insert_at, itechart)
new_industry = '<section class="timeline wrap" id="industry"><h2>Предыдущая работа и проектные роли</h2>\n' + '\n'.join(past_work) + '\n</section>'
past_academia = [r for r in rows(academia) if row_id(r) not in current_ids]
new_academia = '<section class="timeline wrap" id="academia"><h2>Преподавание и образовательные проекты</h2>\n' + '\n'.join(past_academia) + '\n</section>'
source = source.replace(industry, current + new_industry, 1).replace(academia, new_academia, 1)
source = source.replace('<a href="#industry">Работа</a>', '<a href="#current">Сейчас</a><a href="#industry">Предыдущая работа</a>', 1)
# Preserve existing qualification wording, dates, IDs and descriptions.
edu_rows = rows(education)
assert len(edu_rows) == 3
mipt = next(r for r in edu_rows if 'id="mipt"' in r)
masters = next(r for r in edu_rows if '<h3>Магистр</h3>' in r)
bachelors = next(r for r in edu_rows if '<h3>Бакалавр</h3>' in r)
novsu = ('<article class="timeline-row" id="novsu"><p class="timeline-date">Повышение квалификации</p>'
         '<div><p class="eyebrow">НовГУ</p><h3>Методика разработки программ ДПО инженерной направленности</h3>'
         '<p>Прошёл обучение по программе повышения квалификации в Новгородском государственном университете имени Ярослава Мудрого.</p>'
         '<a class="text-link" href="https://dpo.novsu.ru/services/kursy/programmy-povysheniya-kvalifikatsii/metodika-razrabotki-programm-dpo-inzhenernoy-napravlennosti/" '
         'target="_blank" rel="noopener noreferrer">О программе <span aria-hidden="true">↗</span></a></div></article>')
new_education = '<section class="timeline wrap" id="education"><h2>Образование и повышение квалификации</h2>\n' + '\n'.join([masters,mipt,novsu,bachelors]) + '\n</section>'
source = source.replace(education, new_education, 1)
path.write_text(source, encoding='utf-8')
# Change the requested product destination in public page sources only.
for rel in ['index.html','background/index.html','projects/index.html','approach/index.html','context/index.html']:
    p = root / rel
    text = p.read_text(encoding='utf-8')
    text = text.replace('https://century-ai.ru', 'https://century-ai.by')
    if rel == 'context/index.html':
        old = 'БГУИР и повышение квалификации в МФТИ по программе «Спортивное программирование для тренеров».'
        new = 'Учился в БГУИР, прошёл повышение квалификации в МФТИ и НовГУ.'
        assert old in text
        text = text.replace(old, new, 1)
    p.write_text(text, encoding='utf-8')
# Maintain the existing source of truth for metadata and credentials.
p = root / 'scripts/sync-discovery.py'
text = p.read_text(encoding='utf-8')
old = 'Мой путь в разработке и управлении: Century, АСПЗиЗ БГУИР и Teach IT. Архитектура систем, подготовка So Stuffy к ICPC, преподавание и обучение в МФТИ.'
new = 'Мой путь в разработке и управлении: Century, АСПЗиЗ БГУИР, iTechArt и Teach IT. Тренерство ICPC, преподавание, повышение квалификации в МФТИ и НовГУ.'
assert old in text
text = text.replace(old,new,1)
start = text.index("    person['hasCredential'] = {")
end = text.index('    organization = ',start)
text = text[:start] + '''    person['hasCredential'] = [
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
''' + text[end:]
p.write_text(text,encoding='utf-8')
