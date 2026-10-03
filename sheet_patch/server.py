"""Capability-URL loopback workbench. Inputs never leave this machine."""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import base64
import binascii
import json
import re
import secrets
import threading
import webbrowser
from .demo import demo_files
from .engine import InputError, MAX_BYTES, DPI_OPTIONS, safe_name
from .runner import JobManager

WEB = Path(__file__).resolve().parent.parent/'web'
MAX_REQUEST = 2*((MAX_BYTES+2)//3*4) + 16384

class LocalServer(HTTPServer):
    def __init__(self,address):
        self.token=secrets.token_urlsafe(32);self.manager=JobManager()
        super().__init__(address,Handler)
    @property
    def url(self): return f'http://127.0.0.1:{self.server_port}/{self.token}/'
    def server_close(self):
        self.manager.close();super().server_close()

class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.0'
    def log_message(self,*args): pass # Do not log capability URLs or filenames.
    def setup(self):
        super().setup();self.connection.settimeout(15)
    def _send(self,status,body=b'',content_type='application/json',download=None):
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Cross-Origin-Resource-Policy','same-origin')
        self.send_header('Content-Security-Policy',"default-src 'self'; connect-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        if download:self.send_header('Content-Disposition',f'attachment; filename="{download}"')
        self.end_headers()
        try:self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError):pass
    def _json(self,status,data):self._send(status,json.dumps(data).encode())
    def _path(self):
        if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
            self._json(403,{'error':'Invalid local host.'});return None
        origin=self.headers.get('Origin')
        if origin and origin != f'http://127.0.0.1:{self.server.server_port}':
            self._json(403,{'error':'Cross-origin requests are rejected.'});return None
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            self._json(403,{'error':'Cross-site requests are rejected.'});return None
        prefix=f'/{self.server.token}/'
        if not self.path.startswith(prefix) or '?' in self.path or '#' in self.path:
            self._json(404,{'error':'Not found.'});return None
        return self.path[len(prefix):]
    def do_GET(self):
        path=self._path()
        if path is None:return
        if path in ('','index.html','app.js','styles.css','model.js','favicon.svg'):
            name=path or 'index.html'
            types={'index.html':'text/html; charset=utf-8','app.js':'text/javascript; charset=utf-8','styles.css':'text/css; charset=utf-8','model.js':'text/javascript; charset=utf-8','favicon.svg':'image/svg+xml'}
            self._send(200,(WEB/name).read_bytes(),types[name]);return
        if path=='api/demo':
            old,new=demo_files()
            self._json(200,dict(old=dict(name='demo-old.pdf',data=base64.b64encode(old).decode()),new=dict(name='demo-new.pdf',data=base64.b64encode(new).decode())));return
        match=re.fullmatch(r'api/jobs/([a-f0-9]{32})(?:/(packet\.zip|preview/(old|new)/([1-9][0-9]?)\.png))?',path)
        if not match:self._json(404,{'error':'Not found.'});return
        job=self.server.manager.get(match[1])
        if not job:self._json(404,{'error':'This analysis is no longer available.'});return
        state=job.snapshot()
        if not match[2]:self._json(200,state);return
        if state['status']!='done':self._json(409,{'error':'Verified output is not ready.'});return
        # Hold manager lock through file read so replacing a job cannot remove it.
        with self.server.manager.lock:
            if self.server.manager.job is not job:self._json(404,{'error':'Analysis replaced.'});return
            file=job.work/match[2]
            if not file.is_file():self._json(404,{'error':'Not found.'});return
            content=file.read_bytes()
        if match[2]=='packet.zip':self._send(200,content,'application/zip','sheet-patch-packet.zip')
        else:self._send(200,content,'image/png')
    def do_POST(self):
        path=self._path()
        if path is None:return
        if self.headers.get('Content-Type') != 'application/json':
            self._json(415,{'error':'JSON requests are required.'});return
        length=self.headers.get('Content-Length','')
        if not length.isdecimal() or not 0<int(length)<=MAX_REQUEST:
            self._json(413,{'error':'Request size exceeds the supported limit.'});return
        try:
            raw=self.rfile.read(int(length))
            if len(raw)!=int(length):raise InputError('Incomplete request body.')
            data=json.loads(raw)
            if not isinstance(data,dict):raise InputError('Expected a JSON object.')
            if path=='api/jobs':
                dpi=data.get('dpi',144);force=data.get('force',[])
                if type(dpi) is not int or dpi not in DPI_OPTIONS:raise InputError('DPI must be 72, 144 or 216.')
                if not isinstance(force,list) or len(force)>40 or any(type(v)is not int or v<1 or v>40 for v in force):raise InputError('Invalid force-reprint sheet numbers.')
                files=[];names=[]
                for kind in ('old','new'):
                    part=data.get(kind)
                    if not isinstance(part,dict) or not isinstance(part.get('data'),str) or not isinstance(part.get('name'),str):raise InputError('Choose an old PDF and a new PDF.')
                    if len(part['data'])>((MAX_BYTES+2)//3*4):raise InputError('Each PDF must be at most 16 MiB.')
                    blob=base64.b64decode(part['data'],validate=True)
                    if not blob or len(blob)>MAX_BYTES:raise InputError('Each PDF must be nonempty and at most 16 MiB.')
                    files.append(blob);names.append(safe_name(part['name']))
                job=self.server.manager.start(*files,old_name=names[0],new_name=names[1],dpi=dpi,force=force)
                self._json(202,{'id':job.id});return
            match=re.fullmatch(r'api/jobs/([a-f0-9]{32})/cancel',path)
            if match:
                job=self.server.manager.get(match[1])
                if not job:self._json(404,{'error':'Analysis no longer available.'});return
                self._json(200,job.cancel());return
            self._json(404,{'error':'Not found.'})
        except (ValueError,TypeError,binascii.Error,UnicodeError,RecursionError) as exc:
            message=str(exc) if isinstance(exc,InputError) else 'Invalid request data.'
            self._json(400,{'error':message})
        except TimeoutError:
            self._json(408,{'error':'Upload timed out.'})
        except OSError:
            self._json(500,{'error':'Local processing could not start. Check available disk space and permissions.'})

def serve(port=0,open_browser=True):
    server=LocalServer(('127.0.0.1',port))
    print(f'Sheet Patch local workbench: {server.url}',flush=True)
    print('Keep this capability URL private. Press Ctrl+C to stop and remove temporary PDFs.',flush=True)
    if open_browser:threading.Timer(.3,lambda:webbrowser.open(server.url)).start()
    try:server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:pass
    finally:server.server_close()
