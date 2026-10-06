#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
python3 scripts/validate-seo.py
python3 scripts/validate-profile.py
python3 scripts/validate-approach.py
python3 scripts/validate-english.py
python3 scripts/sync-discovery.py --check
