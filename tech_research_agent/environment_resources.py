"""Environment information-resource view. Presentation only; never grants permissions.

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


def environment_source_overview(environment, connectors=None):
    """Show resources in the work environment without changing runtime access."""
    allowed = set(environment.get("allowed_sources", ()))
    connected = set(connectors or ())
    rows = []
    for key, name, description in SOURCE_CATALOG:
        rows.append({
            "정보 자원": name,
            "자료 종류": description,
            "Environment 정책": "허용" if key in allowed else "미허용",
            "외부 Connector": "설정됨" if key in connected else "미설정",
        })
    return rows
