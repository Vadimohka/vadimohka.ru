#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

required_files=(
  ".nojekyll"
  "index.html"
  "en/index.html"
  "robots.txt"
  "sitemap.xml"
  "llms.txt"
  "llm-profile.json"
  "person.jsonld"
  "index.html.md"
  "en/index.html.md"
)

for file in "${required_files[@]}"; do
  if [[ ! -f "$file" ]]; then
    echo "::error::Missing required file: $file"
    exit 1
  fi
done

for bot in "*" "OAI-SearchBot" "GPTBot" "YandexAdditionalBot"; do
  if ! grep -Fqx "User-agent: $bot" robots.txt; then
    echo "::error::robots.txt is missing User-agent block for '$bot'"
    exit 1
  fi
done

if ! grep -Fqx "Sitemap: https://vadimohka.ru/sitemap.xml" robots.txt; then
  echo "::error::robots.txt is missing the sitemap directive"
  exit 1
fi

if grep -Eq 'User-agent: .* (Allow|Disallow|Sitemap):' robots.txt; then
  echo "::error::robots.txt contains multiple directives on one line"
  exit 1
fi

jq -e . llm-profile.json >/dev/null
jq -e . person.jsonld >/dev/null

xmllint --noout sitemap.xml

expected_sitemap_urls=(
  "https://vadimohka.ru/"
  "https://vadimohka.ru/en/"
  "https://vadimohka.ru/llms.txt"
  "https://vadimohka.ru/llm-profile.json"
  "https://vadimohka.ru/person.jsonld"
  "https://vadimohka.ru/index.html.md"
  "https://vadimohka.ru/en/index.html.md"
)

for url in "${expected_sitemap_urls[@]}"; do
  if ! grep -Fq "<loc>$url</loc>" sitemap.xml; then
    echo "::error::sitemap.xml is missing URL: $url"
    exit 1
  fi
done

while IFS= read -r url; do
  path="${url#https://vadimohka.ru}"
  local_path="${path#/}"

  if [[ -z "$local_path" ]]; then
    local_path="index.html"
  elif [[ "$local_path" == */ ]]; then
    local_path="${local_path}index.html"
  fi

  if [[ ! -f "$local_path" ]]; then
    echo "::error::sitemap.xml URL does not map to a local file: $url -> $local_path"
    exit 1
  fi
done < <(
  grep -oE '<loc>https://vadimohka\.ru[^<]*</loc>' sitemap.xml \
    | sed -E 's#<loc>([^<]+)</loc>#\1#'
)

for html in index.html en/index.html; do
  if ! grep -q '<script type="application/ld+json">' "$html"; then
    echo "::error::$html is missing JSON-LD script block"
    exit 1
  fi

  for schema_type in "WebSite" "WebPage" "Person" "ProfilePage"; do
    if ! grep -q "\"@type\": \"$schema_type\"" "$html"; then
      echo "::error::$html JSON-LD is missing @type=$schema_type"
      exit 1
    fi
  done

  for machine_readable_file in "/llms.txt" "/person.jsonld" "/llm-profile.json"; do
    if ! grep -Fq "$machine_readable_file" "$html"; then
      echo "::error::$html is missing machine-readable link: $machine_readable_file"
      exit 1
    fi
  done
done

for link in \
  "https://vadimohka.ru/" \
  "https://vadimohka.ru/en/" \
  "https://vadimohka.ru/person.jsonld" \
  "https://vadimohka.ru/llm-profile.json" \
  "https://vadimohka.ru/index.html.md" \
  "https://vadimohka.ru/en/index.html.md" \
  "https://vadimohka.ru/sitemap.xml" \
  "https://vadimohka.ru/robots.txt"
do
  if ! grep -Fq "$link" llms.txt; then
    echo "::error::llms.txt is missing link: $link"
    exit 1
  fi
done

ru_year="$(grep -oE '© [0-9]{4}' index.html | head -n 1 | awk '{print $2}')"
en_year="$(grep -oE '© [0-9]{4}' en/index.html | head -n 1 | awk '{print $2}')"

if [[ -z "$ru_year" || -z "$en_year" ]]; then
  echo "::error::Could not extract footer years from both pages"
  exit 1
fi

if [[ "$ru_year" != "$en_year" ]]; then
  echo "::error::Footer year mismatch: ru=$ru_year en=$en_year"
  exit 1
fi

echo "AEO/SEO validation passed."
