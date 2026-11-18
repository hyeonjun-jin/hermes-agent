"""Environment information-resource view. Descriptive only; never grants permissions.

The runtime Environment's allowed_sources is server policy, not a collection of
retrieved documents. Connector configuration alone does not prove access or read.
Actual tool receipts and verified evidence remain separate.
"""

SOURCE_CATALOG = (
    ("openalex", "OpenAlex", "학술논문·메타데이터"),
    ("kipris_plus", "KIPRIS Plus", "특허정보"),
    ("opendart", "OpenDART", "기업 공시·재무정보"),
    ("posco_ir", "POSCO IR", "사업·투자 발표자료"),
)


def source_resources(environment):
    """Descriptive access requirements only; ServerContext remains authoritative."""
    catalog = {key: (name, description) for key, name, description in SOURCE_CATALOG}
    catalog['internal_mock'] = ('Internal Mock', 'SYNTHETIC 내부 문서')
    resources = []
    for key in sorted(set(environment['allowed_sources'])):
        name, description = catalog[key]
        resources.append({'source': key, 'name': name, 'material_type': description,
            'access_conditions': {
                'environment_classification': 'server_classification_and_acl' if key == 'internal_mock' else 'PUBLIC',
                'project_access': 'server_acl', 'publication_date': 'at_or_before_cutoff',
                'service_access': 'synthetic_only' if key == 'internal_mock' else 'connector_enforced',
                'external_llm_processing': 'separate_server_approval',
            }})
    return resources


def environment_source_overview(environment, connectors=None):
    """Show resources in the work environment without changing runtime access."""
    allowed = set(environment.get("allowed_sources", ()))
    connected = set(connectors or ())
    rows = []
    for key, name, description in SOURCE_CATALOG:
        connector = (connectors or {}).get(key) if isinstance(connectors, dict) else None
        enabled = getattr(connector, 'enabled', None)
        rows.append({
            "정보 자원": name,
            "자료 종류": description,
            "Environment 정책": "허용" if key in allowed else "미허용",
            "외부 Connector": "설정됨" if key in connected else "미설정",
            "활성 설정": "활성" if enabled is True else "비활성" if enabled is False else "미확인",
            "연결 확인": "미확인 — 네트워크 상태 조회 없음",
            "접근 조건": "PUBLIC 환경 · 서버 프로젝트/기준일 정책 · 정보원 이용권한 · 외부 모델 처리 별도 승인",
        })
    return rows
