"""Bounded, memory-only ZIP/XML extraction. No extractall, file writes or URL resolution."""
import io
import stat
import zipfile
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET

MAX_DOWNLOAD = 8 * 1024 * 1024
MAX_FILES = 32
MAX_FILE = 2 * 1024 * 1024
MAX_EXPANDED = 16 * 1024 * 1024
MAX_RATIO = 100


class TextOnly:
    def __init__(self):
        self.depth = 0
        self.nodes = 0
        self.chars = 0
        self.parts = []

    def doctype(self, *args):
        raise ValueError('xml_dtd_forbidden')

    def start(self, tag, attrs):
        self.depth += 1
        self.nodes += 1
        if self.depth == 1 and tag.rsplit('}', 1)[-1].upper() not in {'DOCUMENT', 'HTML'}:
            raise ValueError('unsupported_xml_root')
        if self.depth > 64 or self.nodes > 50000:
            raise ValueError('xml_structure_limit')

    def end(self, tag):
        self.parts.append(' ')
        self.depth -= 1

    def data(self, text):
        self.chars += len(text)
        if self.chars > 200000:
            raise ValueError('xml_text_limit')
        self.parts.append(text)

    def close(self):
        return ' '.join(''.join(self.parts).split())


def safe_xml(data):
    parser = ET.XMLParser(target=TextOnly())
    parser.feed(data)
    return parser.close()


def check_members(members):
    if not members or len(members) > MAX_FILES or sum(m.file_size for m in members) > MAX_EXPANDED:
        raise ValueError('zip_expansion_limit')
    names = set()
    for member in members:
        name = member.filename
        path = PurePosixPath(name)
        if (path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name or
                name in names or stat.S_ISLNK(member.external_attr >> 16)):
            raise ValueError('unsafe_zip_member')
        names.add(name)
        if (member.flag_bits & 1 or member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) or
                member.file_size > MAX_FILE or member.file_size > max(member.compress_size, 1) * MAX_RATIO):
            raise ValueError('zip_member_limit')


def extract_document(data, section=None):
    spans, warnings = [], []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        check_members(archive.infolist())
        for member in archive.infolist():
            if member.is_dir():
                continue
            if PurePosixPath(member.filename).suffix.lower() != '.xml':
                warnings.append('unsupported_attachment')
                continue
            try:
                with archive.open(member) as source:
                    payload = source.read(MAX_FILE+1)
                if len(payload) > MAX_FILE:
                    raise ValueError('expanded_file_limit')
                text = safe_xml(payload)
                if not text:
                    raise ValueError('empty_xml')
                for offset in range(0, len(text), 3000):
                    chunk = text[offset:offset+3000]
                    if not section or section.casefold() in chunk.casefold():
                        spans.append({'id': f'{member.filename}:{offset}', 'text': chunk,
                                      'kind': 'disclosure_body', 'file': member.filename,
                                      'text_offset': offset})
            except (ET.ParseError, ValueError, UnicodeError, LookupError):
                warnings.append('unsupported_or_invalid_xml')
    if section:
        warnings.append('section_literal_text_filter_not_full_document')
    return spans, warnings
