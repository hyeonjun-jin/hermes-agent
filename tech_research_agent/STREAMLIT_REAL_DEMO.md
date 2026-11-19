# Streamlit 실제 API 공개 논문 시연

기존 `tech_research_agent/ui.py`에서 **실제 API 시연** 모드를 선택한다.
별도 보고서 스크립트가 아니며 `quick_live_demo.py`를 호출하지 않는다.
이번 개발 검증은 전부 Stub/MockTransport다. 실제 GPT-4o mini/OpenAlex 호출을 완료했다는
뜻이 아니며 현재 배포 설정·관리자 승인·연결 성공 여부를 가정하지 않는다.

## 연결 구조

```text
Streamlit 채팅 (검수된 가상 Profile A/B + 고정 공개 질문 + 과금 동의)
  → 서버 활성화 + PaperDemoApproval (매 전송 재확인)
  → 새 임시 ResearchApplication (운영 Persona/Memory를 읽지 않음)
  → 기존 Hermes Research → Analysis → Verification
  → ResearchProvider Function Calling → SourceAdapter (ACL/프로젝트/cutoff/예산)
  → OpenAlex search_works / read_work
  → 공개 메타데이터·초록 처리 경계 → 기존 RealAdapter/OpenAI HTTPS
  → 근거·보고서·로컬 개인화 TOP 3·Tool/토큰/비용 표시
```

내부 연결에는 기존 `approved_public` 실행 루프를 재사용하되, 오직 시연 서비스가
`PaperDemoAdapter`를 주입한 임시 앱에서만 별도 공개 시연 범위 정책이 동작한다.
기존 ApprovedPublicAdapter의 문서별 승인, Real 합성 자료 제한, LiveExecutionApproval,
일반 웹 UI 호출 한도는 바꾸지 않는다. 승인된 문서인 척 가짜 문서별 grant를 만들지 않는다.

시연 승인은 **코드에 고정된 공개 가상 Profile, 고정 질문, 명시한 OpenAlex 메타데이터·초록
처리 범위 전체**를 관리자가 검토하는 별도 opt-in이다. 일반 문서·개인정보·Persona 승인으로
사용할 수 없다. 승인에 동의할 수 없는 운영 환경에서는 시연 모드를 켜지 않는다.

## Profile·Persona·Memory·자료

- A/B는 동일한 철강/연구소/박사 연구원/공정·소재/평가 기준의 가상 Profile이다.
  A 관심사는 수소환원 반응 메커니즘, B 관심사는 수소환원 공정 최적화다.
- 기존 개발 UI에서 편집한 PRIVATE Profile을 가져오거나 PUBLIC으로 바꾸지 않는다.
- 운영 SQLite·승인 Persona·조사 이력·피드백은 로드하지 않는다. 임시 초기 Persona v1은
  선호가 비어 있으며 승인된 개인 Persona라고 주장하지 않는다. 이전 질문을 재전송하지 않는다.
- 프로젝트 H, quick PUBLIC Environment와 cutoff 2026-09-30 등 고정 개발 업무 조건을 사용한다.
  실제 사내 현재 프로젝트·마감이라는 의미가 아니다. UI에 검수 범위 전체를 표시한다.
- 초기 SYNTHETIC corpus와 다른 Connector/Tool Schema를 제거한다. OpenAlex만 실행한다.
  검색 결과의 ID만 Read하며 최신 Read/권한/기준일 검사를 기존 SourceAdapter가 수행한다.
- OpenAlex의 DOI/연도/제목/초록/URL만 사용한다. DOI는 제공된 메타데이터이며 별도 DOI resolve나
  PDF 전문 열람은 하지 않는다. 초록 부재·빈 결과·오류는 표시하고 자료를 생성하지 않는다.

Research의 검색어·Function Calling은 실제 모델이 생성한다. 특정 관심사에 맞는 논문이나
검색 인자를 코드가 강제로 선택하지 않는다. 시간/호출 예산 안에서 검색 후 최대 3개 Read를
병렬 Tool Calling으로 요청하도록 지침을 준다. 모델이 도구를 쓰지 않거나 한도 내에 완료하지
못하면 미완료로 표시한다. Analysis/Verification도 실제 응답이며 로컬 답변 대체가 없다.
확인된 후보에만 기존 `paper_ranking.py`의 관심사·직무·Persona·업무 조건 점수를 적용한다.
순위는 결정론적 heuristic이며 실제 LLM의 개인화 효과나 기술 우수성을 증명하지 않는다.

