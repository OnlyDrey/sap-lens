"""Process-lifetime cross-platform lease; single worker per mutable data store."""
import json
import os
from pathlib import Path


class StorageLease:
    def __init__(self, directory, mode):
        self.directory, self.mode, self.stream = Path(directory), mode, None

    def acquire(self):
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.stream = (self.directory/'.sap-lens-instance.lock').open('a+b')
        try:
            if self.stream.seek(0,2)==0:
                self.stream.write(b'0'); self.stream.flush()
            self.stream.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            marker=self.directory/'deployment.json'
            if marker.exists() and json.loads(marker.read_text()) != {'version':1,'mode':self.mode}:
                raise ValueError('Desktop and server must use separate data directories.')
            if not marker.exists():
                from config import atomic_write
                atomic_write(marker,json.dumps(dict(version=1,mode=self.mode)).encode())
            return self
        except Exception:
            self.close()
            raise RuntimeError('Application storage is owned by another instance/mode or cannot be initialized.') from None

    def close(self):
        if self.stream:
            self.stream.close();self.stream=None
