"""Shared POSIX lease for participating Real backends; never resets a usage ledger."""
from contextlib import contextmanager
from pathlib import Path
import fcntl


@contextmanager
def claim_usage_lock(path):
    lock_path=Path(path).resolve().with_suffix('.research.lock')
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Usage ledger already owned; stop the other Real backend') from None
        try:
            yield
        finally:
            fcntl.flock(lock,fcntl.LOCK_UN)