## 서버 설정: 기본 비활성

먼저 관리자가 UI의 `관리자 검수용 공개 전송 범위 (승인서 아님)`에서 Profile, 질문,
Environment, Tool Schema, 시스템 지침, 모델/옵션과 `scope_sha256`를 검토한다.
범위 표시는 네트워크 호출이나 승인서 생성 없이 가능하다.

서버 전용 `.streamlit/secrets.toml` 설정 예시(기본 비활성):

```toml
[technical_paper_demo]
enabled = false
approval_path = "/server-managed/paper-demo-approval.json"
```

`approval_path`는 관리자가 보관하는 별도 승인 파일이다. 다음은 **비활성 형식 설명**이며
실제 승인이 아니다. 프로그램은 이 파일이나 승인 기록을 자동 생성하지 않는다.

```json
{
  "approval_id": "administrator-chosen-demo-campaign",
  "approved_by": "실제 관리자 식별자",
  "actual_execution_approved": false,
  "source_access_approved": false,
  "public_processing_approved": false,
  "model_identity_reviewed": false,
  "scope_sha256": "관리자가 검수한 현재 공개 범위의 SHA256",
  "response_model_evidence_sha256": "응답 식별자 확인 자료를 검토한 SHA256",
  "max_new_calls": 6,
  "max_reserved_usd": 0,
  "approved_at": "관리자 지정 timezone-aware ISO8601 시각",
  "expires_at": "관리자 지정 timezone-aware ISO8601 만료 시각"
}
```

유료 실행을 별도로 승인받은 뒤에만 관리자가 네 승인 flag, 양수 비용 상한, 실제 식별자·유효
기간·해시를 확정하고 서버 `enabled=true`로 활성화한다. `max_new_calls`는 6 또는 12만 허용한다.
관측된 응답 ID `gpt-4o-mini-2024-07-18`은 정확한 allowlist로 검증하며 관측 사실을 실행 승인으로
취급하지 않는다. 알려진 빈 `annotations` 메타데이터만 허용하며 미검토 annotation은 차단한다.
승인 파일 변경·철회·만료는 다음 전송 전에 차단한다. 기존 시연 manifest와 다른 승인은
같은 원장에 자동 적용되지 않는다. 단순 재시작이나 승인 ID 변경으로 새 예산을 얻을 수 없다.

환경변수는 Codespaces Secrets/서버 secret manager로 전달한다. 키 값은 명령·보고서·Git에 넣지 않는다.

```bash
export PERSONA_BASE_URL=https://api.openai.com/v1
export PERSONA_MODEL=gpt-4o-mini
# PERSONA_API_KEY와 OPENALEX_API_KEY는 이미 서버 환경변수로 주입되어 있어야 함.
python -m streamlit run tech_research_agent/ui.py --server.address 0.0.0.0 --server.port 8501
```

Codespaces에서는 Ports 탭의 8501에서 **Open in Browser**를 선택한다. Secrets 추가 뒤에는
환경변수를 받은 터미널/프로세스로 재시작한다. Streamlit 설정을 바꾼 경우에도 서버를 재시작한다.
UI 선택 순서: `실제 API 시연` → 연구원 A/B → 수소환원제철 → 과금 동의 → 채팅창에
`수소환원제철 관련 주요 기술 논문을 추천하고 분석해 줘` 입력.

허용 질문은 이 고정 문장뿐이다. 업무 비밀이나 개인정보를 자유 입력해 외부 모델에 보내는
기능이 아니다. 연결 상태는 호출 전에는 설정/정책 확인과 **실연결 미검증**을 구분한다.
시연 결과 패널에서 실제 HTTP 상태·응답 식별자·검색/Read 결과를 확인한다. 별도 유료 health
check나 자동 연결 probe를 수행하지 않는다. 실패 시 Mock으로 전환하지 않는다.

## 별도 예산·원장·실패 처리

