"""Prepare verified Git objects only. Publishing remains a separate explicit step."""
import base64
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
OUT = Path('/tmp/approved-site-release')
OUT.mkdir(exist_ok=True)
BASE_TREE = '2ad4f993a3ee5157007784d6276cb9d878c00378'
IMAGE_BLOB = '7c9a1a3b9b00bbbb8ee20b899e309e2b6195a672'
EXPECTED = json.loads((ROOT/'scripts/approved-release-manifest.json').read_text())

def api(path, data=None):
    req = Request('https://api.github.com/repos/' + os.environ['GH_REPOSITORY'] + path,
        data=None if data is None else json.dumps(data).encode(),
        headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'Accept': 'application/vnd.github+json',
                 'Content-Type': 'application/json', 'X-GitHub-Api-Version': '2022-11-28'})
    with urlopen(req, timeout=30) as response:
        return json.load(response)

image = base64.b64decode(api('/git/blobs/' + IMAGE_BLOB)['content'])
(ROOT/'assets/hero-vadim-2026.webp').write_bytes(image)
runpy.run_path(str(ROOT/'scripts/apply-approved-site-update.py'), run_name='__main__')
checks = subprocess.run(['bash', 'scripts/validate-seo.sh'], text=True, capture_output=True)
(OUT/'checks.txt').write_text(checks.stdout + checks.stderr)
print(checks.stdout + checks.stderr)
actual = {}
for name in EXPECTED:
    src = ROOT/name
    dest = OUT/'candidate'/name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src,dest)
    actual[name] = hashlib.sha256(src.read_bytes()).hexdigest()
errors = [name for name in EXPECTED if actual[name] != EXPECTED[name]]
manifest = {'verified': not errors and checks.returncode == 0, 'mismatches': errors, 'sha256': actual}
if manifest['verified']:
    entries = []
    for name in EXPECTED:
        entry = {'path': name, 'mode': '100755' if name.endswith('.sh') else '100644', 'type': 'blob'}
        if name.endswith('.webp'): entry['sha'] = IMAGE_BLOB
        else: entry['content'] = (ROOT/name).read_text()
        entries.append(entry)
    manifest['tree_sha'] = api('/git/trees', {'base_tree': BASE_TREE, 'tree': entries})['sha']
(OUT/'release-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(manifest,indent=2))
if not manifest['verified']: raise SystemExit('Candidate verification failed; no release tree created')
