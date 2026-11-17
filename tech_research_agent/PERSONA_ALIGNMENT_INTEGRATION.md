# 기술조사 Persona Alignment 통합

기준 `20a87a24`, 2026-11-17. PersonaAgent의 test-time 피드백 반영 아이디어를
기술조사 프로토타입에 연결했다. 별도 optimizer/Orchestrator LLM은 없고 실제 OpenAI·정보원
API 호출도 하지 않았다. 논문 알고리즘 전체의 재현이나 개인화 효과 검증을 뜻하지 않는다.

## 기존 코드에서 가져온 것

- MemoryStore의 소유자 검사·SQLite 저장·transaction, 기존 Principal/OwnerOnly 계약.
- PreferenceAligner의 확인/동의한 서로 다른 조사 → 일관된 선호 후보 → 별도 사례 확인 →
  격리된 MockReplay → 명시 승인이라는 절차. actor 기반 propose 인터페이스 유지.
- AlignmentStore의 append-only 버전·현재 revision·기준 버전/피드백 스냅샷 대조·명시 승인·롤백 방식.
- 기존 Hermes Research/Analysis/Verification, MemoryProvider, SYNTHETIC Corpus와 P1 도구 정책.

기존 PreferenceAligner는 format과 risk/delivery/onboarding focus만 다루며, web_turns 및
Alice/Bob/Carol 프로필에 묶여 있다. 기존 MockReplay는 이 챗봇의 형식·태그 점수를 계산한다.
이 규칙·프로필·점수 계산을 기술조사에 그대로 쓰지 않았다. 해당 클래스와 원래 동작은 그대로
두고 연구소/전략실/재무팀용 ResearchPreferenceAligner와 TechnicalMockReplay를 별도로 구현했다.
기술조사 Replay는 점수를 만들거나 improved=true를 보고하지 않는다.

## 저장과 승인 흐름

MemoryStore의 동일한 memory.sqlite 안에 전용 테이블을 추가했다.

| 테이블 | 내용 |
|---|---|
| tr_turns | 사용자·프로젝트별 원래 질문, Profile/Environment, Persona 버전, 실제 Trace/원응답/보고서 스냅샷 |
| tr_feedback | 조사 ID에 연결된 구조화 평가·선호 변경 값·자유 의견·확인·Alignment 동의·원래 조사 해시 |
| tr_personas / tr_active | 프로젝트별 불변 Persona 버전과 현재 버전 포인터 |
| tr_proposals | 기존 버전·현재 Legacy 선호 해시·피드백 스냅샷·후보·Replay 결과·상태 |
| tr_persona_events | 피드백 변경, 승인·거절·롤백 기록 |

tr_feedback은 기술조사용 Episodic Memory다. 기존 조사 이력 episodes와 구분하여 자유 의견이
일반 Memory 검색이나 외부 LLM 컨텍스트로 섞이지 않게 했다. 평가 항목은 정보원, 검색 범위/
최신성, 조사 깊이, 기술 분석, 경쟁사/사업화, 투자/재무 위험, 보고서 구성의 일곱 가지다.
각 항목은 helpful/needs_change/not_assessed로 보관하며 점수 계산에는 쓰지 않는다.

자유 의견은 최대 4,000자로 PRIVATE 저장한다. 자연어를 지시문으로 추출하지 않는다.
현재 구현의 후보 생성은 **사용자가 선택한 구조화 선호**만 사용한다. 자유 의견만 적은
피드백이나 확인/동의하지 않은 피드백은 저장되지만 후보 학습 입력이 되지 않는다.

1. 완료된 서로 다른 조사 네 개 이상의 확인·동의한 피드백을 모은다. 동일 조사 편집 네 번을
   네 경험으로 세지 않는다. 최근 최대 12개 중 마지막 조사를 확인 사례로 분리한다.
2. 나머지에서 같은 필드의 선호가 세 번 이상 일관되게 나타나면 후보에 반영한다.
   변경 필드는 마지막 사례도 같은 값을 명시해야 한다.
3. 기존 Persona와 후보로 각각 격리된 실제 Hermes Mock 흐름을 실행한다. 두 실행의 질문·
   Profile·Environment·Legacy 선호는 같고, 새 이력 없는 동일 SYNTHETIC Corpus를 쓴다.
