import http.client
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_web_admin import BoxFixture, admin
from mini_workspace import Workspace

class LicenseWebTest(BoxFixture):
    def test_unlicensed_web_only_shows_activation(self):
        server=admin.Server(self.box,0)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        self.addCleanup(lambda: (server.shutdown(),thread.join(),server.server_close()))
        with patch('license.evaluate',return_value=(False,'NO_LICENSE')):
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            conn.request('GET','/current/index.html')
            response=conn.getresponse(); body=response.read().decode(); self.assertEqual(response.status,200)
            self.assertIn('ilson license activate',body)
            conn.request('GET','/api/overview'); response=conn.getresponse(); response.read()
            self.assertEqual(response.status,403); conn.close()
    def test_unlicensed_worker_does_not_execute(self):
        worker=Workspace.__new__(Workspace); worker.home=self.home
        class Stop:
            stopped=False
            def is_set(self): return self.stopped
            def wait(self,_): self.stopped=True
        worker.stop_event=Stop(); calls=[]
        with patch('license.evaluate',return_value=(False,'NO_LICENSE')):
            worker.loop(lambda: calls.append('ran'))
        self.assertEqual(calls,[])
    def test_serial_is_redacted(self):
        serial='ILSON-'+'-'.join(['A'*5]*29+['AAAA'])
        self.assertNotIn(serial,self.box.redact('message '+serial))

if __name__=='__main__': unittest.main()
