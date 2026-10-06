from pathlib import Path
import re, json, html
ROOT=Path(__file__).resolve().parents[1]
BASE='https://vadimohka.ru/'
ROLE='Co-Founder Century | CTO StackLevel GROUP'
TITLE='Вадим Владымцев — '+ROLE
DESC='Вадим Владымцев — сооснователь Century и CTO StackLevel GROUP. Архитектура корпоративных ИИ-систем, LLM, RAG, автоматизация процессов и безопасная работа с данными.'
IMAGE='assets/hero-vadim-2026.webp'
PAGES=['index.html','projects/index.html','background/index.html','approach/index.html','context/index.html']
def jdump(o):return json.dumps(o,ensure_ascii=False,separators=(',',':'))
def setmeta(t,k,v):
 return re.sub(r'(<meta (?:name|property)="'+re.escape(k)+r'" content=")[^"]*(">)',lambda m:m[1]+html.escape(v,quote=True)+m[2],t)
def settitle(t,v):return re.sub(r'<title>.*?</title>','<title>'+html.escape(v)+'</title>',t)
for name in ('llm-profile.json','person.jsonld'):
 d=json.loads((ROOT/name).read_text())
 for n in d['@graph']:
  if n['@type']=='Person':
   n['jobTitle']=ROLE;n['image']=BASE+IMAGE
   n['description']='Сооснователь Century и технический директор StackLevel GROUP. Отвечает за архитектуру и разработку платформы Century. Специализация: языковые модели, автоматизация процессов, корпоративные данные и безопасность. Ранее преподавал и готовил команды к ICPC в БГУИР.'
  if n['@type']=='WebSite':n['description']=DESC
  if n['@type']=='WebPage':
   n['name']=TITLE;n['description']=DESC;n['dateModified']='2026-10-06'
   n['primaryImageOfPage']={'@type':'ImageObject','url':BASE+IMAGE,'width':1448,'height':1086}
 (ROOT/name).write_text(jdump(d)+'\n')
for name in PAGES:
 t=(ROOT/name).read_text()
 # The approved composite is shown once, without the old silhouette or overlay.
 if name=='index.html':
  t=settitle(t,TITLE)
  for k in ('description','og:description','twitter:description'):t=setmeta(t,k,DESC)
  for k in ('og:title','twitter:title'):t=setmeta(t,k,TITLE)
  t=t.replace('Технический директор (CTO) · StackLevel Group',ROLE).replace('CTO · StackLevel Group',ROLE)
  t=t.replace('Технический директор StackLevel Group. Отвечаю', 'Сооснователь Century и технический директор StackLevel GROUP. Отвечаю')
  t=t.replace('<dd>Технический директор (CTO)</dd>', '<dd>'+ROLE+'</dd>')
  t=re.sub(r'<figure class="hero-portrait".*?</figure>', '<figure class="hero-portrait"><img class="hero-img" src="/'+IMAGE+'" width="1448" height="1086" alt="Вадим Владымцев. Технологии должны работать на людей. Вадим." loading="eager" decoding="async" fetchpriority="high"></figure>',t,flags=re.S)
  t=re.sub(r'<link rel="preload" as="image"[^>]*>', '<link rel="preload" as="image" href="/'+IMAGE+'" type="image/webp" fetchpriority="high">',t)
  profile=json.loads((ROOT/'llm-profile.json').read_text())
  t=re.sub(r'<script type="application/ld\+json">.*?</script>', '<script type="application/ld+json">'+jdump(profile)+'</script>',t,flags=re.S)
  t=re.sub(r'href="/assets/portrait.css[^"]*"','href="/assets/portrait.css?v=approved-20261006"',t)
 if name=='projects/index.html':
  t=t.replace('Технический директор (CTO), StackLevel Group',ROLE)
  t=t.replace('Как технический директор StackLevel Group, отвечаю', 'Как сооснователь Century и технический директор StackLevel GROUP, отвечаю')
 if name=='background/index.html':
  t=t.replace('Сейчас я технический директор StackLevel Group.', 'Сейчас я сооснователь Century и технический директор StackLevel GROUP.')
  t=t.replace('<h3>Технический директор (CTO)</h3>','<h3>'+ROLE+'</h3>')
  t=t.replace('Веду техническую работу над Century — платформой', 'Как сооснователь Century, веду работу над платформой')
 if name=='context/index.html':
  t=t.replace('Моя текущая должность — технический директор (CTO) StackLevel Group.', 'Моя должность: '+ROLE+'.')
  t=t.replace('Корпоративная ИИ-платформа с ассистентами, рабочими сценариями, доступом к данным, интеграциями и аудитом.', 'Платформа, которую я развиваю как сооснователь: ИИ-ассистенты, рабочие сценарии, корпоративные данные, интеграции и аудит.')
 # All previews use the same new image, hosted on the Russian domain.
 for k in ('og:image','twitter:image'):t=setmeta(t,k,BASE+IMAGE)
 t=setmeta(t,'og:image:type','image/webp');t=setmeta(t,'og:image:width','1448');t=setmeta(t,'og:image:height','1086')
 (ROOT/name).write_text(t)
