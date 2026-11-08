"""Isolated 6.4 installer rehearsal. No actual user launchd, credentials or network."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SCRATCH = ROOT.parent / 'box-release-20261108-scratch'
RUN = Path(tempfile.mkdtemp(prefix='install-64-rehearsal-', dir=SCRATCH))
ASSET = SCRATCH / '6.4/ilson-box-2026.11.6.4.zip'
ACTUAL = Path.home()

def snapshot(path):
    if not path.exists() and not path.is_symlink(): return {'missing': True}
    rows = {}
    def record(p):
        rel = str(p.relative_to(path))
        st = p.lstat()
        if stat.S_ISLNK(st.st_mode): rows[rel] = ['link', os.readlink(p)]
        elif stat.S_ISREG(st.st_mode): rows[rel] = ['file', hashlib.sha256(p.read_bytes()).hexdigest(), stat.S_IMODE(st.st_mode)]
        elif stat.S_ISDIR(st.st_mode): rows[rel] = ['dir', stat.S_IMODE(st.st_mode)]
        else: rows[rel] = ['other', stat.S_IFMT(st.st_mode)]
    record(path)
    if path.is_dir() and not path.is_symlink():
        for parent, dirs, files in os.walk(path, followlinks=False):
            for name in sorted(dirs + files): record(Path(parent) / name)
    return rows

def main():
    for part in ('home', 'tmp', 'bin', 'source'): (RUN / part).mkdir(parents=True)
    home, tmp, box, source = RUN/'home', RUN/'tmp', RUN/'home/ilson', RUN/'source'
    for name, path in [('HOME',home),('ILSON_HOME',box),('TMPDIR',tmp)]:
        resolved = path.resolve()
        if not resolved.is_relative_to(RUN.resolve()): raise SystemExit('unsafe ' + name)
        print(name + '=' + str(resolved), flush=True)
    print('Protected actual ~/ilson and ~/Library/LaunchAgents will be hashed before and after.', flush=True)
    protected = [ACTUAL/'ilson', ACTUAL/'Library/LaunchAgents']
    before = {str(p):snapshot(p) for p in protected}
    (RUN/'protected-before.json').write_text(json.dumps(before, sort_keys=True))
    tarpath = RUN/'source-2e6fd52.tar'
    with tarpath.open('wb') as f:
        subprocess.run(['git','archive','2e6fd52'], cwd=ROOT, stdout=f, check=True)
    with tarfile.open(tarpath) as archive:
        for item in archive.getmembers():
            if not (source / item.name).resolve().is_relative_to(source.resolve()) or not (item.isfile() or item.isdir()):
                raise ValueError('unsafe source archive member')
        archive.extractall(source)
    with zipfile.ZipFile(ASSET) as archive:
        for item in archive.infolist():
            if item.filename.startswith('cli/') and not item.is_dir():
                dest = source / item.filename.removeprefix('cli/')
                if not dest.resolve().is_relative_to(source.resolve()): raise ValueError('archive path')
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(archive.read(item))
    code = r'''#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
 const char *n=strrchr(argv[0],'/'); n=n?n+1:argv[0];
 const char *p=getenv("ILSON_SHIM_LOG"); FILE *f=p?fopen(p,"a"):NULL;
 if(f){fprintf(f,"%s\n",n);fclose(f);}
 if(!strcmp(n,"curl")||!strcmp(n,"brew")||!strcmp(n,"sudo")||!strcmp(n,"security")) return 1;
 return 0;
}'''
    (RUN/'shim.c').write_text(code)
    subprocess.run(['/usr/bin/cc',str(RUN/'shim.c'),'-o',str(RUN/'bin/shim')],check=True)
    for name in ('launchctl','osascript','open','crontab','security','brew','sudo','claude','curl'):
        os.link(RUN/'bin/shim',RUN/'bin'/name)
    env = {'HOME':str(home), 'ILSON_HOME':str(box), 'TMPDIR':str(tmp), 'ILSON_SRC':str(source),
           'PATH':str(RUN/'bin')+':/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin',
           'ILSON_SHIM_LOG':str(RUN/'shim.log'), 'LANG':'en_US.UTF-8'}
    try:
        with (RUN/'install.log').open('w') as log:
            result = subprocess.run(['/bin/sh',str(source/'install.sh'),'--sandbox'],env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,timeout=180)
        print('Installer exit:',result.returncode, flush=True)
        print('Installed CLI:', (home/'.ilson-cli/ilson').is_file(), 'Box common:', (box/'lib/common.sh').is_file(), 'sandbox:', (box/'state/sandbox').is_file(), flush=True)
    finally:
        after = {str(p):snapshot(p) for p in protected}
        (RUN/'protected-after.json').write_text(json.dumps(after, sort_keys=True))
        print('Protected paths unchanged:', before == after, flush=True)
    if before != after: raise SystemExit('protected path change detected; investigate')
    if result.returncode: raise SystemExit(result.returncode)

if __name__ == '__main__': main()
