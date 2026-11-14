"""Entirely synthetic fixtures. No company documents or personal data."""
PROFILES = {
    "alice": {"project": "atlas", "format": "bullets", "language": "ko"},
    "bob": {"project": "beacon", "format": "table", "language": "ko"},
    "carol": {"project": "cedar", "format": "explanation", "language": "ko"},
}
PREFERENCES = {"alice": "delivery", "bob": "risk", "carol": "onboarding"}
DOCUMENTS = [
    {"id": "doc-1", "tag": "delivery", "text": "delivery 프로젝트 계획: 작은 단위로 배포하고 진행 상황을 공유합니다."},
    {"id": "doc-2", "tag": "delivery", "text": "delivery 일정: 의존성을 확인하고 담당자를 지정합니다."},
    {"id": "doc-3", "tag": "risk", "text": "risk 프로젝트 계획: 변경 전 위험과 복구 절차를 검토합니다."},
    {"id": "doc-4", "tag": "risk", "text": "risk 검증: 테스트 근거와 승인 기록을 남깁니다."},
    {"id": "doc-5", "tag": "onboarding", "text": "onboarding 프로젝트 계획: 용어 설명과 단계별 실습을 제공합니다."},
    {"id": "doc-6", "tag": "onboarding", "text": "onboarding 시작: 개발 환경과 도움말을 먼저 확인합니다."},
]
ENVIRONMENTS = {
    "atlas": {"project": "atlas", "stage": "prototype", "constraint": "작은 단위 배포"},
    "beacon": {"project": "beacon", "stage": "review", "constraint": "검증 근거 필요"},
    "cedar": {"project": "cedar", "stage": "learning", "constraint": "초보자 설명 필요"},
}
