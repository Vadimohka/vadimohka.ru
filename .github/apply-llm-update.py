from pathlib import Path
import re
import shutil
ROOT = Path(__file__).resolve().parents[1]
shutil.copyfile(ROOT / '.github/llm-pages.py', ROOT / 'scripts/llm-pages.py')
path = ROOT / 'background/index.html'
s = path.read_text()
old = '<article class="timeline-row" id="itechart"><p class="timeline-date">Обучение и адаптация</p>'
assert s.count(old) == 1
s = s.replace(old, '<article class="timeline-row" id="itechart"><p class="timeline-date">2021</p>')
path.write_text(s)
path = ROOT / 'scripts/sync-discovery.py'
s = path.read_text()
s = s.replace('import re\n', 'import re\nimport runpy\n', 1)
s = s.replace("VOID = {'area'", "LLM_PAGES = runpy.run_path(str(ROOT / 'scripts/llm-pages.py'))\nVOID = {'area'", 1)
needle = "    head = re.sub(r'<meta name=\"twitter:url\"[^>]*>\\s*', '', head)"
assert needle in s
s = s.replace(needle, "    head = re.sub(r'<link rel=\"alternate\" type=\"text/html\" title=\"Текстовая версия\"[^>]*>\\s*', '', head)\n    head = re.sub(r'<link rel=\"describedby\" type=\"text/plain\"[^>]*>\\s*', '', head)\n"+needle)
needle = "        '<link rel=\"alternate\" type=\"text/markdown\" href=\"/'+path+'.md\">',"
assert needle in s
s = s.replace(needle, needle + "\n        '<link rel=\"alternate\" type=\"text/html\" title=\"Текстовая версия\" href=\"/'+LLM_PAGES['lite_path'](path).removesuffix('index.html')+'\">',\n        '<link rel=\"describedby\" type=\"text/plain\" href=\"/'+LLM_PAGES['index_path'](path)+'\">',")
start = s.index("    lines = ['# Вадим Владымцев'")
end = s.index("    # Use genuine page edit dates",start)
s = s[:start] + '''    lines = ['# Вадим Владымцев','', '> '+ROLE+'. Проектирую системы, пишу код, организую разработку, преподаю и тренирую команды ICPC.',
             '', '## Страницы в Markdown','']
    for path in PAGES:
        title, description = title_description(path,docs[path])
        lines.append('- ['+title+']('+BASE+path+'.md): '+description)
    lines += ['', '## Текстовые HTML-версии','']
    for path in PAGES:
        title = title_description(path,docs[path])[0]
        lines.append('- ['+title+']('+BASE+LLM_PAGES['lite_path'](path).removesuffix('index.html')+')')
    lines += ['', '## Optional','',
              '- [Полный текст](https://vadimohka.ru/llms-full.txt)',
              '- [Структурированный профиль](https://vadimohka.ru/llm-profile.json)',
              '- [Person](https://vadimohka.ru/person.jsonld)',
              '- [Карта сайта](https://vadimohka.ru/sitemap.xml)', '']
    outputs['llms.txt'] = '\\n'.join(lines)
''' + s[end:]
s = s.replace("    return outputs\n\n\ndef validate(outputs):", "    outputs.update(LLM_PAGES['generate'](docs, outputs, BASE))\n    LLM_PAGES['validate'](docs, outputs, BASE, Document)\n    return outputs\n\n\ndef validate(outputs):",1)
s = s.replace("PAGES + ['llms.txt','assets/hero-vadim-2026.webp','assets/studio.css']", "PAGES + list(outputs) + ['llms.txt','assets/hero-vadim-2026.webp','assets/studio.css']",1)
s = s.replace('faithful Markdown and crawler rules.', 'faithful Markdown, five text-only HTML pages, page indexes and crawler rules.')
path.write_text(s)
