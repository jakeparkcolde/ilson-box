"""Isolated local manager used only by the browser regression test."""
import importlib.util
import os
from pathlib import Path
import secrets
import shutil
import sys

ROOT=Path(__file__).resolve().parents[2]
LIB=ROOT/'template/lib';sys.path.insert(0,str(LIB))
import license as lic
home=Path(sys.argv[1])/'box';user=Path(sys.argv[1])/'user';user.mkdir()
shutil.copytree(ROOT/'template/web',home/'web')
(home/'state/web-admin').mkdir(parents=True)
(home/'state/setup-pending').touch()
(home/'vault').mkdir();(home/'vault/CONTEXT.md').write_text('# 회사\n- 회사명: (인터뷰에서 채움)\n')
(home/'launchd').mkdir();shutil.copy2(ROOT/'template/launchd/jobs.conf',home/'launchd/jobs.conf')
for name,value in [('token',secrets.token_urlsafe(32)),('instance',secrets.token_urlsafe(24))]:
    path=home/'state/web-admin'/name
    with os.fdopen(os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'w') as f:f.write(value)
lic.evaluate=lambda _: (True,'ACTIVE')
spec=importlib.util.spec_from_file_location('navigation_test_admin',LIB/'web-admin-server.py')
admin=importlib.util.module_from_spec(spec);spec.loader.exec_module(admin)
probe=admin.Probe(home,run=lambda _: (1,''),which=lambda _:None)
probe.jobs=lambda:set()
server=admin.Server(admin.Box(home,user_home=user,probe=probe),0)
print(server.server_port,flush=True)
try: server.serve_forever()
finally:
    server.server_close()
    if server.box._workspace is not None:server.box._workspace.close()
