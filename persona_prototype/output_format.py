"""Text-only Markdown conversion: no summarizing, fact inference, or HTML rendering."""
import re

_BREAK = re.compile(r'<br\s*/?>', re.IGNORECASE)


def table_rows(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 3 or any(not (line.startswith('|') and line.endswith('|')) for line in lines):
        return None
    rows = [re.split(r'(?<!\\)\|', line[1:-1]) for line in lines]
    rows = [[cell.strip() for cell in row] for row in rows]
    width = len(rows[0])
    if any(len(row) != width for row in rows) or not all(re.fullmatch(r':?-+:?', c) for c in rows[1]):
        return None
    return rows


def format_matches(text, style):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    table = table_rows(text) is not None
    bullets = all(re.match(r'^[-*] ', line) for line in lines)
    return {'table': table, 'bullets': bullets, 'explanation': not table and not bullets}[style]


def _cell(text):
    # Preserve existing escaped pipes; escape only Markdown column delimiters.
    return re.sub(r'(?<!\\)\|', r'\\|', text).replace('\r', '')


def _table(headers, rows):
    def line(values):
        return '| ' + ' | '.join(_cell(value) for value in values) + ' |'
    return '\n'.join([line(headers), line(['---'] * len(headers)), *(line(row) for row in rows)])


def _expand_cells(rows):
    expanded = []
    for row in rows:
        cells = [_BREAK.sub('\n', cell).splitlines() or [''] for cell in row]
        for index in range(max(map(len, cells))):
            expanded.append([cell[index] if index < len(cell) else '' for cell in cells])
    return expanded


def _labels(lines):
    matches = [re.fullmatch(r'([-*] )?([^:：]{1,40})([:：])\s*(.*)', line) for line in lines]
    if not all(m and m[2].strip() and not m[2].strip()[0].isdigit() for m in matches):
        return None
    return [[m[2], m[4]] for m in matches]


def readable_table(text):
    existing = table_rows(text)
    if existing:
        headers = existing[0]
        rows = _expand_cells(existing[2:])
        if len(headers) == 1:
            labeled = _labels([row[0] for row in rows])
            return _table(['항목', headers[0]], labeled) if labeled else _table(
                ['순서', headers[0]], [[str(i), row[0]] for i, row in enumerate(rows, 1)])
        return _table(headers, rows)
    lines = [line.strip() for line in _BREAK.sub('\n', text).splitlines() if line.strip()]
    labeled = _labels(lines)
    if labeled:
        return _table(['항목', '내용'], labeled)
    return _table(['순서', '내용'], [[str(i), line] for i, line in enumerate(lines, 1)])


def append_table_notes(text, notes):
    """Keep an existing table's columns while adding explicitly labeled local notes."""
    normalized = readable_table(text)
    rows = table_rows(normalized)
    width = len(rows[0])
    additions = [[label, content, *([''] * (width - 2))] for label, content in notes]
    return _table(rows[0], [*rows[2:], *additions])
