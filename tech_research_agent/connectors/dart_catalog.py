"""Server-reviewed company allowlist. No built-in real or synthetic company mapping."""
import copy
import re
from datetime import date
from urllib.parse import urlsplit


class CompanyCatalog:
    def __init__(self, entries):
        self.entries = copy.deepcopy(entries)
        for code, company in self.entries.items():
            if (not re.fullmatch(r'[0-9]{8}', code) or code in {'00000001', '00000002'} or
                    company.get('verified') is not True or not company.get('name')):
                raise ValueError('Unverified company catalog entry')
            verified = date.fromisoformat(company['verified_at'])
            origin = urlsplit(company['verification_source'])
            if verified > date.today() or origin.scheme != 'https' or origin.hostname != 'opendart.fss.or.kr':
                raise ValueError('Invalid company verification provenance')
            for field in ('allowed_users', 'allowed_projects'):
                if not isinstance(company.get(field), list) or not all(isinstance(v, str) for v in company[field]):
                    raise ValueError('Company permissions must be explicit lists')

    def permits(self, code, context):
        company = self.entries.get(code, {})
        return (context.user_id in company.get('allowed_users', []) and
                context.project_id in company.get('allowed_projects', []))

    def public_entries(self, context):
        return [{'corp_code': code, 'company_name': company['name'],
                 'verified_at': company['verified_at'], 'public_topic': context.entity_topics.get(code),
                 'synthetic': False, 'classification': 'PUBLIC'}
                for code, company in self.entries.items() if self.permits(code, context)]
