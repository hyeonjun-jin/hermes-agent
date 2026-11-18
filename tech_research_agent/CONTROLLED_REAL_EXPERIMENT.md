# GPT-4o mini 기술조사 Persona 통제 실험 준비

기준 `467c6e3722`, 2026-11-18. 이번 작업은 Offline 준비이며 실제 OpenAI·외부 정보원
API 호출은 각각 **0회**다. 운영 원장·한도·Hermes 코어는 변경하지 않는다.
현재 결론은 **실제 실험 NO-GO**다. 실행 권한이나 예산을 부여하는 문서가 아니다.

후속 승인으로 [비교 전용 신규 12회 경로](PAIRED_CALL_ALLOWANCE.md)를 구현했다. 아래의
calls<=4/역할당 2회 설명은 기존 일반 Real 경로에 해당한다. 새 경로는 Research 3회와
조건별 사전 검사를 제공하지만, 실제 API 실행·반출·비용 설정은 여전히 별도 승인 대상이다.

## 현재 Real 실행 조건과 한도

ResearchApplication은 기존 세 Hermes Agent Loop를 순서대로 실행한다. 별도 Main/
Orchestrator LLM 요청은 없다. 여기서 R/A/V 숫자는 Tool 실행 수가 아닌 모델 요청 수다.
여러 Tool Call을 한 응답에서 병렬로 선택해도 그 응답은 모델 요청 1회로 센다.

| 경로 | Research | Analysis | Verification | 조건당 / 두 조건 |
|---|---|---|---|---|
| 일반 검색 R3 | 검색 선택 → ID를 받고 Read 선택 → 원문을 받고 답변: 3 | 1 | Read 재검증 선택 → 답변: 2 | 6 / 12 |
| 재무 직접 조회 R2 | 검증된 회사 코드로 read_financials → 답변: 2 | 1 | 재무 행 재조회 → 답변: 2 | 5 / 10 |

이는 재검색·수정 없이 진행하는 최소 정상 경로의 예상치다. 추가 검색/검증 요청,
Tool 오류, 512토큰 출력 중단으로 더 필요할 수 있다. 현재 자동 외부 재시도는 0이며,
오류를 다시 시도해 완주시키는 예산은 없다. 모델이 R2를 선택하도록 서버가 정답 도구를
강제하면 APP/API 선택 비교가 왜곡되므로 R2는 **모델이 그 흐름을 선택한 경우의 시나리오**다.
논문·특허 선호 비교를 R2로 대체할 수 없다.

- PersistentBudget: 원장 전체 12회, 각 전문 역할 2회, main 2회. 본 앱은 main을 사용하지 않는다.
- RealAdapter.preflight: 기존 calls가 4회 이하일 때만 보수적 8회 workflow envelope를
  확보했다고 판단한다. failed 또는 pending이면 시작하지 않는다. 잔여량이 충분해 보여도
  이 사전 조건을 통과해야 한다. 재시작으로 누적 원장이나 역할 제한을 초기화하지 않는다.
- R3는 Research 3번째 요청을 외부 전송하기 전에 차단된다. 보통 2회 시도 후 failed로
  중단하므로 이 경로의 실제 유료 시도를 사전 검토 없이 시작하면 안 된다.
- R2 한 조건은 역할 제한에 들어간다. 그러나 빈 원장에서도 첫 조건 5회 후 두 번째
  preflight가 8회 envelope를 확보하지 못한다. R3도 역할 제한을 별도로 고쳐도 첫 6회 후
  같은 문제가 있다. 따라서 **현재 코드로 두 조건 연속 완주는 두 경로 모두 불가능**하다.

### 읽기 전용 원장 확인

현재 작업 환경에서 발견한 `/workspace/persona-web-real-state/usage.json`은 11회 기록,
잔여 1회, failed=false, pending=0이었다. 해당 파일이 Codespaces 기술조사 앱의 실제
canonical 원장인지 관리자가 추가 확인해야 한다. 다른 서버의 원장을 확인한 것은 아니다.

파일 SHA-256: `313419af1ed02e4c68f7ce724f3851414004b742435496b98fcfc0bf53731147`.
11개 모두 reported usage가 있고 입력 53,281 / 출력 1,139토큰, 기존 단가 추정 $0.00867555다.
reserved_usd_upper_bound가 없는 과거 항목 11개이므로 예약액을 0으로 간주하면 안 된다.
approved_public 비용 검사는 이런 미조정 예약 기록도 차단한다. 별도 관리자의 사용량/
예약액 조정 절차가 필요하며, 이번에는 원장을 읽기만 했다. 복사·초기화·자동 조정하지 않는다.

### 두 Real 경로의 구분

