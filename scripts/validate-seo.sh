#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
test -f .nojekyll
for file in index.html projects/index.html context/index.html approach/index.html en/index.html robots.txt sitemap.xml llms.txt llms-full.txt llm-profile.json person.jsonld; do test -f "$file"; done
grep -Fqx 'User-agent: *' robots.txt
grep -Fqx 'Allow: /' robots.txt
grep -Fqx 'Sitemap: https://vadimohka.ru/sitemap.xml' robots.txt
! grep -Eq '/en/' sitemap.xml llms.txt llms-full.txt index.html.md
jq -e . llm-profile.json >/dev/null
jq -e . person.jsonld >/dev/null
xmllint --noout sitemap.xml
grep -Fq 'https://vadimohka.ru/' sitemap.xml
! grep -Fq 'https://vadimohka.ru/en/' sitemap.xml
for file in index.html projects/index.html context/index.html approach/index.html; do
  test "$(grep -c 'rel=\"canonical\"' "$file")" -eq 1
  grep -Fq 'content="index,follow' "$file"
done
for file in en/index.html en/projects/index.html en/context/index.html en/approach/index.html; do
  grep -Fq 'noindex' "$file"
  grep -Fq 'https://vadimohka.com/' "$file"
done
echo 'SEO validation passed'
