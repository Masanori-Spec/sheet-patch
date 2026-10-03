from pathlib import Path
import base64
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
from sheet_patch.demo import demo_files,make_pdf
from sheet_patch.runner import Job,JobManager
from sheet_patch.server import LocalServer,MAX_REQUEST
from sheet_patch.engine import InputError


def wait(job,timeout=20):
    deadline=time.monotonic()+timeout
    while job.snapshot()['status']=='running' and time.monotonic()<deadline:time.sleep(.03)
    return job.snapshot()

class RunnerTests(unittest.TestCase):
    def test_success_and_cleanup(self):
        job=Job(*demo_files(),dpi=72)
        work=job.work
        try:
            state=wait(job);self.assertEqual(state['status'],'done',state)
            self.assertEqual(state['result']['summary']['reprint'],2)
        finally:job.close()
        self.assertFalse(work.exists())
    def test_cancel_and_repeat(self):
        manager=JobManager()
        try:
            blob=make_pdf(['front','back']*40)
            job=manager.start(blob,blob,dpi=144)
            with self.assertRaises(InputError):manager.start(blob,blob,dpi=72)
            state=job.cancel();self.assertEqual(state['status'],'cancelled')
            self.assertFalse(job.process.is_alive())
            old_work=job.work
            new=manager.start(*demo_files(),dpi=72)
            self.assertFalse(old_work.exists());self.assertIsNone(manager.get(job.id))
            self.assertEqual(wait(new)['status'],'done')
        finally:manager.close()
    def test_wall_timeout(self):
        with patch('sheet_patch.runner.WALL_SECONDS',-.1):
            job=Job(*demo_files(),dpi=144)
            try:
                state=wait(job);self.assertEqual(state['status'],'error')
                self.assertIn('wall-clock',state['error'])
                self.assertFalse(job.process.is_alive())
            finally:job.close()
    def test_malformed_worker_error(self):
        job=Job(b'%PDF-1.4\nbroken\n%%EOF',demo_files()[1],dpi=72)
        try:self.assertEqual(wait(job)['status'],'error')
        finally:job.close()

class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=LocalServer(('127.0.0.1',0))
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base=cls.server.url
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join(timeout=3)
    def fetch(self,path,body=None,headers=None):
        data=None if body is None else json.dumps(body).encode()
        h={} if body is None else {'Content-Type':'application/json'}
        h.update(headers or {})
        request=urllib.request.Request(self.base+path,data=data,headers=h)
        try:response=urllib.request.urlopen(request,timeout=20)
        except urllib.error.HTTPError as error:response=error
        return response.status,response.read(),response.headers
    def test_host_origin_and_no_cors(self):
        for headers in ({'Host':'evil.test'},{'Origin':'https://evil.test'},{'Sec-Fetch-Site':'cross-site'}):
            status,_,_=self.fetch('api/demo',headers=headers);self.assertEqual(status,403)
        status,_,headers=self.fetch('api/demo');self.assertEqual(status,200)
        self.assertNotIn('Access-Control-Allow-Origin',headers)
        self.assertIn("connect-src 'self'",headers['Content-Security-Policy'])
        self.assertEqual(headers['Referrer-Policy'],'no-referrer')
    def test_path_traversal_and_unknown(self):
        for path in ('../sheet_patch/engine.py','%2e%2e/sheet_patch/engine.py','api/jobs/invalid','?leak=1'):
            self.assertEqual(self.fetch(path)[0],404)
    def test_input_validation(self):
        for body in ([],{},dict(old=dict(name='a',data='bad'),new=dict(name='b',data='bad')),dict(dpi=True)):
            self.assertEqual(self.fetch('api/jobs',body)[0],400)
    def test_complete_api_and_preview(self):
        status,data,_=self.fetch('api/demo');self.assertEqual(status,200)
        request=json.loads(data);request['dpi']=72
        status,data,_=self.fetch('api/jobs',request);self.assertEqual(status,202)
        job_id=json.loads(data)['id']
        job=self.server.manager.get(job_id);self.assertEqual(wait(job)['status'],'done')
        status,data,_=self.fetch('api/jobs/'+job_id);state=json.loads(data)
        self.assertEqual(status,200);self.assertEqual(state['result']['summary']['reused'],2)
        status,data,_=self.fetch(f'api/jobs/{job_id}/preview/new/1.png')
        self.assertEqual(status,200);self.assertTrue(data.startswith(b'\x89PNG'))
        self.assertEqual(self.fetch(f'api/jobs/{job_id}/preview/new/99.png')[0],404)
        status,data,headers=self.fetch(f'api/jobs/{job_id}/packet.zip')
        self.assertEqual(status,200);self.assertTrue(data.startswith(b'PK'))
        self.assertEqual(headers['Content-Disposition'],'attachment; filename="sheet-patch-packet.zip"')
    def test_upload_limit(self):
        self.assertEqual(self.fetch('api/jobs',{},headers={'Content-Length':str(MAX_REQUEST+1)})[0],413)
