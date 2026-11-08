"""Offline release-asset integrity and 6.4 updater path preflight; not an upgrade test."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import zipfile

EXPECTED_ZIP = 'bd197daebcf11c63f58b4c145cc582e5e7556f8f6ea64eed3c8a1f72b8083106'
EXPECTED_MANIFEST = '67c8fadb3304d0fbd9c239717f48b222ccda247a9aeff2292e8dbd167d623ebb'

def digest(data):
    return hashlib.sha256(data).hexdigest()

def verify(manifest_path, archive_path):
    manifest = json.loads(manifest_path.read_bytes())
    data = archive_path.read_bytes()
    if digest(data) != manifest['archive_sha256']:
        raise ValueError('archive digest mismatch')
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('duplicate archive member')
        expected = set()
        for item in manifest['files']:
            key = item['area'] + '/' + item['path']
            if key in expected or digest(archive.read(key)) != item['sha256']:
                raise ValueError('duplicate entry or digest mismatch: ' + key)
            expected.add(key)
        if set(names) != expected:
            raise ValueError('archive and manifest member sets differ')
    return manifest

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--baseline', type=Path, required=True, help='directory containing downloaded 6.4 assets')
    p.add_argument('--candidate-manifest', type=Path)
    p.add_argument('--candidate-archive', type=Path)
    args = p.parse_args()
    if bool(args.candidate_manifest) != bool(args.candidate_archive):
        p.error('provide both candidate files')
    manifest_path = args.baseline / 'latest-v2.json'
    zip_path = args.baseline / 'ilson-box-2026.11.6.4.zip'
    if digest(manifest_path.read_bytes()) != EXPECTED_MANIFEST or digest(zip_path.read_bytes()) != EXPECTED_ZIP:
        raise ValueError('6.4 GitHub asset digest mismatch')
    baseline = verify(manifest_path, zip_path)
    if baseline['version'] != '2026.11.6.4':
        raise ValueError('unexpected baseline version')
    print('6.4 integrity OK:', len(baseline['files']), 'members')
    if args.candidate_manifest:
        candidate = verify(args.candidate_manifest, args.candidate_archive)
        with zipfile.ZipFile(zip_path) as archive, tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'old_updater.py'
            path.write_bytes(archive.read('cli/tools/update.py'))
            spec = importlib.util.spec_from_file_location('old_updater_64', path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            rejected = [f['area'] + '/' + f['path'] for f in candidate['files'] if not module.allowed(f['area'], f['path'])]
        if rejected:
            raise ValueError('6.4 updater rejects: ' + ', '.join(rejected))
        print('candidate integrity and old allowed() OK:', len(candidate['files']), 'members')
    print('Preflight only: install, upgrade, data preservation and launchd remain untested.')

if __name__ == '__main__':
    main()