4. 완료·정책 준수·기존 로컬 호출 한도 같은 기능 조건을 확인한다. 근거를 못 찾으면
   replay_failed로 남기고 승인할 수 없다. 기존 사실에 맞추려고 자료 날짜를 고치지 않는다.
5. proposed 후보를 사용자에게 비교 표시한다. 승인 전 현재 버전은 유지한다.
6. 승인 시 transaction에서 기준 버전·Legacy 선호 해시·동의 피드백 스냅샷이 여전히 같은지
   확인한다. 바뀌었거나 이미 적용한 후보는 거부한다. 새 버전을 저장하고 다음 조사부터 사용한다.
7. 롤백은 이전 선호를 복사한 **새 버전**을 만든다. 과거 버전이나 감사 기록을 덮어쓰지 않는다.

예전 공개자료를 사용한 조사를 Replay해도 실제 원문을 재수집하거나 그 자료의 품질을
재현하지 않는다. 원래 조사 Trace는 피드백 스냅샷에 보존하고, before/after Replay Trace는
별도로 표시한다. 두 Replay 사이의 기능 비교와 원래 조사 결과를 혼동하면 안 된다.

## 기술조사 선호 스키마

| 필드 | 허용 값·의미 |
|---|---|
| preferred_apps | OpenAlex, KIPRIS Plus, OpenDART, POSCO IR의 APP ID 목록 |
| preferred_apis | 위 APP의 search_works/search_patents/list_disclosures/search_materials |
| lookback_months / result_limit | 6/12/36/60개월, 1~10건. 현재 Environment 범위를 우선 적용 |
| sort | APP별 정렬. OpenAlex date_desc/relevance/citations_desc, KIPRIS date_desc, IR date_desc/relevance |
| depth / technical_detail / business_detail / financial_detail | brief/detailed 분석 선호. 실행 예산·권한을 바꾸지 않음 |
| criteria | 실험 조건, 재현성, 청구항 범위, 조건을 맞춘 비교, 사업화, 재무 위험의 allowlist 값 |
| report_format | bullets/table/explanation. Tool OP와 별개 |

OpenDART Registry에는 sort OP가 없으므로 해당 선호를 허용하지 않는다. 권한, 보안 등급,
allowed_sources, 사용자/프로젝트 ID, 자유 지시문과 임의 API는 선호로 저장할 수 없다.
기간은 현재 서버 cutoff에서 계산한다. quick에서는 기존 1년/최대 3건, deep에서는 기존
2022년 이후/최대 5건보다 넓어지지 않게 안내한다. 선호가 현재 Environment를 바꾸지 않는다.

## 실제 컨텍스트와 Tool 선택의 경계

Research 시작 때 프로젝트의 활성 버전을 한 번 읽어 해당 조사 동안 고정한다.
기존 Profile/Environment/승인 선호/이력에 research_persona, persona_revision,
persona_guidance를 추가했다. 응답, input_snapshot, 각 Tool의 input_provenance와
tr_turns에 사용 버전을 남긴다. 중간에 Persona를 갱신해도 진행 중인 프롬프트를 다시 만들지 않는다.

실제 Real/approved_public 경로는 이 컨텍스트를 모델에 제공할 뿐, APP/API/RP/OP를
서버에서 바꾸거나 호출하지 않는다. 역할별 Tool Schema도 Persona 승인 전후 동일하다.
모델은 선호 밖의 다른 **허용 도구**를 선택할 수 있고, 호출은 계속 서버 P1 검사를 거친다.
현재 명시 요청과 Environment, 서버 정책이 과거 선호보다 우선한다.

기존 Mock responder에는 전용 선호-following fixture를 추가했다. 이 fixture만 선호로 검색
APP/API·query 관점·기간/limit/sort와 보고서 표현을 바꾼다. Real에서 이 선택 규칙을 호출하지 않는다.
Mock의 명시 요청 인식은 기존 '논문만', '재무 중심' 표현을 유지한 범위이며 임의 자연어
요청 충돌 해결이나 실제 모델의 지시 준수 능력을 검증한 것이 아니다.

분석 기준을 더 자세히 보라는 선호와 근거 없는 우열 판단 보류를 컨텍스트에 넣지만,
기존 grounding/권한 규칙을 선택 가능한 선호로 약화시키지 않는다. 보고서 형식은 모델
입력의 표현 선호이고 API OP로 전달되지 않는다.

## 보안과 PUBLIC 승인

