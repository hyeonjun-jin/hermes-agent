"""Admin-reviewed public IR inventory. No discovery API, crawling or model-supplied paths."""
import copy
import hashlib
import json
import re
from datetime import UTC, date, datetime
from pathlib import PurePosixPath
from threading import RLock
from urllib.parse import parse_qs, unquote, urlsplit

HOSTS = frozenset({'www.posco-inc.com', 'posco-inc.com'})
MATERIAL_KINDS = {'earnings_release': 'earnings', 'ir_datapack': 'earnings',
                  'investor_day': 'strategy', 'strategy_presentation': 'strategy', 'other': 'other'}


def official_url(value, *, pdf=False):
    if not isinstance(value, str) or any(ord(c) < 33 for c in value):
        raise ValueError('invalid_official_url')
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or parsed.hostname not in HOSTS or parsed.username or parsed.password or
            parsed.port not in (None, 443) or parsed.fragment):
        raise ValueError('unapproved_official_host')
    if '..' in PurePosixPath(unquote(parsed.path)).parts:
        raise ValueError('unsafe_url_path')
    if pdf and not parsed.path.lower().endswith('.pdf'):
        files = parse_qs(parsed.query).get('file', [])
        if (parsed.path != '/poscoinc/servlet/FileDown' or len(files) != 1 or
                not files[0].lower().endswith('.pdf') or '..' in PurePosixPath(files[0]).parts):
            raise ValueError('not_an_approved_pdf_url')
    return value


def relative_pdf(value):
    if (not isinstance(value, str) or not value or PurePosixPath(value).is_absolute() or
            '..' in PurePosixPath(value).parts or '\\' in value or ':' in value or any(ord(c) < 32 for c in value) or
            not value.lower().endswith('.pdf')):
        raise ValueError('unsafe_local_pdf_path')
    return value


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('timezone_required')
    return parsed


def validate_entry(entry, now):
    if not re.fullmatch(r'ir-[A-Za-z0-9][A-Za-z0-9_.-]{0,76}', entry['id']):
        raise ValueError('invalid_catalog_id')
    if entry.get('approved') is not True or entry.get('classification') != 'PUBLIC':
        raise ValueError('public_review_required')
    if not isinstance(entry['title'], str) or not entry['title'].strip():
        raise ValueError('missing_title')
    if entry['material_type'] not in MATERIAL_KINDS or entry['language'] not in {'ko', 'en'}:
        raise ValueError('invalid_material_type_or_language')
    published = date.fromisoformat(entry['published_at'])
    registered = timestamp(entry['registered_at']); verified = timestamp(entry['verified_at'])
    if not registered <= verified <= now or published > verified.date():
        raise ValueError('invalid_review_dates')
    official_url(entry['source_url'])
    if bool(entry.get('pdf_url')) == bool(entry.get('local_path')):
        raise ValueError('exactly_one_pdf_location_required')
    if entry.get('pdf_url'):
        official_url(entry['pdf_url'], pdf=True)
    else:
        relative_pdf(entry['local_path'])
    if not isinstance(entry['version'], str) or not entry['version'].strip() or not re.fullmatch(r'[0-9a-f]{64}', entry['sha256']):
        raise ValueError('version_and_sha256_required')
    if not isinstance(entry.get('keywords', []), list) or not all(isinstance(v, str) for v in entry.get('keywords', [])):
        raise ValueError('invalid_catalog_keywords')
    for field in ('allowed_users', 'allowed_projects'):
        if not isinstance(entry[field], list) or not all(isinstance(v, str) and v for v in entry[field]):
            raise ValueError('explicit_access_lists_required')


class IRCatalog:
    def __init__(self, entries=(), *, clock=None):
        self._entries = {}
        self._versions = {}
        self._lock = RLock()
        self.clock = clock or (lambda: datetime.now(UTC))
        if not isinstance(entries, (list, tuple)) or any(not isinstance(entry, dict) for entry in entries):
            raise ValueError('catalog_must_be_a_list_of_objects')
        ids = [entry['id'] for entry in entries]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate_catalog_id')
        for entry in entries:
            self.register(entry)

    def register(self, entry):
        data = copy.deepcopy(entry)
        try:
            validate_entry(data, self.clock())
        except (KeyError, TypeError) as exc:
            raise ValueError('invalid_catalog_fields') from exc
        data['kind'] = MATERIAL_KINDS[data['material_type']]
        with self._lock:
            key = (data['id'], data['version'])
            if key in self._versions and self._versions[key] != data['sha256']:
                raise ValueError('changed_bytes_require_new_version')
            self._versions[key] = data['sha256']
            previous = self._entries.get(data['id'], {})
            data['catalog_revision'] = previous.get('catalog_revision', 0)+1
            self._entries[data['id']] = data

    def withdraw(self, identifier):
        with self._lock:
            entry = copy.deepcopy(self._entries[identifier])
            entry['withdrawn'] = True
            self.register(entry)

    def get(self, identifier):
        with self._lock:
            return copy.deepcopy(self._entries.get(identifier))

    def entries(self):
        with self._lock:
            return copy.deepcopy(list(self._entries.values()))

    def permits(self, identifier, context, binding=None):
        entry = self.get(identifier)
        return bool(entry and not entry.get('withdrawn') and context.classification == 'PUBLIC' and
                    'posco_ir' in context.allowed_sources and identifier not in context.revoked and
                    context.project_id in context.allowed_projects and context.user_id in entry['allowed_users'] and
                    context.project_id in entry['allowed_projects'] and entry['published_at'] <= context.cutoff and
                    (binding is None or binding == self.binding(entry)))

    @staticmethod
    def binding(entry):
        return hashlib.sha256(json.dumps(entry, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
