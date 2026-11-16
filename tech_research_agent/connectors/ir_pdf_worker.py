"""Standalone bounded PDF worker. It receives bytes, never a URL or local document path."""
import hashlib
import io
import json
import sys

MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PAGES = 100
MAX_PAGE_CONTENT = 2 * 1024 * 1024
MAX_PAGE_TEXT = 100000
MAX_TOTAL_TEXT = 1000000


def limits():
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (6, 7))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))


def page_text(page, number):
    from pypdf.errors import PyPdfError, DependencyError
    try:
        contents = page.get_contents()
        if contents is not None and len(contents.get_data()) > MAX_PAGE_CONTENT:
            return {'page': number, 'status': 'content_limit', 'text': None}
        visuals = set()
        def visit(operator, operands, cm, tm):
            if operator in {b'Do', b're', b'l', b'c', b'BI'}:
                visuals.add(operator.decode('ascii'))
        text = page.extract_text(visitor_operand_before=visit).strip()
        if len(text) > MAX_PAGE_TEXT:
            return {'page': number, 'status': 'text_limit', 'text': None}
        status = ('partial_visual' if visuals else 'ok') if text else 'image_or_graphic_only' if visuals else 'no_extractable_text'
        return {'page': number, 'status': status, 'text': text or None,
                'visual_operators': sorted(visuals), 'tables_charts_parsed': False,
                'layout_semantics_verified': False}
    except (PyPdfError, DependencyError, LookupError, ValueError, TypeError, AttributeError, ArithmeticError, RuntimeError, OSError):
        # Malformed untrusted objects must not expose PDF content or parser internals on stderr.
        return {'page': number, 'status': 'parse_error', 'text': None}


def extract(data, pages):
    from pypdf import PdfReader, __version__
    if len(data) > MAX_PDF_BYTES or not data.startswith(b'%PDF-'):
        raise ValueError('invalid_pdf_or_size')
    reader = PdfReader(io.BytesIO(data), strict=True)
    if reader.is_encrypted:
        raise ValueError('encrypted_pdf_not_supported')
    root = reader.trailer['/Root']
    names = root['/Names'] if '/Names' in root else {}
    if '/AA' in root or '/OpenAction' in root or '/JavaScript' in names or '/EmbeddedFiles' in names:
        raise ValueError('active_or_embedded_content_not_supported')
    total = len(reader.pages)
    if not 1 <= total <= MAX_PAGES:
        raise ValueError('page_count_limit')
    selected = pages or list(range(1, total+1))
    if any(type(n) is not int or not 1 <= n <= total for n in selected) or len(selected) != len(set(selected)):
        raise ValueError('invalid_requested_pages')
    results = []
    chars = 0
    for number in selected:
        row = page_text(reader.pages[number-1], number)
        chars += len(row.get('text') or '')
        if chars > MAX_TOTAL_TEXT:
            row.update(status='total_text_limit', text=None)
        results.append(row)
    return {'source_sha256': hashlib.sha256(data).hexdigest(), 'page_count': total, 'pages': results,
            'parser': 'pypdf', 'parser_version': __version__}


def main():
    try:
        limits()
        pages = json.loads(sys.argv[1])
        data = sys.stdin.buffer.read(MAX_PDF_BYTES+1)
        output = extract(data, pages)
        sys.stdout.write(json.dumps(output, ensure_ascii=False))
    except (ImportError, LookupError, ValueError, TypeError, AttributeError, ArithmeticError, RuntimeError, OSError):
        sys.stdout.write(json.dumps({'error': 'pdf_parser_unavailable_or_rejected'}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
