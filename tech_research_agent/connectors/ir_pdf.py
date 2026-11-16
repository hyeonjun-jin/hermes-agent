"""PDF subprocess boundary and confined local-file loading."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

from .ir_catalog import relative_pdf
from .ir_pdf_worker import MAX_PDF_BYTES


class PDFRejected(ValueError):
    pass


class PDFParser:
    def __init__(self, *, python=None):
        self.python = str(python or sys.executable)  # Trusted server interpreter, not a model argument.

    def parse(self, data, pages):
        worker = Path(__file__).with_name('ir_pdf_worker.py')
        try:
            completed = subprocess.run([self.python, '-I', str(worker), json.dumps(pages)], input=data,
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=12,
                                       env={'LANG': 'C.UTF-8', 'TZ': 'UTC'}, check=False)
            if completed.returncode or len(completed.stdout) > 8 * 1024 * 1024:
                raise PDFRejected('pdf_parser_rejected_or_limit')
            result = json.loads(completed.stdout)
            if result.get('error') or not isinstance(result.get('pages'), list):
                raise PDFRejected('pdf_parser_rejected')
            return result
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            raise PDFRejected('pdf_parser_unavailable_or_limit') from exc


def local_pdf(root, relative):
    relative_pdf(relative)
    if root is None:
        raise PDFRejected('local_pdf_root_not_configured')
    descriptors = []
    try:
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(fd)
        parts = Path(relative).parts
        for part in parts[:-1]:
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            descriptors.append(fd)
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
        descriptors.append(fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_PDF_BYTES:
            raise PDFRejected('local_pdf_type_or_size')
        with os.fdopen(os.dup(fd), 'rb') as source:
            data = source.read(MAX_PDF_BYTES+1)
        if len(data) > MAX_PDF_BYTES:
            raise PDFRejected('local_pdf_size')
        return data
    except OSError as exc:
        raise PDFRejected('local_pdf_unavailable') from exc
    finally:
        for fd in reversed(descriptors):
            os.close(fd)
