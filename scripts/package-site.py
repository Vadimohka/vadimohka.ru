#!/usr/bin/env python3
"""Copy the public allowlist into dist for Pages, without running validation.

The existing builder owns public_files(). Importing that module only defines
its inventory and functions; this entrypoint never calls build() or validators.
Only the Python standard library is required.
"""
import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def package():
    spec = importlib.util.spec_from_file_location('publication_inventory', ROOT / 'scripts/build-site.py')
    inventory = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inventory)
    files = inventory.public_files()
    output = ROOT / 'dist'
    if output.is_symlink():
        raise ValueError('The publication directory cannot be a symbolic link')
    with tempfile.TemporaryDirectory(prefix='.pages-staging-', dir=ROOT) as staging_name:
        staging = Path(staging_name)
        for path in sorted(files):
            source = ROOT / path
            if source.resolve(strict=True) != source:
                raise ValueError('Published paths cannot contain symbolic links: ' + path)
            destination = staging / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        if output.exists():
            shutil.rmtree(output)
        os.replace(staging, output)
    print(f'Packaged {len(files)} static files in dist.')


if __name__ == '__main__':
    try:
        package()
    except (OSError, ValueError) as error:
        print('Packaging failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
