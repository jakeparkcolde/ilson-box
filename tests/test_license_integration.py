"""License gates against isolated copies with an RFC test key, no real credentials."""
import importlib.util
import datetime
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
SEED=bytes.fromhex('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60')
PUBLIC='d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a'

class Integration(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.repo=self.root/'repo'; self.repo.mkdir()
        shutil.copy2(ROOT/'ilson',self.repo/'ilson')
        shutil.copytree(ROOT/'template',self.repo/'template',ignore=shutil.ignore_patterns('__pycache__'))
        p=self.repo/'template/lib/license.py'
        source,count=re.subn(r'^PUBLIC_KEYS\s*=.*$',f"PUBLIC_KEYS = {{1: bytes.fromhex('{PUBLIC}')}}",p.read_text(),flags=re.MULTILINE)
        if count != 1:
            raise AssertionError(f'expected one public key declaration, found {count}')
        source,count=re.subn(r"^API_URL\s*=.*$", "API_URL = 'https://127.0.0.1:1'", source, flags=re.MULTILINE)
        if count != 1:
            raise AssertionError(f'expected one API URL declaration, found {count}')
        p.write_text(source)
        spec=importlib.util.spec_from_file_location('fixture_license',p); self.license=importlib.util.module_from_spec(spec); spec.loader.exec_module(self.license)
        self.box=self.root/'box'; self.env={**os.environ,'HOME':str(self.root),'ILSON_HOME':str(self.box)}
    def command(self,*args):
        return subprocess.run(['bash',str(self.repo/'ilson'),*args],env=self.env,text=True,capture_output=True,timeout=15)
    def activate(self):
        now=int(time.time()); payload=struct.pack('>BB16sHBII',1,1,b't'*16,1,1,now-10,now+86400)
        serial=self.license.encode_serial(payload,SEED)
        ok,_=self.license.evaluate(self.box,serial,transport=lambda *_: (_ for _ in ()).throw(OSError('offline')))
        self.assertTrue(ok)
    def test_unlicensed_command_blocked_but_help_and_install_kit_allowed(self):
        result=self.command('course-kit')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('NO_LICENSE',result.stdout)
        self.assertFalse((self.box/'강의키트-20261109-v2').exists())
        kit=subprocess.run(['python3',str(self.repo/'template/lib/course-kit.py'),str(self.repo/'template/claude/skills/course-kit-20261109'),str(self.box)],env=self.env,capture_output=True,text=True)
        self.assertEqual(kit.returncode,0,kit.stderr)
        self.assertTrue((self.box/'강의키트-20261109-v2').is_dir())
        self.assertIn('사용법',self.command('--help').stdout)
    def test_issuer_creates_only_test_key_and_private_serial_in_temporary_home(self):
        issuer=ROOT/'server/license/issuer.py'
        def call(*args):
            return subprocess.run(['python3',str(issuer),*args],env=self.env,text=True,capture_output=True)
        init=call('init-key'); self.assertEqual(init.returncode,0,init.stderr)
        config=self.root/'.config/ilson-license'; key=config/'signing-key'
        self.assertEqual(key.stat().st_mode & 0o777,0o600)
        self.assertNotIn(key.read_text().strip(),init.stdout)
        now=datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
        out=config/'sample.serial'
        result=call('issue','--key',str(key),'--output',str(out),'--kid','1','--cohort','1',
                    '--plan','one-time','--issued',now.isoformat(),'--expires',(now+datetime.timedelta(days=3650)).isoformat())
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(out.stat().st_mode & 0o777,0o600)
        serial=out.read_text().strip(); self.assertNotIn(serial,result.stdout)
        self.license.PUBLIC_KEYS[1]=self.license.public_key(bytes.fromhex(key.read_text().strip()))
        self.assertEqual(self.license.parse_serial(serial)['plan'],1)
        self.assertNotEqual(call('init-key').returncode,0)
        # V2 short serial issue (--short) creates 0600 <output>.short without leaking either code to stdout.
        out_v2=config/'sample-v2.serial'
        res_v2=call('issue','--key',str(key),'--output',str(out_v2),'--kid','1','--cohort','1',
                    '--plan','one-time','--issued',now.isoformat(),'--expires','never','--short')
        self.assertEqual(res_v2.returncode,0,res_v2.stderr)
        short_file=config/'sample-v2.serial.short'
        self.assertTrue(short_file.is_file())
        self.assertEqual(out_v2.stat().st_mode & 0o777,0o600)
        self.assertEqual(short_file.stat().st_mode & 0o777,0o600)
        v1_v2=out_v2.read_text().strip(); short_code=short_file.read_text().strip()
        self.assertTrue(self.license.is_short_serial(short_code))
        self.assertNotIn(v1_v2,res_v2.stdout); self.assertNotIn(short_code,res_v2.stdout)
        # Reject --short-output outside ~/.config/ilson-license/ without creating V1 output.
        outside_v1=config/'sample-v2-bad.serial'; outside_short=self.root/'outside.short'
        bad_res=call('issue','--key',str(key),'--output',str(outside_v1),'--kid','1','--cohort','1',
                     '--plan','one-time','--issued',now.isoformat(),'--expires','never','--short','--short-output',str(outside_short))
        self.assertNotEqual(bad_res.returncode,0)
        self.assertFalse(outside_v1.exists()); self.assertFalse(outside_short.exists())
        # Reject case-insensitive collision on macOS APFS without creating V1 output.
        case_v1=config/'sample-case.serial'; case_short=config/'SAMPLE-CASE.SERIAL'
        case_res=call('issue','--key',str(key),'--output',str(case_v1),'--kid','1','--cohort','1',
                      '--plan','one-time','--issued',now.isoformat(),'--expires','never','--short','--short-output',str(case_short))
        self.assertNotEqual(case_res.returncode,0)
        self.assertFalse(case_v1.exists())
        # Rollback newly created V1 file if creating the short file fails midway.
        import sys
        rollback_v1=config/'sample-rollback.serial'; rollback_short=config/'sample-rollback.serial.short'
        rollback_code=(
            "import importlib.util, os, sys; "
            f"spec=importlib.util.spec_from_file_location('issuer_mod',{str(issuer)!r}); "
            "m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); "
            "orig_open=os.open; "
            f"os.open=lambda p,*a,**k: (_ for _ in ()).throw(OSError('disk full')) if str(p)=={str(rollback_short)!r} else orig_open(p,*a,**k); "
            f"sys.argv=['issuer.py','issue','--key',{str(key)!r},'--output',{str(rollback_v1)!r},'--kid','1','--cohort','1',"
            f"'--plan','one-time','--issued',{now.isoformat()!r},'--expires','never','--short']; "
            "sys.exit(m.main())"
        )
        rb=subprocess.run([sys.executable,'-c',rollback_code],env=self.env,text=True,capture_output=True)
        self.assertNotEqual(rb.returncode,0)
        self.assertFalse(rollback_v1.exists()); self.assertFalse(rollback_short.exists())
        # Verify register --short-file produces deterministic sealed_serial for idempotent retries with same request_id.
        self.assertEqual(call('init-admin').returncode,0)
        import ssl, threading, json
        from http.server import BaseHTTPRequestHandler, HTTPServer
        cert=self.root/'cert.pem'; cert_key=self.root/'key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(cert_key),'-out',str(cert),
                        '-days','1','-subj','/CN=127.0.0.1','-addext','subjectAltName=IP:127.0.0.1'],
                       check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        captured=[]; seen={}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                captured.append(body)
                rid=body['request_id']
                comparable={k:v for k,v in body.items() if k!='nonce'}
                if rid in seen and seen[rid]!=comparable:
                    resp=json.dumps({'nonce':body['nonce'],'status':'conflict'}).encode()
                    self.send_response(409)
                else:
                    seen[rid]=comparable
                    resp=json.dumps({'nonce':body['nonce'],'status':'ok'}).encode()
                    self.send_response(200)
                self.send_header('Content-Length',str(len(resp))); self.end_headers(); self.wfile.write(resp)
        server=HTTPServer(('127.0.0.1',0),Handler)
        ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(cert,cert_key)
        server.socket=ctx.wrap_socket(server.socket,server_side=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        self.addCleanup(lambda: (server.shutdown(),thread.join(),server.server_close()))
        reg_env={**self.env,'SSL_CERT_FILE':str(cert)}
        req_id='a'*32
        for _ in range(2):
            reg=subprocess.run([sys.executable,str(issuer),'register','--server',f'https://127.0.0.1:{server.server_port}',
                                '--serial-file',str(out_v2),'--short-file',str(short_file),'--display-name','V2수강생',
                                '--request-id',req_id],
                               env=reg_env,text=True,capture_output=True)
            self.assertEqual(reg.returncode,0,reg.stderr)
        self.assertEqual(len(captured),2)
        self.assertEqual(captured[0]['short_code_hash'],self.license.short_code_hash(short_code))
        self.assertEqual(captured[0]['sealed_serial'],captured[1]['sealed_serial'])
        unsealed_v1,_=self.license.unseal_serial(short_code,captured[0]['sealed_serial'])
        self.assertEqual(unsealed_v1,v1_v2)
    def test_active_course_kit_preserves_user_file(self):
        self.activate(); kit=self.box/'강의키트-20261109-v2'; kit.mkdir()
        note=kit/'내 업무 소개.md'; note.write_text('개인 수정')
        result=self.command('course-kit')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(note.read_text(),'개인 수정')
        self.assertTrue((kit/'시작과_막힘_복구.md').is_file())
    def test_help_anywhere_never_executes_motion_research_or_nested_commands(self):
        for args in (('motion','-h'),('motion','영상 요청','--help'),('research','run','-h'),('people','add','--help')):
            with self.subTest(args=args):
                result=self.command(*args)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertIn('사용법:',result.stdout)
        self.assertFalse((self.box/'state/license').exists())
    def test_unlicensed_watchdog_suppresses_missed_job_alert(self):
        (self.box/'lib').mkdir(parents=True)
        (self.box/'state').mkdir()
        for f in ('license.py','watchdog.sh','common.sh'):
            shutil.copy2(self.repo/'template/lib'/f,self.box/'lib'/f)
        marker=self.box/'state/enabled.briefing'; marker.touch()
        old=time.time()-4*86400; os.utime(marker,(old,old))
        capture=self.root/'notify.txt'
        (self.box/'lib/notify.sh').write_text('#!/bin/sh\necho alert > "'+str(capture)+'"\n')
        result=subprocess.run(['bash',str(self.box/'lib/watchdog.sh')],env=self.env,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(capture.exists())
        self.assertFalse(list((self.box/'state').glob('alerted.briefing.*')))
    def test_unlicensed_scheduled_job_skips_and_logs(self):
        (self.box/'lib').mkdir(parents=True)
        for f in ('license.py','run-job.sh','common.sh'):
            shutil.copy2(self.repo/'template/lib'/f,self.box/'lib'/f)
        result=subprocess.run(['bash',str(self.box/'lib/run-job.sh'),'briefing'],env=self.env,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('skipped: license required',(self.box/'logs/briefing.log').read_text())
        self.assertFalse((self.box/'state/last-run.briefing').exists())

if __name__=='__main__': unittest.main()