| 항목 | 기존 real | approved_public |
|---|---|---|
| 자료 | PUBLIC 합성 fixture만 | 승인된 실제 공개 Connector 자료와 허용 합성 자료 |
| 실제 Connector 동시 사용 | application에서 차단 | 서버 opt-in과 승인 후 가능 |
| PRIVATE Persona | 차단 | 원본은 PRIVATE 유지, 정확히 승인된 최소 표현만 전달 |
| Memory | 명시 PUBLIC_SYNTHETIC만 | 선호·각 이력 및 문서 의존성 별도 승인 |
| 비용 | 기존 누적 호출 제한 | 같은 호출 제한 + 별도 예약 비용 상한, 기본 0 |
| 질문·Environment | 두 지정 질문 / quick PUBLIC | 같은 지정 질문·PUBLIC 제한 유지 |

실제 공개자료 조사는 approved_public 경로가 필요하다. Persona 사용자 승인·Replay 통과는
반출 승인을 대신하지 않는다. 상세 경계는 [PREFERENCE_BOUNDARIES.md](PREFERENCE_BOUNDARIES.md).

## Persona v1/v2 비교 조건

사용자는 개발용 researcher, 프로젝트 proj-H, quick/PUBLIC, 질문은 정확히
`수소환원제철을 비교 조사해주세요.`로 고정한다. Profile, Environment(기준일·cutoff 포함),
초기 Episodic Memory, Legacy semantic, 서버 APP/API/OP 권한, 회사 Catalog, 정보원 설정,
모델 및 생성 설정을 동일하게 유지한다. 첫 조건이 저장한 새 이력을 두 번째에 넣지 않는다.
Mock은 기존 TechnicalMockReplay의 별도 임시 DB 두 개를 사용한다.

Offline fixture의 조건은 다음과 같다. 실제 사용자의 승인된 Persona를 만든 것은 아니다.

| 선호 | v1 label | v2 label |
|---|---|---|
| APP | openalex | kipris_plus |
| lookback_months / result_limit | 12 / 3 | 36 / 2 |
| technical_detail | brief | detailed |
| criteria | experimental_conditions | claim_scope |
| report_format | bullets | table |

여러 선호가 동시에 바뀌므로 개별 필드의 인과 효과를 분리하지 않는다. quick Environment가
lookback을 제한하므로 두 요청의 실제 검색 시작일이 같을 수 있다. 이러한 상위 정책의
clamp를 개인화 실패로 해석하지 않는다. 기존 이력은 관찰 정보이고 선호를 덮어쓰지 않는다.

### 메타데이터와 자료 통제의 한계

- Offline fixture에만 두 조건의 내부 revision을 2, 생성 시각·초기 episode 시각/세션/ID를
  동일하게 둔다. v1/v2는 보고서 label이며 운영 버전/승인을 조작하지 않는다.
- 실제 승인 버전은 각각의 revision과 공개 표현의 해시 승인을 유지해야 한다. 현재
  context에는 persona_revision, research_persona.version과 감사 정보가 포함되므로
  실제 버전 차이를 제거했다고 주장할 수 없다. 원래 승인 버전을 바꾸거나 승인 subject에서
  버전을 제거하면 안 된다. 실제 비교 시 버전 메타데이터는 교란 요인으로 명시한다.
- Offline 입력 해시는 application snapshot의 고정 필드에 대한 검사다. 전체 Hermes
  wire prompt의 host/session 메타데이터까지 동일하다는 증명은 아니다. 실제 실행 전에는
  반출 검사 이후 wire payload를 비밀 값 없이 검수하고 모델·temperature/top_p/seed의
  존재/부재, max_tokens, tools/Schema, prompt 차이를 기록해야 한다. 현재 앱은 생성 옵션을
  모두 명시하지 않으며 이번 작업에서 모델 기본값이나 Hermes 코어를 바꾸지 않았다.
- 실제 모델 alias gpt-4o-mini의 서버 snapshot·확률성은 완전히 고정되지 않는다. 현재
  1쌍 실험은 탐색 관찰이며 통계적 성능 개선이나 인과 증명이 아니다.
- 실제 검색 결과·회사 Catalog·원문이 시간에 따라 변한다. 공통 corpus/catalog hash와
  cutoff, 조회 시각, Read 범위, 원문 버전/hash를 기록한다. 각 조건에서 처음 조회된 서로
  다른 문서·메타데이터도 모두 승인되어야 한다. 자료 변화는 Persona 효과와 구분한다.

## 기록과 사람의 검토 기준