- 모든 읽기/쓰기·후보·활성화·롤백은 소유자와 현재 프로젝트 접근을 확인한다.
  후보/승인/롤백에는 전용 Persona scope도 요구한다. 현재 프로젝트 접근 구현은 기존 개발
  fixture 기반이며 전사 SSO/실 프로젝트 ACL을 새로 구현하지 않았다.
- 프로젝트별 Persona와 피드백을 분리한다. 기존 전역 source_focus 간편 승인 API는
  호환성을 위해 유지하며 해당 값을 덮어쓰지 않는다. 그 값이 바뀌면 이전 후보가 stale이 된다.
- 새 버전과 롤백은 기본 PRIVATE다. 자유 의견·후보·Replay 보고서를 외부 LLM으로 보내지 않는다.
- 기존 Real은 PRIVATE 선호를 차단한다. approved_public은 기술조사 Persona 레코드도 별도의
  preference Memory subject로 승인하고, 전송마다 현재 저장 버전을 다시 대조한다.
- 버전 숫자도 승인 해시에 포함된다. 같은 선호로 롤백해도 과거 승인 해시를 재사용하지 않는다.
  분류/외부 처리 승인은 별도 관리자 절차이며 사용자 후보 승인이 이를 대신하지 않는다.
- public_synthetic 인자는 기존 PUBLIC 합성 테스트 계약을 확인하는 서버/테스트용 명시 옵션이다.
  UI에 노출하지 않으며 실제 PRIVATE 정보를 PUBLIC으로 분류하는 수단으로 사용하면 안 된다.
- 원장·유료 한도·PUBLIC 두 질문 제한·공개자료 처리 기본 비활성/비용 상한 0은 변경하지 않았다.
  후보 Replay는 임시 앱과 로컬 Mock만 사용하며 운영 usage.json이나 실제 Connector를 연결하지 않는다.

## 실행 예제: 기능 Stub에서 확인한 변화

동일 질문: `수소환원제철을 비교 조사해주세요.` / 연구소 / quick / 합성 기준일 2026-10-01.

| 상태 | 조사 행동 |
|---|---|
| v1, 기존 papers_only 선호 | OpenAlex 검색·Read, 최근 1년, limit=3, date_desc |
| 네 조사에서 확인한 구조화 피드백 | 논문+특허, 실험 조건·재현성·청구항·조건을 맞춘 비교, limit=2, 논문 relevance, 표 형식 |
| 후보 생성 후 승인 전 | 활성 v1 유지. 비교 화면에 격리된 before/after Trace 표시 |
| 명시 승인 후 v2 | Mock이 OpenAlex+KIPRIS 검색·Read 선택, limit=2, 논문 relevance/특허 date_desc, 분석 기준·표 표현 반영 |
| v1 선호로 롤백 후 v3 | Mock이 다시 OpenAlex만 선택. v2와 승인·롤백 이력 보존 |

기간은 기존 근거가 있는 2025-10-01~2026-09-30을 유지했다. 6개월로 줄인 별도 후보는 현재
합성 자료가 해당 기간에 없어 Replay 실패로 처리했다. 새 정답·성과 수치를 만들지 않았다.

Streamlit에서 피드백 작성, 후보 생성/비교, 승인/거절, 이력, 이전 버전 복원이 가능하다.
각 보고서에 실제 사용한 Persona 버전을 표시한다. 버튼의 승인은 다음 조사 선호만 변경한다.

## 아직 검증되지 않은 것

실제 GPT-4o mini가 Profile·Environment와 선호를 종합해 더 적절한 도구/검색을 고르는지,
자연어 피드백을 이해하는지, 상세 분석·보고서 품질이 나아지는지는 미검증이다. 현재 후보
생성은 구조화 값의 제한된 합의 방식이며 무제한 자연어 최적화나 모델 학습이 아니다.
실제 모델 실험에는 현재 반출 승인·Memory 재승인·운영 예산 조건을 별도로 충족해야 한다.

초기 Replay는 단일 확인 사례와 합성 Corpus를 사용한다. 적합한 전문가 검수, 다양한 업무
환경, 충돌/망각 정책, 저장 스냅샷 용량·보존/삭제, 다중 worker 프로젝트 권한 동기화는 후속 작업이다.
검사 결과는 [PERSONA_ALIGNMENT_VALIDATION.md](PERSONA_ALIGNMENT_VALIDATION.md)에 구분해 기록한다.