저장소의 `.technical-paper-demo/usage.json`, `manifest.json`, `report-*.json`만 사용하며 모두
Git에서 제외한다. 운영 usage.json 경로를 설정받거나 기존 원장을 재해석하지 않는다.
심볼릭/하드 링크 원장도 거절한다. 이 기록은 최초의 승인된 사용자 채팅 실행 때만 생성한다.

기존 ComparisonPlan/ComparisonBudget와 RealAdapter의 파일 잠금·전송 전 durable 예약·Payload
해시·엄격한 사용량 기록을 재사용한다. 두 Profile은 각각 독립된 임시 DB에서 실행되고 조사
DB는 종료 시 제거된다. 로그 writer가 늦게 임시 로그 폴더를 만들더라도 다음 조사에 재사용하지
않는다. 각 원장 조건은 A=v1, B=v2이며 Persona 버전 비교를 의미하는 명칭이 아니다.

- Profile당 최대 **6회 모델 요청**: Research 3, Analysis 1, Verification 2.
- 승인 상한 6이면 한 Profile 시연 1회, 12이면 A/B 각각 1회 가능. 질문 1회의 정상 경로는
  유료 HTTP 요청 **6회**이지 유료 요청 1회가 아니다. 출력은 요청당 512토큰 이하.
- 시작 전에 해당 6회 비용/호출 envelope를 검사한다. 기존 잠정 단가 입력 $0.15/M,
  출력 $0.60/M과 64KB Payload 상한의 보수적 예약은 **6회 $0.0594432**, **12회 $0.1188864**다.
  실제 청구액 추정은 공급자 반환 토큰으로 별도 계산한다. 최신 요율·서비스 청구는 관리자 확인이 필요하다.
- OpenAlex는 실행당 최대 12 source/tool units의 기존 정책을 유지한다. 일반적인 후보 3개
  검색/Read/검증은 7회 조회다. OpenAlex 요금은 미확인이며 OpenAI 비용에 섞거나 무료로 보고하지 않는다.
- 자동 외부 재시도 0. 첫 외부 오류·미승인 응답 모델·사용량 누락·반출 거부는 중단한다.
  실패/미결 예약·기존 실행 조건은 재시작해도 보존하며 자동 초기화/확대하지 않는다.
- 최종 전송 Payload는 해시와 승인된 Schema/Context로 검증한다. UI/별도 보고서에는
  실제 선택 Tool/RP/OP, 조회 자료·열람 범위, 역할별 원응답, 토큰·예약·비용을 기록한다.
  요청 헤더는 기록하지 않고 거부된 원문은 해시로 대체한다. 반사된 키도 제거한다.
- OpenAI는 기존 HTTPS/환경변수 인증과 Codex/Codespaces 네트워크 검사를 사용한다.
  OpenAlex 시연은 `api_key` query 인증을 사용하되 Trace URL에서 제거하고 HTTPX 로그도
  필터링한다. 기존 Connector의 기본 Bearer 동작은 유지한다. 가짜 네트워크 정책 파일을 만들지 않는다.

API 오류 응답은 원문을 노출하지 않는다. UI에서 중단 상태/Trace/원장을 확인하고 관리자가
미결 사용량을 확인해야 한다. 같은 Profile을 다시 입력해 유료 요청을 자동 반복할 수 없다.

## 실제 시연 전 GO/NO-GO

현재 코드는 실행 경로를 제공하지만 **실제 API 검증은 하지 않았다**.
관리자의 공개 Profile/자료 처리 범위·정보원 이용권한·모델 식별자·6회 또는 12회 호출/비용
승인, 환경변수, 실제 플랫폼 네트워크 허용, 사용자 과금 동의가 모두 필요하다.
승인 없이 서버 활성화·운영 원장 수정·유료 호출은 하지 않는다.

첫 승인은 `max_new_calls=6`으로 한 번의 채팅 흐름을 검증할 수 있다. A/B 실비교를 원하면
처음부터 별도 승인을 받은 12회 캠페인을 계획해야 하며, 소비한 6회 원장을 지우거나 상한을
수정해 확장하지 않는다. 모델이 검색/Read를 추가 요구하면 남은 예산에서 안전하게 중단할 수
있다. 실제 후보·순위·한국어 응답 품질·초록 제공률·API 접근 성공은 승인 후 관찰해야 한다.