| 비교 항목 | 현재 Offline 산출물 / 실제 실행 시 추가 필요 |
|---|---|
| APP/API, RP/OP | outcomes.before/after.trace의 plan과 실제 result |
| 검색·Read | trace.result, evidence의 source_id, span·원문 근거; 실제 경로는 approval/hash/URL |
| Research / Analysis / Verification | stages의 역할별 raw_answer, error, checks의 숫자·인용 감사 |
| 원응답 / 보고서 | 모든 역할 raw_answer와 report를 별도 보존; 로컬 안내·보정과 모델 문장 구분 |
| Memory·입력 | initial_episodes, history, Profile/Environment/semantic, 고정 필드 해시 |
| 호출·토큰·비용 | Mock model_calls는 로컬 호출. 실제는 audit·누적 원장 차이, reported usage와 예약액 |

문서 인용·숫자·단위·기간·비교 조건·논문과 특허 주장의 차이를 원문과 사람이 대조한다.
형식 준수와 사실 정확성은 별도로 판단한다. 문서 부재와 미조회·미확인도 구분한다.
checks의 기계적 일치나 표 형식만으로 정확성·개선을 판정하지 않는다. 새 Scorer는 없다.

## 실제 실행 전 GO/NO-GO 체크리스트

아래 모두 충족하기 전에는 실제 모델과 외부 정보원을 호출하지 않는다.

- [ ] 관리자 지정 canonical 원장을 읽기 전용으로 확인하고 잔여량·failed·pending·예약액을
  검수한다. 이전 Backend를 중지하고 단독 소유·기존 파일 잠금을 확보한다.
- [ ] 별도 승인된 호출 계획이 **두 조건 모두**의 preflight·역할·누적 한도를 충족한다.
  한 조건만 실행하고 나머지가 막히는 예산이면 비교를 시작하지 않는다.
- [ ] OpenAlex 서비스 접근·범위/이용 조건, OpenDART 인증·조회/회사 권한, KIPRIS Plus
  상품/API 이용권한·키, POSCO IR Catalog/공개 PDF 취득·처리 권한을 정보원별 확인한다.
- [ ] 각 검색 표현과 Read 표현의 정확한 외부 처리 승인을 준비한다. OpenAlex는 전문이
  아닌 metadata/abstract, KIPRIS는 claims/bibliography, IR은 검수된 PDF 페이지 텍스트,
  DART는 허용된 공시/재무 행이다. 미지원 원문을 조회했다고 기록하지 않는다.
- [ ] 실제 회사 Catalog 행과 모든 문서 subject에 user/project/model/purpose, 정확한 hash,
  검수 범위, 이용 조건·외부 처리 승인, 유효기간·취소 상태가 유효하다.
- [ ] 두 PRIVATE Persona의 공개 가능 필드만 관리자가 최소 표현으로 승인한다. 원본·자유
  피드백·후보/Replay 보고서를 전송하지 않는다. 버전 변경/롤백 뒤에는 새 승인이 필요하다.
- [ ] 동일한 초기 Legacy 선호와 각 episode에 재전송 승인 및 문서 의존성이 있다.
  PRIVATE Legacy는 별도 승인 없는 자동 공개가 불가능하다. 한쪽 이력이 추가되면 중단한다.
- [ ] approved_public 서버 opt-in과 유효 grant, 양수 비용 상한이 명시 승인되어 있다.
- [ ] PERSONA_API_KEY는 서버 환경변수/Secrets에만 있다. 모델은 gpt-4o-mini, endpoint는
  https://api.openai.com/v1, Chat Completions JSON 응답이다. 이번 환경에서 세 변수 존재와
  모델/endpoint 일치는 확인했지만 키 유효성·계정 모델 접근·실제 연결은 확인하지 않았다.
- [ ] Codex 네트워크 정책 또는 실제 Codespaces의 egress·TLS·proxy 제약을 충족한다.
  정책 파일 생성/우회는 금지한다. 네트워크 probe도 이번에는 수행하지 않았다.
  현재 환경의 기존 Codex 정책은 읽기 전용 check_real_network 검사에 통과했다.
  이는 실제 HTTPS 연결 성공이나 Codespaces의 연결 가능성을 확인한 결과는 아니다.
- [ ] 모델의 실제 function Tool Calling, RP/OP JSON Schema 호환, finish_reason=length,
  usage 형식, 한국어·숫자/인용 응답, Hermes 오류 처리를 최소 승인 호출로 확인한다.
  기존 Alice 검증은 이번 기술조사+공개자료 경로의 연결 검증을 대신하지 않는다.
  REST의 JSON envelope와 모델의 구조화 출력 response_format은 다르다. 이번에는 후자의
  strict schema 지원을 검증하지 않았다. 공급자가 반환한 실제 model 식별자/fingerprint도
  현재 기술조사 감사 출력에서 완전히 수집하지 않으므로 향후 wire 검수 항목으로 남긴다.
- [ ] 자동 외부 재시도 0, 출력당 512토큰, 첫 오류 시 중단을 유지한다. pending/실패 기록과
  알려진 usage를 보존한다. usage 누락은 0원으로 처리하지 않고 비용 미확인으로 보고한다.

