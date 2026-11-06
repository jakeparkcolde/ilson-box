"""Isolated local PostgreSQL transaction test; creates no production resource."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
BIN=Path('/opt/homebrew/opt/postgresql@17/bin')

@unittest.skipUnless((BIN/'initdb').is_file() and (BIN/'psql').is_file(),'local PostgreSQL 17 unavailable')
class PostgreSQLLicenseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='ilson-license-pg-')
        cls.base=Path(cls.temp.name); cls.data=cls.base/'data'
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); cls.port=sock.getsockname()[1]
        def run(*cmd):
            return subprocess.run([str(x) for x in cmd],text=True,capture_output=True,check=True)
        try:
            run(BIN/'initdb','-D',cls.data,'--auth=trust','--no-locale','-E','UTF8')
            run(BIN/'pg_ctl','-D',cls.data,'-l',cls.base/'postgres.log','-o',f"-h '' -k {cls.base} -p {cls.port}",'start','-w')
            cls.running=True
            cls.sql('create role anon; create role authenticated; create role service_role;')
            cls.sql((ROOT/'server/license/migrations/001_license.sql').read_text())
        except Exception:
            if getattr(cls,'running',False): run(BIN/'pg_ctl','-D',cls.data,'stop','-m','fast','-w')
            cls.temp.cleanup()
            raise
    @classmethod
    def tearDownClass(cls):
        try:
            subprocess.run([str(BIN/'pg_ctl'),'-D',str(cls.data),'stop','-m','fast','-w'],check=True,text=True,capture_output=True)
        finally:
            cls.temp.cleanup()
    @classmethod
    def sql(cls,query,check=True):
        result=subprocess.run([str(BIN/'psql'),'-X','-qAt','-v','ON_ERROR_STOP=1','-h',str(cls.base),'-p',str(cls.port),'-d','postgres'],input=query,text=True,capture_output=True)
        if check and result.returncode:
            raise AssertionError(result.stderr)
        return result
    def test_concurrent_device_limit_rls_and_revocation(self):
        now=int(time.time()); ident='ab'*16
        lic={'id':ident,'payload_hash':'12'*32,'cohort':1,'plan':2,'issued':now-10,'expires':now+31536000}
        base={'license':lic,'ip_hash':'a'*64}
        def request_sql(p):
            return "select public.ilson_license_request('"+json.dumps(p).replace("'","''")+"'::jsonb);"
        reg={**base,'action':'register','display_name':'test','paid_until':now+86400,'request_id':'1'*32}
        self.assertEqual(json.loads(self.sql(request_sql(reg)).stdout)['status'],'ok')
        barrier=threading.Barrier(3)
        def activate(n):
            request={**base,'action':'activate','device_hash':str(n)*64}
            barrier.wait()
            result=self.sql('begin; '+request_sql(request)+' select pg_sleep(0.3); commit;')
            return json.loads(result.stdout.splitlines()[0])['status']
        with ThreadPoolExecutor(max_workers=3) as pool:
            states=list(pool.map(activate,(1,2,3)))
        self.assertEqual(sorted(states),['active','active','device_limit'])
        direct=self.sql('set role anon; select * from license_private.licenses;',check=False)
        self.assertNotEqual(direct.returncode,0)
        rpc=self.sql("set role authenticated; select public.ilson_license_request('{}'::jsonb);",check=False)
        self.assertNotEqual(rpc.returncode,0)
        revoke={**base,'action':'revoke','request_id':'2'*32}
        self.assertEqual(json.loads(self.sql(request_sql(revoke)).stdout)['status'],'ok')
        check={**base,'action':'check','device_hash':'1'*64}
        self.assertEqual(json.loads(self.sql(request_sql(check)).stdout)['status'],'revoked')

if __name__=='__main__': unittest.main()