(ROOT/'assets/portrait.css').write_text('''/* Approved image: full native dimensions, no old mask or caption overlay. */
.home .hero-portrait { display: block; min-width: 0; mask-image: none; -webkit-mask-image: none; }
.home .hero-img { display: block; width: 100%; height: auto; aspect-ratio: 1448 / 1086; object-fit: contain; mix-blend-mode: normal; mask-image: none; -webkit-mask-image: none; }
.home .hero-copy .eyebrow { text-transform: none; letter-spacing: .025em; font-size: 13px; line-height: 1.6; }
@media (max-width: 767px) { .home .hero-portrait { width: min(100%, 580px); margin-inline: auto; } }
''')
# Keep the exact uploaded Markdown as the edit source. Its metadata is not body copy.
source=(ROOT/'scripts/content/approach.md').read_text()
(ROOT/'scripts/content').mkdir(parents=True,exist_ok=True)
(ROOT/'scripts/content/approach.md').write_text(source)
body,metadata=source.split('## Метаданные страницы',1)
body=body.rstrip().removesuffix('---').rstrip()
atitle=re.search(r'\*\*Title:\*\*\s*(.*)',metadata)[1]
adesc=re.search(r'\*\*Description:\*\*\s*(.*)',metadata)[1]
blocks=re.split(r'\n\s*\n',body)

def inline(txt):
 parts=[];last=0
 for m in re.finditer(r'\[([^\]]+)\]\(([^)]+)\)',txt):
  parts.append(html.escape(txt[last:m.start()]));url=m[2]
  cls='button' if url.startswith('mailto:') else 'text-link'
  parts.append('<a class="'+cls+'" href="'+html.escape(url,quote=True)+'">'+html.escape(m[1])+'</a>');last=m.end()
 parts.append(html.escape(txt[last:]));return ''.join(parts)
ids=['kaizen','implementation','project-process','debt-example','principles','skills','contact']
content=['<main id="main-content" tabindex="-1" class="approach-page">','<header class="page-heading wrap approach-heading">']
section_index=0;in_section=False;sub_open=False
for b in blocks:
 b=b.strip()
 if not b:continue
 if b.startswith('# '): content.append('<h1>'+inline(b[2:])+'</h1>')
 elif b.startswith('## '):
  if sub_open:content.append('</div>');sub_open=False
  if in_section:content.append('</section>')
  else:content.append('</header><div class="approach-content wrap">')
  sid=ids[section_index];section_index+=1;in_section=True
  content.append('<section class="approach-section" id="'+sid+'" aria-labelledby="'+sid+'-heading">\n<h2 id="'+sid+'-heading">'+inline(b[3:])+'</h2>')
 elif b.startswith('### '):
  if sub_open:content.append('</div>')
  content.append('<div class="approach-topic"><h3>'+inline(b[4:])+'</h3>');sub_open=True
 else:
  css=' class="lead"' if not in_section and not b.startswith('[') else ''
  content.append('<p'+css+'>'+inline(b)+'</p>')
if sub_open:content.append('</div>')
content+=['</section>','</div>','</main>']
t=(ROOT/'approach/index.html').read_text()
t=re.sub(r'<main.*?</section>\s*(?=<footer)', '\n'.join(content)+'\n', t, flags=re.S)
t=t.replace('class="inside"','class="inside approach"')
t=settitle(t,atitle)
for k in ('description','og:description','twitter:description'):t=setmeta(t,k,adesc)
for k in ('og:title','twitter:title'):t=setmeta(t,k,atitle)
d=json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>',t,re.S)[1])
for n in d['@graph']:
 if n['@type']=='WebPage':
  n['name']=atitle;n['description']=adesc;n['dateModified']='2026-10-06'
 if n['@type']=='BreadcrumbList':n['itemListElement'][-1]['name']='Подход к внедрению ИИ и автоматизации'
