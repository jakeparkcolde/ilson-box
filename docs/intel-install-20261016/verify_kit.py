from pathlib import Path
import tempfile,zipfile,os,subprocess,json,importlib.util
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('u',ROOT/'tools/update.py');u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u)
with tempfile.TemporaryDirectory(prefix='ilson-intel-kit-') as tmp:
 t=Path(tmp)
 with zipfile.ZipFile(HERE/'ilson-intel-mac-20261016.zip') as z:z.extractall(t)
 kit=t/'ilson-intel-mac-20261016'
 subprocess.run(['shasum','-a','256','-c','SHA256SUMS'],cwd=kit,check=True,stdout=subprocess.DEVNULL)
 b=t/'bin';b.mkdir()
 for name,body in [('uname','case "$1" in -s) echo Darwin ;; -m) echo x86_64 ;; *) /usr/bin/uname "$@" ;; esac'),('sysctl','exit 1'),('sw_vers','echo 26.6.2')]:
  p=b/name;p.write_text('#!/bin/sh\n'+body+'\n');p.chmod(0o755)
 cli=t/'installed-cli';home=t/'box'
 env=dict(os.environ,ILSON_SRC=str(kit/'cli'),ILSON_CLI_DIR=str(cli),ILSON_BIN_DIR=str(b),ILSON_HOME=str(home),PATH=str(b)+':'+os.environ['PATH'])
 r=subprocess.run(['sh',str(kit/'install.sh'),'--sandbox'],env=env,text=True,capture_output=True,timeout=45)
 assert r.returncode==0,r.stdout+r.stderr
 assert 'Intel 64비트' in r.stdout
 assert (cli/'tools/update.py').is_file()
 assert (home/'state/sandbox').is_file()
 assert not (home/'state/setup-complete').exists()
 assert not list((home/'state').glob('enabled.*'))
 m=json.loads((kit/'release/release-2026.10.16.3.json').read_text());a=(kit/'release'/m['archive']).read_bytes()
 roots={'cli':cli,'box':home}
 u.apply(roots,m,a)
 assert (home/'lib/research/native.py').read_bytes()==(home/'packs/research/0.16.1/native.py').read_bytes()
 assert json.loads((home/'.updates/installed.json').read_text())['version']=='2026.10.16.3'
 assert (home/'state/sandbox').exists()
 print('PASS: ZIP checksums, Intel simulated fresh install, tools updater included, code-only release apply, research pack parity, no jobs or machine setup enabled')
HERE.joinpath('kit-verification.txt').write_text('PASS: ZIP checksum + Intel CPU/macOS 26.6.2 mocked sandbox fresh install + local release application + source/pack parity. No actual Intel hardware, third-party tool installation, authentication, or live LLM test performed.\n')
