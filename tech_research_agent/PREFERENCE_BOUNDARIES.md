# 기술조사 이력·선호 우선순위·공개 표현 승인 경계

기준 커밋 `29b087231f`의 기술조사 Alignment를 유지하면서 검색 범위, 선호 충돌,
PRIVATE Persona의 최소 공개 표현만 보완했다. 기존 Alice Alignments와의 공통화,
Hermes 코어, Connector, 운영 원장·호출 한도, Benchmark·Scorer는 변경하지 않았다.

## 사용자·프로젝트를 먼저 제한하는 검색

`MemoryStore.search(..., project_id=...)`는 소유자 권한을 검사하고 SQL에서 사용자와
`[project=...] `의 정확한 접두사를 제한한 뒤 관련도 계산과 상위 4건 선택을 수행한다.
다른 프로젝트의 최근 기록이 먼저 상위 4건을 차지하는 문제를 막는다. 프로젝트 식별자의
`%`와 `_`는 와일드카드로 해석하지 않는다. 기술조사 Mock과 approved_public 모두 이
검색을 사용한다. 프로젝트 인자를 생략하는 기존 Alice 검색 계약은 유지한다.

검색 조건 자체는 권한 부여가 아니다. 기존 소유자 검사, 프로젝트 접근 검사,
문서별 접근 및 외부 처리 승인은 계속 별도로 적용한다.

## 선호 우선순위

1. 서버 정책: 도구·APP/API/OP 허용 범위와 전송 승인, 예산 등은 선호로 바꿀 수 없다.
2. 현재 요청·Environment: 기존 명시 요청 패턴과 허용 정보원, 검색 기간·결과 수 제한.
3. 승인된 기술조사 Persona: 위 제한 안에서 검색·분석·보고서의 선호를 제공한다.
4. 기존 명시 승인 선호: 상위 계층에서 결정하지 않은 source_focus를 보충한다.
5. 과거 이력: 과거 관찰이며, 상위 선호를 덮어쓰는 암묵적 선호 추출에 사용하지 않는다.

`persona_preferences.resolve()`는 저장 원본을 수정하지 않는 컨텍스트 사본을 만든다.
Persona가 APP/API 선호를 지정하거나 현재 요청이 정보원을 지정하면 충돌 가능한 기존
source_focus를 모델 사본에서 제거한다. 보고서 형식만 변경하면 기존 정보원 선호는
유지한다. `persona_guidance`의 `field_sources`, `overrides`, `priority`로 결정 경로를
추적한다. 각 역할은 동일한 해결된 지침을 받는다.

실제 LLM의 Tool Call을 코드에서 정답으로 다시 쓰지 않는다. 기존 Mock 라우팅만 같은
해결된 지침을 사용한다. 현재 명시 요청 인식은 기존의 `논문만`, `재무 중심` 패턴에
한정되며 일반 자연어의 모든 충돌을 결정적으로 해결하는 것은 아니다.

## PRIVATE 원본과 관리자 승인 공개 표현

사용자 후보 승인은 외부 반출 승인이 아니다. Persona 버전·피드백·후보·자유 의견은
기존 PRIVATE 저장 상태로 유지한다. 관리자는 별도 서버 절차에서 필요한 허용 필드를
직접 선정·검수하고 기존 ApprovalRegistry에 정확한 표현의 승인을 등록해야 한다.
UI나 모델이 이 승인을 만들 수 없다.

다음 함수는 검수할 subject만 준비한다. 승인 등록, 저장 원본 변경, 전송을 수행하지 않는다.

```python
from tech_research_agent.persona_preferences import memory_record
from tech_research_agent.persona_projection import public_persona_subject

source = memory_record(app.personas.current(actor, "proj-H"))
subject = public_persona_subject(
    actor.user_id, "proj-H", source, ["report_format"]
)
```

관리자는 이 subject에 기존 서버 승인 형식을 적용한다. PUBLIC 분류, 외부 처리 및 이용
조건 승인, 검수자, 사용자·프로젝트 범위, 유효 기간, 모델·목적과 정확한 content hash가
필요하다. 함수가 PUBLIC 표현을 구성했다는 사실만으로 전송 권한이 생기지 않는다.

표현은 허용 목록의 선택 필드와 원래 값만 포함하며 자유 지시문은 허용하지 않는다.
서버 측 subject의 persona_binding은 현재 Persona memory_record 전체 해시와 버전을 묶는다.
LLM의 approved_preferences와 persona_guidance에는 선택한 공개 표현만 제공한다.
이전처럼 PRIVATE 전체 선호에서 guidance를 별도로 만들지 않는다. 원본 해시·서버
승인 subject·자유 의견을 Persona 표현의 모델 컨텍스트로 보내지 않는다.

현재 원본과 정확히 일치하는 서로 다른 공개 표현은 하나만 활성 상태여야 한다.
없거나 모호하면 차단한다. 현재 원본 reader가 필수이며 매 전송 전에 기존 정책으로
내용·버전·권한·승인 만료·취소를 재확인한다. 비공개 필드만 바뀌거나 같은 선호로
롤백해 새 버전이 생겨도 이전 공개 표현 승인을 재사용할 수 없다.

이 승인은 기존 semantic 선호와 episode의 반출 권한을 주지 않는다. PRIVATE 기존
선호는 계속 차단하며 검색된 이력도 각각의 정확한 승인과 문서 의존성이 필요하다.
승인되지 않은 검색 이력을 조용히 제외해서 실행하지 않고 차단한다. 기존 real 경로는
PRIVATE Persona를 계속 차단하며 이 공개 표현 경로는 approved_public에만 적용한다.

## 검증 범위와 운영 제약

Mock/Stub 테스트는 프로젝트별 선검색, 우선순위 충돌, APP/API 인자·문서 선택,
최소 표현만 포함한 3단계 컨텍스트, 잘못된 승인과 변경·롤백·취소 시 차단을 검사한다.
전체 Stub 흐름의 기존 테스트용 예산은 운영 예산과 별개다. 운영 역할별·전체 호출 한도,
기본 비활성·비용 상한 0과 운영 usage.json은 그대로 유지한다.

실제 OpenAI·외부 정보원 API는 호출하지 않았으며 실제 LLM의 우선순위 준수나 개인화
개선을 입증하지 않는다. 승인 파일의 서버 접근 통제, 최소 공개 범위의 수동 검수,
전사 SSO·프로젝트 ACL, 보관·삭제 운영은 여전히 별도 과제다.

2026-11-18 검증: 공식 `scripts/run_tests.sh`로 기술조사·기존 Persona 전체와 Hermes
MemoryProvider/위임 범위 관련 30개 파일을 실행해 **559 passed, 0 failed**를 확인했다.
정적 검사에 따른 테스트 코드 정리 후 승인 경계·검색 우선순위 2개 파일도 다시 실행해
**60 passed, 0 failed**를 확인했다. `scripts/check --base 29b087231f`의 19개 검사도 통과했다.
실제 API 호출은 0회이며 테스트 원장은 모두 임시 경로를 사용했다.