### 최소 변경 예산안 — 적용하지 않음

| 시나리오 | 신규 호출 계획 | 필요한 별도 승인 변경 |
|---|---|---|
| R3 두 조건 | 12 (R3/A1/V2 ×2) | Research cap 3, 조건당 envelope 6을 사용한 전체쌍 사전 검수 |
| R2 두 조건 | 10 (R2/A1/V2 ×2) | 역할 cap 유지, 조건당 envelope 5를 사용한 전체쌍 사전 검수 |

이는 각 조건 정상 최소 경로까지만 허용하는 제안이며 초과 시 미완료 중단한다. 현재 발견
원장의 11회는 그대로 보존하므로 누적 상한은 R3라면 최소 23회, R2라면 최소 21회가
필요하다. 단순히 총 상한만 늘려도 현재 preflight의 calls<=4 조건을 충족하지 못한다.
새 원장/별도 복사로 예산을 확보하지 않는다. 원장·reservation 조정, 해당 캠페인의 호출
승인 및 preflight 변경안을 관리자가 함께 승인해야 한다. 이번에는 어느 것도 적용하지 않았다.

### 예상 비용

기존 provisional 단가 $0.15/백만 입력토큰, $0.60/백만 출력토큰을 사용한다. 최신 가격은
실행 승인 시 별도로 확인한다. 실제 청구액은 이번에 발생하지 않았다.

- 공식: `입력토큰×0.15/1e6 + 출력토큰×0.60/1e6`.
- 예를 들어 각 요청 입력 5,000, 출력 512라면 R3 쌍 60,000/6,144토큰 약 **$0.0126864**,
  R2 쌍 50,000/5,120토큰 약 **$0.010572**다. 입력 5,000은 가정이지 측정값이 아니다.
- 64,000-byte payload 상한에서 기존 예약 공식의 보수적 요청당 상한은 $0.0099072다.
  R3 12회 약 **$0.1188864**, R2 10회 약 **$0.099072**의 신규 예약 여유가 필요하다.
  누적 비용 ceiling에는 조정된 기존 예약도 더해야 한다. 실제 요금과 예약액은 다르다.

## Offline 실행

기존 TechnicalMockReplay에 고정 initial_episodes와 Offline 전용 fixed_revision 인자만
추가했다. 일반 Alignment 호출의 기본 동작은 유지한다. 새 실행기는 이 Replay를 호출하며
실제 모델/Connector/원장 경로를 받지 않는다. 실제 실행 flag도 없다.
이 fixture의 PRIVATE semantic과 과거 이력은 유료 전송 승인이 아니므로 그대로 Real에
사용할 수 없다. 위 체크리스트에 따라 각각의 반출 가능 여부부터 검토해야 한다.

```bash
research_report_dir="$(python -c 'import tempfile; print(tempfile.gettempdir())')"
python -m tech_research_agent.controlled_comparison \
  --output "$research_report_dir/research-persona-controlled.json"
```

Hermes의 기존 개발·테스트 의존성이 필요하며 추가 패키지는 없다. 로컬 loopback Mock
서버만 사용한다. 출력 파일은 새 파일이어야 하며 usage.json과 기존 파일/심볼릭 링크를
덮어쓸 수 없다. 보고서의 actual_api_usage는 0이고 Mock 토큰을 유료 사용량으로 표시하지 않는다.

이번 Offline 실행에서 두 고정 입력 해시는 일치했다. 양쪽 모두 R3/A1/V2, 로컬 모델
요청 6회씩으로 완료됐고 v1은 OpenAlex/H-A01, v2는 KIPRIS/H-P01을 선택했다.
이는 선호를 따르도록 작성된 Mock의 배선·격리 확인이며 실제 LLM 선택이나 성능 결과가 아니다.
운영 버전 승인, 실제 공개자료 승인, 실제 유료 비교 실행기는 이번 범위에서 활성화하지 않았다.

## 이번 변경의 검증 결과

- 신규 비교·기존 Alignment·예산 테스트: 3개 파일 **43 passed**.
- 기술조사와 기존 Persona 전체, Hermes MemoryProvider/위임 범위 회귀: 31개 파일
  **563 passed, 0 failed**, 127.8초. 공식 scripts/run_tests.sh, 파일 재시도 0으로 실행했다.
- 정적 검사 scripts/check --base 467c6e3722: **19개 통과**.
- 비교 실행으로 생성한 자료는 임시 경로에만 기록했다. 운영 원장의 실행 전후 SHA-256이
  일치했다. 키 값은 출력하지 않았고 변경 5개 파일의 비밀 정보·DB/로그 포함 검사 결과는 0건이다.
