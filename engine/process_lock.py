"""One trading worker per checkout, across processes and server ports."""
import os
from contextlib import contextmanager


@contextmanager
def acquire(path=None):
    path = path or os.path.join(os.path.dirname(__file__), "..", "data", "worker.lock")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a+b") as handle:
        if os.path.getsize(path) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise RuntimeError("DDM koerer allerede fra denne mappe") from None
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise RuntimeError("DDM koerer allerede fra denne mappe") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)
