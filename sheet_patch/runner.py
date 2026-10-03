"""One disposable POSIX process per analysis; process-group cancellation."""
from __future__ import annotations
from pathlib import Path
import multiprocessing as mp
import os
import queue
import resource
import shutil
import signal
import tempfile
import threading
import time
import uuid
from .engine import analyze, InputError, MAX_BYTES

WALL_SECONDS = 180
CPU_SECONDS = 120
MEMORY_BYTES = 1536 * 1024 * 1024


def _worker(old, new, path, options, events):
    os.setsid()
    resource.setrlimit(resource.RLIMIT_AS,(MEMORY_BYTES,MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU,(CPU_SECONDS,CPU_SECONDS))
    resource.setrlimit(resource.RLIMIT_FSIZE,(64*1024*1024,64*1024*1024))
    resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))
    try:
        result = analyze(Path(old),Path(new),Path(path),progress=lambda text:events.put(('progress',text)),**options)
        events.put(('done',result))
    except InputError as exc:
        events.put(('error',str(exc)))
    except FileNotFoundError:
        events.put(('error','Poppler pdftoppm is required. Install poppler-utils from your OS package manager.'))
    except (MemoryError, OSError):
        events.put(('error','Processing exceeded a resource limit or could not access a required local file.'))
    except Exception:
        events.put(('error','The document could not be processed safely. Use a flattened, well-formed PDF within the supported limits.'))

class Job:
    def __init__(self, old, new, **options):
        if not old or not new or len(old)>MAX_BYTES or len(new)>MAX_BYTES:
            raise InputError('Each PDF must be nonempty and at most 16 MiB.')
        self.id = uuid.uuid4().hex
        self.work = Path(tempfile.mkdtemp(prefix='sheet-patch-'))
        os.chmod(self.work,0o700)
        (self.work/'old.pdf').write_bytes(old); (self.work/'new.pdf').write_bytes(new)
        self.lock = threading.RLock()
        self.status = 'running'; self.progress = 'Starting bounded local worker'
        self.result = None; self.error = None; self.started = time.monotonic()
        self.closed = False
        context = mp.get_context('spawn')
        self.events = context.Queue()
        self.process = context.Process(target=_worker,args=(str(self.work/'old.pdf'),str(self.work/'new.pdf'),str(self.work),options,self.events),daemon=True)
        try:
            self.process.start()
        except Exception as exc:
            self.events.close()
            shutil.rmtree(self.work,ignore_errors=True)
            raise InputError('Could not start the local worker.') from exc
        self.monitor = threading.Thread(target=self._monitor,daemon=True)
        self.monitor.start()

    def _stop_process(self):
        try:
            os.killpg(self.process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if self.process.is_alive():
            try:
                # Worker calls setsid before parsing. If startup has not reached
                # setsid yet, kill only that child, never the parent's group.
                if os.getpgid(self.process.pid) == self.process.pid:
                    os.killpg(self.process.pid,signal.SIGKILL)
                else:
                    self.process.kill()
            except ProcessLookupError:
                pass
        self.process.join(timeout=3)

    def _monitor(self):
        while True:
            with self.lock:
                if self.status != 'running':
                    return
                if time.monotonic()-self.started > WALL_SECONDS:
                    self._stop_process(); self.status='error'
                    self.error='Processing exceeded the 180-second wall-clock limit.'
                    self.progress='Processing stopped safely'; return
            try:
                kind,value = self.events.get(timeout=.1)
            except queue.Empty:
                with self.lock:
                    if not self.process.is_alive():
                        self._stop_process()
                        self.status='error'; self.error='The worker stopped unexpectedly or exceeded a resource limit.'
                        self.progress='Processing stopped safely'; self.process.join(timeout=1)
                        return
                    if time.monotonic()-self.started > WALL_SECONDS:
                        self._stop_process(); self.status='error'
                        self.error='Processing exceeded the 180-second wall-clock limit.'
                        self.progress='Processing stopped safely'; return
                continue
            with self.lock:
                if self.status != 'running': return
                if kind == 'progress': self.progress=value
                elif kind == 'done':
                    self.result=value; self.status='done'; self.progress='Verified packet ready'
                    self._stop_process(); return
                else:
                    self.error=value; self.status='error'; self.progress='Processing stopped safely'
                    self._stop_process(); return

    def snapshot(self):
        with self.lock:
            data=dict(id=self.id,status=self.status,progress=self.progress)
            if self.result is not None: data['result']=self.result
            if self.error: data['error']=self.error
            return data

    def cancel(self):
        with self.lock:
            if self.status=='running':
                self._stop_process(); self.status='cancelled'; self.progress='Cancelled; no packet is available'
                self.result=None
                shutil.rmtree(self.work,ignore_errors=True)
        return self.snapshot()

    def close(self):
        self.cancel()
        self.monitor.join(timeout=3)
        with self.lock:
            if not self.closed:
                self.events.close(); self.events.join_thread()
                shutil.rmtree(self.work,ignore_errors=True); self.closed=True

class JobManager:
    def __init__(self):
        self.job=None; self.lock=threading.Lock()
    def start(self,old,new,**options):
        with self.lock:
            if self.job and self.job.snapshot()['status']=='running':
                raise InputError('An analysis is already running. Cancel it before starting another.')
            if self.job: self.job.close()
            self.job=Job(old,new,**options)
            return self.job
    def get(self,job_id):
        with self.lock:
            return self.job if self.job and self.job.id==job_id else None
    def close(self):
        with self.lock:
            if self.job: self.job.close(); self.job=None
