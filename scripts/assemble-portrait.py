"""Reassemble the user-approved image; never modify a branch or publish a page."""
import base64
import hashlib
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

BLOBS = [
    '5d95ff2ca2e683fe496fc97e45e5509007ae211d',
    'a9de5291fe6d5b84908d0e16c861960a55e3cbb4',
    'dc0a1256faee259789ec43d73a51e88e269777c4',
    '9aec8963d02ed0492aa2afd15599d95f74d263cc',
    'e11b7301301e7d83c0a193330c5997276769ecb2',
    '47111264d9abdbfef7721d1e14238670a5b52e09',
    'b8862138f80c08e713ab3db918ce369feff6f2f5',
    'c6a633cc51714fbc8a3ffc876d07008b02b46294',
    '738fa09e463b1db7789738532cc2ddede041ff32',
]
EXPECTED = '7861caaa5608ecbc2bcebc4760fd30c79eeb08f035bfee48456f6428db87ff13'
PATCHES = {}
out = Path('_portrait-transfer')
out.mkdir(exist_ok=True)

def api(path, data=None):
    payload = None if data is None else json.dumps(data).encode()
    req = Request('https://api.github.com/repos/' + os.environ['GH_REPOSITORY'] + path,
                  data=payload, headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                  'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json',
                  'X-GitHub-Api-Version': '2022-11-28'})
    with urlopen(req, timeout=30) as response:
        return json.load(response)

parts = []
for index, sha in enumerate(BLOBS):
    blob = api('/git/blobs/' + sha)
    raw = base64.b64decode(blob['content'])
    (out / ('chunk-%d.bin' % index)).write_bytes(raw)
    encoded = base64.b64encode(raw).decode()
    for start, stop, replacement in sorted(PATCHES.get(str(index), []), reverse=True):
        encoded = encoded[:start] + replacement + encoded[stop:]
    parts.append(base64.b64decode(encoded, validate=True))
image = b''.join(parts)
checksum = hashlib.sha256(image).hexdigest()
manifest = {'bytes': len(image), 'sha256': checksum, 'expected': EXPECTED, 'verified': checksum == EXPECTED}
if manifest['verified']:
    (out / 'hero-vadim-2026.webp').write_bytes(image)
    manifest['blob_sha'] = api('/git/blobs', {'encoding': 'base64', 'content': base64.b64encode(image).decode()})['sha']
(out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps(manifest, indent=2))