t=re.sub(r'<script type="application/ld\+json">.*?</script>','<script type="application/ld+json">'+jdump(d)+'</script>',t,flags=re.S)
t=t.replace('<link rel="stylesheet" href="/assets/studio.css">','<link rel="stylesheet" href="/assets/studio.css">\n<link rel="stylesheet" href="/assets/approach.css?v=20261006">')
(ROOT/'approach/index.html').write_text(t)
(ROOT/'assets/approach.css').write_text('''/* Long-form author copy; deliberately scoped to the approach page. */
.approach-heading { max-width: 832px; padding-block: 68px 56px; }
.approach-heading h1 { font-size: clamp(36px, 4.2vw, 54px); line-height: 1.14; max-width: 760px; }
.approach-heading .lead { max-width: none; font-size: 19px; line-height: 1.75; margin-top: 28px; }
.approach-heading p:last-child { margin-top: 28px; }
.approach-content { max-width: 832px; padding-bottom: 36px; }
.approach-section { border-top: 1px solid var(--line); padding-block: 44px 48px; scroll-margin-top: 28px; }
.approach-section h2 { font-size: clamp(28px, 3vw, 35px); font-weight: 500; line-height: 1.25; margin-bottom: 24px; }
.approach-section p { font-size: 17px; line-height: 1.8; }
.approach-section p + p { margin-top: 20px; }
.approach-topic { margin-top: 32px; }
.approach-topic h3 { font-size: 21px; font-weight: 500; line-height: 1.45; margin-bottom: 14px; }
#debt-example { background: var(--paper); padding: 32px; margin-block: 0 12px; border: 0; border-radius: 8px; }
#contact.approach-section { padding-bottom: 38px; }
.approach-section a:not(.button) { display: inline; min-height: 0; text-decoration: underline; text-underline-offset: 4px; }
@media (max-width: 767px) {
 .approach-heading { padding-block: 32px 38px; }
 .approach-heading .lead { font-size: 17px; margin-top: 22px; }
 .approach-section { padding-block: 32px; }
 .approach-section p { font-size: 16px; line-height: 1.75; }
 .approach-topic h3 { font-size: 20px; }
 #debt-example { padding: 24px 20px; }
}
''')
for name in ('index.html.md','llms-full.txt','llms.txt'):
 t=(ROOT/name).read_text()
 t=t.replace('CTO StackLevel Group и архитектор ИИ',ROLE)
 t=t.replace('Вадим Владымцев — технический директор (CTO) StackLevel Group и архитектор корпоративных ИИ-систем.', 'Вадим Владымцев — '+ROLE+'. Сооснователь Century и технический директор StackLevel GROUP.')
 t=t.replace('Персональный сайт технического директора (CTO) StackLevel Group и архитектора корпоративных ИИ-систем.', 'Персональный сайт Вадима Владымцева — '+ROLE+'.')
 t=t.replace('в качестве CTO StackLevel Group.', 'как сооснователя Century и CTO StackLevel GROUP.')
 t=t.replace('StackLevel Group: технический директор (CTO).', 'Century: сооснователь. StackLevel GROUP: технический директор (CTO).')
 t=t.replace('[Подход](https://vadimohka.ru/approach/): этапы работы и технологии.', '[Подход](https://vadimohka.ru/approach/): кайдзен, два подхода к внедрению, AI core, этапы проекта и пример работы с задолженностями.')
 (ROOT/name).write_text(t)
# Image entry remains local; approach was materially updated today.
t=(ROOT/'sitemap.xml').read_text().replace('assets/vadim-vladymtsev-2026.jpg', IMAGE)
t=re.sub(r'(<loc>https://vadimohka.ru/approach/</loc><lastmod>)[^<]+',r'\g<1>2026-10-06',t)
(ROOT/'sitemap.xml').write_text(t)
print('Text and layout edits prepared.')

p=ROOT/'context/index.html'
t=p.read_text()
t=t.replace('Компания, в которой я работаю техническим директором (CTO).','Моя должность: Co-Founder Century | CTO StackLevel GROUP.')
t=t.replace('Корпоративная ИИ-платформа: ассистенты, автоматизация процессов, документы, базы данных и интеграции с контролем доступа и аудитом.','Сооснователь платформы Century. В ней объединяем ассистентов, автоматизацию процессов, документы, базы данных и интеграции с контролем доступа и аудитом.')
p.write_text(t)
