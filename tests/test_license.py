import importlib.util
import json
import os
from pathlib import Path
import struct
import ssl
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('license_test_module',ROOT/'template/lib/license.py')
lic=importlib.util.module_from_spec(spec)
spec.loader.exec_module(lic)
SEED=bytes.fromhex('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60')
PUBLIC=bytes.fromhex('d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a')
SIGNATURE=bytes.fromhex('e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155' '5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b')

class LicenseTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name)/'box'
        self.old=lic.PUBLIC_KEYS.copy(); lic.PUBLIC_KEYS.clear(); lic.PUBLIC_KEYS[1]=PUBLIC
        self.addCleanup(lambda: (lic.PUBLIC_KEYS.clear(),lic.PUBLIC_KEYS.update(self.old)))
        self.now=int(__import__('time').time())
        self.payload=struct.pack('>BB16sHBII',1,1,b'a'*16,1,2,self.now-10000,self.now+365*86400)
        self.serial=lic.encode_serial(self.payload,SEED)
    def offline(self,*_):
        raise OSError('offline')

    @unittest.skipIf(os.name == 'nt', 'POSIX Box compatibility')
    def test_box_home_symlink_keeps_existing_posix_behavior(self):
        actual = Path(self.tmp.name) / 'actual-box'
        actual.mkdir()
        alias = Path(self.tmp.name) / 'box-alias'
        alias.symlink_to(actual, target_is_directory=True)
        self.assertEqual(lic.private_dir(alias), alias / 'state/license')
    def active(self,*_):
        return {'status':'active','server_time':self.current,'paid_until':self.current+86400}
    def test_https_client_checks_nonce_and_online_revocation(self):
        cert=Path(self.tmp.name)/'cert.pem'; key=Path(self.tmp.name)/'key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),
                        '-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost'],
                       check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        state={'status':'active','time':self.now}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                response=json.dumps({'nonce':body['nonce'],'status':state['status'],'server_time':state['time']}).encode()
                self.send_response(200 if state['status']=='active' else 403)
                self.send_header('Content-Length',str(len(response))); self.end_headers(); self.wfile.write(response)
        server=HTTPServer(('127.0.0.1',0),Handler)
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(cert,key)
        server.socket=context.wrap_socket(server.socket,server_side=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(lambda: (server.shutdown(),thread.join(),server.server_close()))
        endpoint=f'https://localhost:{server.server_port}'
        def transport(action,serial,device): return lic.request(action,serial,device,url=endpoint)
        trusted=lambda: ssl.create_default_context(cafile=str(cert))
        with patch('ssl._create_default_https_context', side_effect=trusted):
            self.assertTrue(lic.evaluate(self.home,self.serial,now=self.now,transport=transport)[0])
            state.update(status='revoked',time=self.now+86400)
            self.assertEqual(lic.evaluate(self.home,now=self.now+86400,transport=transport),(False,'REVOKED'))
    def test_updater_allows_both_distributed_license_files(self):
        updater_spec=importlib.util.spec_from_file_location('license_updater',ROOT/'tools/update.py')
        updater=importlib.util.module_from_spec(updater_spec); updater_spec.loader.exec_module(updater)
        self.assertTrue(updater.allowed('cli','template/lib/license.py'))
        self.assertTrue(updater.allowed('box','lib/license.py'))
        self.assertFalse(updater.allowed('box','state/license/serial'))
    def test_rfc_vector_and_tamper(self):
        self.assertEqual(lic.public_key(SEED),PUBLIC)
        self.assertEqual(lic.sign(SEED,b''),SIGNATURE)
        self.assertTrue(lic.verify(PUBLIC,b'',SIGNATURE))
        self.assertFalse(lic.verify(PUBLIC,b'x',SIGNATURE))
        self.assertFalse(lic.verify(bytes(32),b'',bytes(64)))
    def test_rfc_second_vector(self):
        seed=bytes.fromhex('4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb')
        public=bytes.fromhex('3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c')
        signature=bytes.fromhex('92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da'
                                '085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00')
        self.assertEqual(lic.public_key(seed),public)
        self.assertEqual(lic.sign(seed,b'\x72'),signature)
        self.assertTrue(lic.verify(public,b'\x72',signature))
    def test_python_serial_is_accepted_by_node_server(self):
        env={**os.environ,'ILSON_PUBLIC_KEY_1':PUBLIC.hex()}
        js="const h=require(process.argv[1]);const x=h.serialData(process.argv[2]);process.stdout.write(JSON.stringify(x))"
        proc=subprocess.run(['node','-e',js,str(ROOT/'server/license/api/v1/[action].js'),self.serial],env=env,capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['id'],lic.parse_serial(self.serial,self.now)['id'])
    def test_serial_framing_normalization_and_rejection(self):
        self.assertEqual(len(self.serial),184)
        self.assertEqual(lic.parse_serial(self.serial.lower().replace('-', ' \n'),self.now)['cohort'],1)
        changed=self.serial[:-1]+('A' if self.serial[-1]!='A' else 'B')
        with self.assertRaises(ValueError): lic.parse_serial(changed,self.now)
        with self.assertRaises(ValueError): lic.parse_serial(self.serial,self.now+365*86400)
    def test_offline_deadline_cannot_reset_by_reentry(self):
        self.assertEqual(lic.evaluate(self.home,self.serial,now=self.now,transport=self.offline),(True,'OFFLINE_GRACE'))
        self.assertTrue(lic.evaluate(self.home,self.serial,now=self.now+lic.GRACE-1,transport=self.offline)[0])
        self.assertEqual(lic.evaluate(self.home,self.serial,now=self.now+lic.GRACE,transport=self.offline),(False,'GRACE_EXPIRED'))
    def test_online_revocation_locks_and_cannot_fall_back_offline(self):
        self.current=self.now
        self.assertTrue(lic.evaluate(self.home,self.serial,now=self.now,transport=self.active)[0])
        revoke=lambda *_:{'status':'revoked','server_time':self.now+86400}
        self.assertEqual(lic.evaluate(self.home,now=self.now+86400,transport=revoke),(False,'REVOKED'))
        self.assertEqual(lic.evaluate(self.home,now=self.now+86401,transport=self.offline),(False,'REVOKED'))
    def test_clock_recovery_with_server_time(self):
        self.current=self.now
        self.assertTrue(lic.evaluate(self.home,self.serial,now=self.now,transport=self.active)[0])
        self.current=self.now-600
        self.assertEqual(lic.evaluate(self.home,now=self.current,transport=self.offline),(False,'CLOCK_ERROR'))
        self.assertEqual(lic.evaluate(self.home,now=self.current,transport=self.active),(True,'ACTIVE'))
    def test_snapshot_excludes_license_secret_and_rejects_tracked(self):
        root=self.home; (root/'lib').mkdir(parents=True); (root/'state/license').mkdir(parents=True); (root/'vault').mkdir()
        for file in ('common.sh','snapshot.sh'):
            (root/'lib'/file).write_bytes((ROOT/'template/lib'/file).read_bytes())
        (root/'state/license/serial').write_text('never-add-this')
        run=lambda:subprocess.run(['bash',str(root/'lib/snapshot.sh')],env={**os.environ,'ILSON_HOME':str(root)},capture_output=True,text=True)
        r=run(); self.assertEqual(r.returncode,0,r.stderr)
        files=subprocess.check_output(['git','ls-files'],cwd=root,text=True)
        self.assertNotIn('state/license/serial',files)
        subprocess.run(['git','add','-f','state/license/serial'],cwd=root,check=True)
        self.assertNotEqual(run().returncode,0)
    def test_rejected_replacement_preserves_original_and_denial_is_rechecked(self):
        self.current=self.now
        self.assertTrue(lic.evaluate(self.home,self.serial,now=self.now,transport=self.active)[0])
        state=self.home/'state/license/state.json'; serial=self.home/'state/license/serial'
        before=(state.read_bytes(),serial.read_bytes())
        other=struct.pack('>BB16sHBII',1,1,b'b'*16,1,2,self.now-10000,self.now+86400)
        replacement=lic.encode_serial(other,SEED)
        denied=lambda *_:{'status':'device_limit','server_time':self.now+1}
        self.assertEqual(lic.evaluate(self.home,replacement,force=True,now=self.now+1,transport=denied),(False,'DEVICE_LIMIT'))
        self.assertEqual((state.read_bytes(),serial.read_bytes()),before)
        self.assertTrue(lic.evaluate(self.home,now=self.now+2,transport=self.offline)[0])
        self.assertEqual(lic.evaluate(self.home,now=self.now+3,force=True,transport=lambda *_:{'status':'payment_due','server_time':self.now+3}),(False,'PAYMENT_DUE'))
        self.current=self.now+4
        self.assertEqual(lic.evaluate(self.home,now=self.current,transport=self.active),(True,'ACTIVE'))
    def test_invalid_serial_does_not_replace_previous(self):
        self.assertTrue(lic.evaluate(self.home,self.serial,now=self.now,transport=self.offline)[0])
        with self.assertRaises(ValueError): lic.evaluate(self.home,'ILSON-BAD',now=self.now,transport=self.offline)
        self.assertEqual((self.home/'state/license/serial').read_text(),self.serial)

    def test_short_serial_normalization_rejection_and_node_hash_match(self):
        short = lic.generate_short_serial()
        self.assertEqual(len(short), 18)
        self.assertTrue(lic.is_short_serial(short))
        self.assertEqual(lic.normalize_short_serial(short.lower().replace('-', ' \n')), short)
        self.assertEqual(lic.short_code_hash(short.lower().replace('-', '')), lic.short_code_hash(short))
        # Reject ambiguous characters 0/O/1/I, wrong prefix, wrong length, non-string, oversized.
        for bad in (
            'IL2-0AAA-AAAA-AAAA', 'IL2-OAAA-AAAA-AAAA', 'IL2-1AAA-AAAA-AAAA', 'IL2-IAAA-AAAA-AAAA',
            'IL1-AAAA-AAAA-AAAA', 'IL2-AAAA-AAAA-AAA', 'IL2-AAAA-AAAA-AAAAA', 'IL2-' + 'A'*600,
            '', 12345, None, self.serial,
        ):
            self.assertFalse(lic.is_short_serial(bad), f'should reject {bad!r}')
            with self.assertRaises(ValueError):
                lic.normalize_short_serial(bad)
        js = "const h=require(process.argv[1]);process.stdout.write(h.shortCodeHash(process.argv[2]))"
        proc = subprocess.run(['node', '-e', js, str(ROOT/'server/license/api/v1/[action].js'), short.lower().replace('-', ' ')],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, lic.short_code_hash(short))
        # Non-ASCII whitespace (\x85, \u00a0) must be rejected identically in both Python and Node.
        for bad_ws in (short[:4] + '\x85' + short[4:], short[:4] + '\u00a0' + short[4:]):
            self.assertFalse(lic.is_short_serial(bad_ws))
            with self.assertRaises(ValueError) as ctx:
                lic.normalize_short_serial(bad_ws)
            self.assertEqual(str(ctx.exception), 'INVALID_SERIAL')
            with self.assertRaises(ValueError) as ctx:
                lic.short_code_hash(bad_ws)
            self.assertEqual(str(ctx.exception), 'INVALID_SERIAL')
            node_bad = subprocess.run(
                ['node', '-e', "const h=require(process.argv[1]);try{h.shortCodeHash(process.argv[2]);process.exit(2)}catch(e){process.stdout.write(e.message)}",
                 str(ROOT/'server/license/api/v1/[action].js'), bad_ws],
                capture_output=True, text=True)
            self.assertEqual(node_bad.returncode, 0, node_bad.stderr)
            self.assertEqual(node_bad.stdout, 'INVALID_SERIAL')

    def test_seal_and_unseal_roundtrip_and_tamper_detection(self):
        short = lic.generate_short_serial()
        sealed = lic.seal_serial(short, self.serial)
        self.assertEqual(len(sealed), 188)
        v1, info = lic.unseal_serial(short.lower().replace('-', ' '), sealed, self.now)
        self.assertEqual(v1, self.serial)
        self.assertEqual(info['id'], lic.parse_serial(self.serial, self.now)['id'])
        # Deterministic salt test
        salt = b'\x11' * 16
        self.assertEqual(lic.seal_serial(short, self.serial, salt=salt), lic.seal_serial(short, self.serial, salt=salt))
        with self.assertRaises(ValueError):
            lic.seal_serial(short, self.serial, salt=b'short')
        # Tamper in salt (pos 0), ciphertext (pos 40), tag (pos 180)
        for pos in (0, 40, 180):
            flipped = 'A' if sealed[pos] != 'A' else 'B'
            tampered = sealed[:pos] + flipped + sealed[pos+1:]
            with self.assertRaises(ValueError):
                lic.unseal_serial(short, tampered, self.now)
        # Wrong short code
        other_short = lic.generate_short_serial()
        while other_short == short:
            other_short = lic.generate_short_serial()
        with self.assertRaises(ValueError):
            lic.unseal_serial(other_short, sealed, self.now)
        # Bad sealed length / non-string
        for bad_sealed in ('', sealed[:-1], sealed + 'A', 123, None):
            with self.assertRaises(ValueError):
                lic.unseal_serial(short, bad_sealed, self.now)
        # Expired V1 inside sealed blob
        with self.assertRaises(ValueError) as ctx:
            lic.unseal_serial(short, sealed, self.now + 365 * 86400)
        self.assertEqual(str(ctx.exception), 'EXPIRED')
        # Future-issued V1 inside sealed blob
        with self.assertRaises(ValueError) as ctx:
            lic.unseal_serial(short, sealed, self.now - 20000)
        self.assertEqual(str(ctx.exception), 'CLOCK_ERROR')
        # Bad Ed25519 signature inside sealed blob
        bad_v1 = self.serial[:-1] + ('A' if self.serial[-1] != 'A' else 'B')
        # Construct raw 93 bytes with valid base32 but bad signature
        raw93 = bytearray(lic.serial_raw_bytes(self.serial))
        raw93[-1] ^= 0xff
        bad_sig_v1 = lic.raw_bytes_to_serial(bytes(raw93))
        bad_sealed = lic.seal_serial(short, bad_sig_v1)
        with self.assertRaises(ValueError) as ctx:
            lic.unseal_serial(short, bad_sealed, self.now)
        self.assertEqual(str(ctx.exception), 'INVALID_SERIAL')

    def test_short_serial_flow_offline_grace_and_state_preservation_in_template_and_course(self):
        course_spec = importlib.util.spec_from_file_location('course_license_test_module', ROOT/'course/lib/license.py')
        course_lic = importlib.util.module_from_spec(course_spec)
        course_spec.loader.exec_module(course_lic)
        old_course_keys = course_lic.PUBLIC_KEYS.copy()
        course_lic.PUBLIC_KEYS.clear(); course_lic.PUBLIC_KEYS[1] = PUBLIC
        self.addCleanup(lambda: (course_lic.PUBLIC_KEYS.clear(), course_lic.PUBLIC_KEYS.update(old_course_keys)))

        for label, mod in (('template', lic), ('course', course_lic)):
            with self.subTest(module=label):
                home = Path(self.tmp.name) / f'v2-{label}'
                short = mod.generate_short_serial()
                sealed = mod.seal_serial(short, self.serial)
                # 1. Offline first activation must fail with SERVER_UNAVAILABLE and leave no serial/state.
                self.assertEqual(mod.evaluate(home, short, force=True, now=self.now, transport=self.offline),
                                 (False, 'SERVER_UNAVAILABLE'))
                self.assertFalse((home/'state/license/serial').exists())
                self.assertFalse((home/'state/license/state.json').exists())

                # 2. Online V2 activation unseals and stores V1 serial, enabling 14-day offline grace.
                calls = []
                def ok_transport(action, serial_arg, device_arg):
                    calls.append((action, serial_arg, device_arg))
                    return {'status': 'active', 'server_time': self.now, 'paid_until': self.now + 86400, 'sealed_serial': sealed}
                self.assertEqual(mod.evaluate(home, short.lower().replace('-', ' '), force=True, now=self.now, transport=ok_transport),
                                 (True, 'ACTIVE'))
                self.assertEqual(calls[0][0], 'activate')
                self.assertEqual(calls[0][1], short)
                self.assertEqual((home/'state/license/serial').read_text(), self.serial)

                # 3. Existing valid license must be preserved if a replacement short serial fails.
                state_path = home/'state/license/state.json'
                serial_path = home/'state/license/serial'
                before = (state_path.read_bytes(), serial_path.read_bytes())
                other_short = mod.generate_short_serial()
                # Offline replacement
                self.assertEqual(mod.evaluate(home, other_short, force=True, now=self.now + 10, transport=self.offline),
                                 (False, 'SERVER_UNAVAILABLE'))
                self.assertEqual((state_path.read_bytes(), serial_path.read_bytes()), before)
                # Server rejection (device_limit, revoked)
                for denied_status in ('device_limit', 'revoked', 'invalid_serial'):
                    denied_tx = lambda *_, s=denied_status: {'status': s, 'server_time': self.now + 10}
                    self.assertEqual(mod.evaluate(home, other_short, force=True, now=self.now + 10, transport=denied_tx),
                                     (False, denied_status.upper()))
                    self.assertEqual((state_path.read_bytes(), serial_path.read_bytes()), before)
                # Server clock skew
                skew_tx = lambda *_: {'status': 'active', 'server_time': self.now + 1000, 'sealed_serial': sealed}
                self.assertEqual(mod.evaluate(home, other_short, force=True, now=self.now + 10, transport=skew_tx),
                                 (False, 'CLOCK_ERROR'))
                self.assertEqual((state_path.read_bytes(), serial_path.read_bytes()), before)
                # Missing or tampered sealed_serial
                missing_tx = lambda *_: {'status': 'active', 'server_time': self.now + 10}
                self.assertEqual(mod.evaluate(home, other_short, force=True, now=self.now + 10, transport=missing_tx),
                                 (False, 'INVALID_SERIAL'))
                self.assertEqual((state_path.read_bytes(), serial_path.read_bytes()), before)
                tampered_tx = lambda *_: {'status': 'active', 'server_time': self.now + 10, 'sealed_serial': sealed}
                self.assertEqual(mod.evaluate(home, other_short, force=True, now=self.now + 10, transport=tampered_tx),
                                 (False, 'INVALID_SERIAL'))
                self.assertEqual((state_path.read_bytes(), serial_path.read_bytes()), before)
                # Original license is still active offline and works for the full 14-day grace window!
                self.assertEqual(mod.evaluate(home, now=self.now + 20, transport=self.offline), (True, 'ACTIVE'))
                self.assertEqual(mod.evaluate(home, now=self.now + mod.GRACE - 1, transport=self.offline), (True, 'ACTIVE'))
                self.assertEqual(mod.evaluate(home, now=self.now + mod.GRACE, transport=self.offline), (False, 'GRACE_EXPIRED'))

    def test_main_prints_short_serial_offline_guidance(self):
        short = lic.generate_short_serial()
        for rel in ('template/lib/license.py', 'course/lib/license.py'):
            with self.subTest(script=rel):
                home = Path(self.tmp.name) / ('cli-' + rel.split('/')[0])
                code = (
                    "import importlib.util, sys; "
                    f"spec=importlib.util.spec_from_file_location('m',{str(ROOT/rel)!r}); "
                    "m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); "
                    "m.API_URL='https://127.0.0.1:1'; "
                    f"sys.argv=['license.py','--home',{str(home)!r},'activate',{short!r}]; "
                    "sys.exit(m.main())"
                )
                proc = subprocess.run(['python3', '-c', code], capture_output=True, text=True, timeout=15)
                self.assertEqual(proc.returncode, 1)
                self.assertIn('라이선스 확인 필요: SERVER_UNAVAILABLE — 짧은 시리얼은 최초 1회 온라인 확인이 필요합니다. 인터넷 연결 후 ilson license activate를 다시 실행해 주세요.',
                              proc.stdout)

if __name__=='__main__': unittest.main()
