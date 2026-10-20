from pathlib import Path
import hashlib,shutil,zipfile
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
kit=OUT/'ilson-intel-mac-20261016'
if kit.exists():shutil.rmtree(kit)
kit.mkdir()
shutil.copytree(ROOT/'template',kit/'cli/template',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
(kit/'cli/tools').mkdir()
for src,dest in [(ROOT/'ilson',kit/'cli/ilson'),(ROOT/'README.md',kit/'cli/README.md'),(ROOT/'tools/update.py',kit/'cli/tools/update.py'),(ROOT/'install.sh',kit/'install.sh'),(OUT/'install-intel.command',kit/'install-intel.command'),(OUT/'README-KO.txt',kit/'README-KO.txt')]:shutil.copy2(src,dest)
shutil.copytree(OUT/'release',kit/'release')
(kit/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(kit).as_posix()+'\n' for p in sorted(kit.rglob('*')) if p.is_file()))
archive=OUT/(kit.name+'.zip')
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
 for p in sorted(kit.rglob('*')):
  if p.is_file():z.write(p,Path(kit.name)/p.relative_to(kit))
(OUT/(archive.name+'.sha256')).write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n')
print(archive,archive.stat().st_size)
