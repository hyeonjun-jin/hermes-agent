# 개인화 기술조사 Agent 전환 계획

설계 기준: `0874e772`, `feat/persona-gpt4o-mini-validation`. 작성일: 2026-11-15.
이번 변경은 이 문서와 [BENCHMARK_DESIGN.md](BENCHMARK_DESIGN.md)뿐이다.
코드, 기존 Mock, 사용량 원장, 호출 제한은 그대로 둔다. 아래 Registry와 데이터셋은
구현된 기능이 아니라 다음 단계의 계약이다. 실제 포스코 내부 자료는 사용하지 않는다.

## 1. 목표와 연구 질문

포스코홀딩스 임직원이 같은 기술을 물어도 필요한 정보원과 판단 기준은 다르다.
연구소 박사는 원리·실험·특허를, 전략실은 경쟁 구도·사업화를, 재무팀은 투자 규모와
손익·현금흐름 위험을 확인해야 한다. 여기에 마감·프로젝트·보안·보고 대상이 달라지면
선호하던 정보원을 쓰지 못하거나 조사 깊이를 줄여야 한다.

연구 대상은 **Profile과 현재 Environment를 함께 반영한 조사 행동**이다.
출력 문체를 바꾸는 것만으로 개인화에 성공했다고 평가하지 않는다.
질문 → 조사 계약 → Tool/API 선택 → 검색 조건 → 근거 수집·검증 → 보고서 순서로 본다.

- RQ1: Profile+Environment가 각각만 주어진 경우보다 APP/API와 검색 파라미터 선택을 개선하는가?
- RQ2: 둘이 충돌할 때 현재 업무 조건과 보안을 지키면서 개인의 판단 기준을 유지하는가?
- RQ3: 확인된 과거 Memory가 현재 조건과 중복되지 않는 검색 선호를 보완하는가?
- RQ4: 개선이 보고서 형식이나 더 많은 호출 때문이 아니라 실제 검색 행동에서 나타나는가?

ToolSpectrum의 APP/API/RP/OP 평가 단위와 Profile·Environment 분리를 가져온다.
PersonaAgent에서는 Episodic/Semantic Memory와 행동을 연결하는 구성을 참고한다.
전자의 일반 도구 선택을 기술조사로 좁히고, 후자의 Persona를 보안 정책의 근거로 쓰지 않는다.
원 논문을 그대로 재현하는 실험은 아니며, 본 설계의 점수와 원 논문의 점수는 직접 비교하지 않는다.

## 2. 현재 시스템: 재사용과 변경

| 구성 | 현재 코드에서 확인한 동작 | 재사용할 부분 | 기술조사 전환 시 필요한 변경 |
|---|---|---|---|
| Profile/Persona | `data.py`의 세 가상 사용자; `store.py:build_persona`가 format/language/project 및 승인 focus를 제한적으로 구성 | 명시 선호 allowlist, 버전과 세션 Snapshot | 역할·전문성·관심 지표·근거 선호를 구조화. 역할명만으로 선호나 권한을 추정하지 않음 |
| Episodic Memory | `MemoryStore.search`: 사용자 범위 SQLite, 어휘 중복 검색, provider는 confirmed episode를 사용 | 사용자 격리, 확인된 이력만 참고, memory ID 추적 | 조사 조건·채택/기각 이유·시각·유효기간·프로젝트 범위를 저장. 과거 환경을 현재로 오인하지 않음 |
| Semantic Memory | 사용자별 JSON; 명시 format/focus를 Persona에 반영 | 승인된 안정적 선호와 롤백 | 관할·선호 지표·근거 수준·제외 관심사. 현재 보안·마감·문서 권한은 저장된 선호로 덮어쓰지 않음 |
| 검색 | `MockEnterpriseData.search`: tag 일치+어휘 교집합; 실제 vector RAG 아님 | backend Protocol, trace, 빈 검색 결과 처리 | 5개 정보원 Registry, 정규화 인자와 출처별 retrieval. 기존 6개 문서는 기술조사 평가셋으로 재명명하지 않음 |
| Environment | 프로젝트 stage/constraint 조회, 과거 Snapshot과 현재 조회 구분 | 별도 관측 근거, 권한 검사 | 목적·프로젝트·마감·보안·보고 대상·접근 정책·자료 기준일을 조회하는 계약 |
| Research | native Hermes delegate_task, 허용된 문서 검색과 ID 전달 | 역할 scope, 출처 원문 보관 | 조사 계약과 현재 환경을 **검색 전** 전달. 현 구조는 Analysis 단계에서 환경을 읽어 Research 개인화에는 늦음 |
| Analysis | Environment를 별도 조회하고 문서와 함께 판단 | 문서와 환경의 출처 분리 | 실험 조건 비교, 경쟁 기술 비교, 재무 계산·가정 검토를 역할별로 수행 |
| Verification | 검색했던 원문을 권한 확인 후 다시 읽고 Environment와 대조 | 자식 요약을 그대로 믿지 않는 재조회, 미확인 표기 | 논문·특허·공시의 주장 종류, 수치 단위/기간/법인, 최신성, 인용 span 검증. 특허는 성능 입증이나 FTO 결론이 아님 |
| 피드백 Alignment | `PreferenceAligner`: 동의된 4개 이상 이력, 3개 이상 학습+마지막 held-out; format/focus 투표와 deterministic Mock replay; 승인 후 반영 | 제안/평가/승인/롤백 분리, 자동 활성화 금지 | 검색 실패 원인과 보고서 취향 피드백 분리. 정책·사실을 학습 선호로 바꾸지 않음. 현재 구현은 실제 LLM 최적화 증거가 아님 |
| 출력·근거 감사 | raw_answer / presentation_input / answer 분리; 근거 패턴 감사와 로컬 표 보정 | 원응답과 보정 구분, 문서 미발견≠사실 부재 | 인용별 claim ledger, 검색 행동과 renderer 평가 분리. 기존 패턴 검사는 의미적 사실 검증을 보장하지 않음 |
| 런타임·예산 | 세션별 상태, 턴마다 AIAgent 생성; host coding/probe off; 기존 validation/delegation 한도 | Mock 실행 경계와 원장, supported plugin/provider 확장 | 장기 세션 날짜·프롬프트 수명, 다중 worker 예산 예약, 인증 주체 전파부터 정리. Hermes 코어 수정 없이 설계 |

관련 파일: `persona_prototype/{app,provider,store,multi_agent,alignment,alignment_store,
web_sessions,evidence,fact_grounding,comparison_controls,runtime_config}.py`.
현재 OwnerOnly/scopes는 개발용 소유자 경계이며 사내 문서별 ACL·SSO 구현이 아니다.
기존 Alice/Bob/Carol은 유지하고 새 역할은 별도 합성 벤치마크 Profile로 정의한다.

## 3. Profile과 Environment의 책임

| 구분 | 필드 | 신뢰·갱신 원칙 |
|---|---|---|
| Profile | role, expertise, evidence_priorities, decision_criteria, preferred_jurisdiction, language | 사용자 확인 또는 승인된 Semantic Memory; 직급만으로 권한 부여 금지 |
| Environment | purpose, project_id, deadline, classification, audience, as_of, allowed_sources, allowed_projects | 업무 시스템/정책 서버가 제공하는 현재 Snapshot; observed_at/version 포함 |
| Memory | 과거 요청, 승인 선호, 채택 이유, observed_at, expires_at, project_scope, consent | 최신 명시 요청과 현재 환경보다 우선하지 않음; 미확인 과거 답은 사실 근거에서 제외 |
| ReportOptions | format, length, sections, audience_language | 검색 API 인자가 아님. 본 실험에서는 고정하고 형식 실험에서만 변경 |

우선순위는 권한·반출 정책 → 현재 명시 요청 → 현재 Environment → 확인된 Profile →
유효한 Memory → 일반 기본값이다. 보안과 요청이 충돌하면 안전한 범위로 축소하고 한계를 알린다.
RESTRICTED는 검색뿐 아니라 모델 입력·로그·캐시의 외부 반출도 막는 조건이다.
실제 도입 시 승인된 사내/격리 추론 경로가 없으면 원문을 모델에 전달하지 않고 작업을 중단한다.
현재 벤치마크는 모두 로컬 합성 fixture여서 외부 모델에 비공개 자료를 전송하는 실험이 아니다.
서버는 실행 시 다시 정책을 확인한다. 모델이 `classification=public`을 출력해도 승인이 되지 않는다.
누락된 마감·프로젝트를 Memory로 확정하지 말고 질문하거나 제한된 기본 조사임을 밝힌다.

초기 주제는 H: 수소환원제철의 유동층·샤프트로 비교,
B: 이차전지 양극재의 고니켈 NCM·LFP 비교로 제한한다.
전자는 공정·수소/전력 비용·실증 수준, 후자는 성능/수명·소재 공급·투자 위험을 함께
다룰 수 있어 같은 질문의 역할별 차이를 확인하기 좋다. 다른 철강 공정·음극재·전고체
전반으로 범위를 넓히지 않는다. 어느 기술의 우월성이나 실제 포스코 투자 계획을 전제하지 않는다.

## 4. 목표 흐름과 출력 계약

1. 서버가 인증 주체·Environment·허용 Toolset을 결정한다. 세션 시작 시 Registry 버전을 고정한다.
2. Profile과 허용된 Memory를 읽고 조사 계약을 만든다. 범위·지역·기간·필요 근거·정지 조건을 명시한다.
3. Research가 APP/API/RP/OP 계획을 제출한다. 외부 query에는 공개 용어만 넣고 내부 코드·수치는 제거한다.
4. 정책 validator가 인자·권한·반출·예산을 검증한다. 거부된 호출을 다른 API로 우회하지 않는다.
5. Research가 근거를 수집하고 Analysis가 비교·가정을 정리한다. Verification이 원문·환경·단위를 확인한다.
6. 고정된 보고서 형식으로 렌더링한다. 피드백은 검색 행동과 출력 취향을 별도로 수집한다.

```json
{
  "decision": "execute",
  "research_scope": {"topic": "H", "depth": "quick", "as_of": "2026-10-01"},
  "actions": [{"app": "openalex", "api": "search_works", "rp": {"query": "hydrogen iron reduction fluidized bed shaft furnace"}, "op": {"from_date": "2025-10-01", "to_date": "2026-09-30", "sort": "date_desc", "limit": 3}}],
  "parameter_provenance": {"actions[0].op.from_date": "environment:E1"},
  "report_options": {"format": "fixed_sections", "language": "ko"},
  "uncertainties": ["검색 전이며 기술 성능은 아직 확인하지 않음"]
}
```

실행 완료 후에는 action_id, 상태, 비용, evidence IDs, 재검색 이유를 별도로 붙인다.
`decision`은 execute/clarify/partial/deny 중 하나다. 계획을 실제 호출·완료로 기록하지 않는다.
Environment와 역할별 Schema는 세션 내 고정하고 관측값은 tool message로 전달한다.
환경·정책의 중요한 변경은 새 작업 경계를 만들되 권한 취소는 기존 세션에도 즉시 강제한다.

## 5. Tool Registry v0: 모델 계약

APP은 정보원 애플리케이션, API는 그 안의 동작, RP는 해당 API의 Schema 필수 인자,
OP는 선택 인자다. **OP라도 현재 사례의 정답을 만족하려면 특정 값이 필요할 수 있다.**
예를 들어 API에서 생략 가능한 기간이 Environment의 기준일 때문에 필수 평가 항목이 된다.
반대로 provider 인증키·principal·ACL·정책 버전은 모델 RP/OP에 넣지 않는 서버 컨텍스트다.

아래 이름은 내부 adapter의 정규화 이름이다. 공급자의 공식 endpoint/인자명과 동일하다는
뜻이 아니다. 입력은 모두 closed object(`additionalProperties=false`), RP 필드만 required다.
검색 조건에는 format, report_length 같은 보고서 옵션을 넣을 수 없다.

### 타입과 공통 출력

- `S`: 비어 있지 않은 string(최대 500자), `ID`: Registry/fixture에 등록된 ID string.
- `Date`: YYYY-MM-DD, `Year`: 4자리 연도 string, `N`: integer 1..10.
- `Range`: from_date≤to_date≤환경 as_of의 자료 마감일. 모델이 미래 자료를 요구하면 거부한다.
- `Sources`: 각 source_id에 origin_app, canonical_id, title, published_at(nullable), retrieved_at,
  snapshot_version, locator, content_hash, classification, coverage를 붙인다.
- `SearchResult`: `{status:ok|empty|denied|unavailable|partial, items:Sources[], next_cursor:string|null,
  query_echo:object, coverage:string[], cost:{mock_units:int}, warnings:string[]}`.
- `ReadResult`: 같은 status/cost/warnings + `source:Sources|null,
  passages:[{span_id:ID,text:string,locator:string}]`. 없는 초록·본문은 null/빈 배열로 표기한다.
- `FinancialResult`: 같은 status/cost/warnings + `source:Sources|null,
  rows:[{account_id:ID,label:string,value:string|null,unit:string,currency:string,period:string,
  fs_div:CFS|OFS,is_estimate:boolean,span_id:ID}]`. 소수는 string으로 보존한다.
- 오류와 empty를 구분한다. 다음 페이지도 별도 호출이며 cursor는 opaque string이다.
  items는 limit 이하이며 denied 응답에는 제목·건수·ID 같은 비인가 메타데이터를 넣지 않는다.

| APP | API | RP: 이름·타입 | OP: 이름·타입과 기본값 | 출력 | 허용 역할/용도 |
|---|---|---|---|---|---|
| openalex | search_works | query:S | from_date/to_date:Date(미지정), types:array[article,review](전체), open_access:boolean(미지정), language:ko/en(미지정), sort:date_desc/relevance/citations_desc(relevance), limit:N(3), cursor:string(미지정) | SearchResult | 모든 역할; 학술 근거 탐색 |
| openalex | read_work | work_id:ID | include_abstract:boolean(true) | ReadResult | 검색으로 확인한 논문 메타·초록; 전문 획득을 보장하지 않음 |
| kipris_plus | search_patents | query:S, jurisdiction:KR | applicant:S(미지정), ipc:array[S](미지정), from_date/to_date:Date(공개일; 미지정), sort:date_desc/relevance(relevance), limit:N(3), cursor:string(미지정) | SearchResult | 모든 역할; 첫 버전은 한국 공개·등록공보만 |
| kipris_plus | read_patent | application_id:ID | include_claims:boolean(false) | ReadResult | 승인된 fixture의 청구항·서지; 권리 유효성/FTO 판단은 별도 범위 |
| opendart | list_disclosures | corp_code:8자리 string, from_date:Date, to_date:Date | report_type:annual/quarterly/material(all), keyword:S(미지정; adapter 후필터), limit:N(3), cursor:string(미지정) | SearchResult | 공시 목록과 문서 ID; keyword는 공급자 native 인자라고 가정하지 않음 |
| opendart | read_disclosure | receipt_no:ID | section:S(미지정) | ReadResult | 공시 본문·주석의 해당 근거 |
| opendart | read_financials | corp_code:8자리 string, bsns_year:Year, reprt_code:11011/11012/11013/11014, fs_div:CFS/OFS | account_ids:array[ID](전체에서 서버 한도 적용) | FinancialResult | 재무 수치; 기준 기간·법인·연결/별도 확인 |
| posco_ir | search_materials | query:S | from_date/to_date:Date(미지정), kind:earnings/strategy/all(all), language:ko/en(ko), sort:date_desc/relevance(relevance), limit:N(3), cursor:string(미지정) | SearchResult | 포스코홀딩스 공식 IR만; 시장 전체의 독립적 수요 전망은 아님 |
| posco_ir | read_material | material_id:ID | pages:array[integer≥1](미지정) | ReadResult | 등록된 공식 IR 원문 locator; 임의 URL 다운로드 금지 |
| internal_mock | search_documents | query:S, project_id:ID | evidence_kind:experiment/strategy/financial/all(all), from_date/to_date:Date(미지정), sort:date_desc/relevance(relevance), limit:N(3), cursor:string(미지정) | SearchResult | 서버가 principal별 ACL 먼저 적용. 현 코드에는 없는 미래 Mock adapter |
| internal_mock | read_document | document_id:ID | sections:array[S](미지정) | ReadResult | 매번 ACL 재검사; 다른 프로젝트·폐기 권한 접근 거부 |

모든 read ID는 이전 검색/서버가 제공한 허용 evidence catalog에서만 가져온다.
공시 재무조회처럼 검색 ID가 필요 없는 API도 corp_code를 승인된 entity catalog와 대조한다.
금융 수치를 검색 query로 대체하거나 IR의 계획 수치를 공시 실적으로 바꾸지 않는다.

### 환경·Memory·보고서의 보조 계약

이 세 가지는 APP/API 선택 점수에서 제외하지만 비용과 보안 점수에는 포함한다.

| 컴포넌트 | 입력 | 출력/제약 |
|---|---|---|
| environment.snapshot | `{project_id:ID}` | `{project_id,purpose,deadline,classification,audience,as_of,allowed_sources,allowed_projects,policy_version,observed_at}`; 사용자는 서버가 바인딩 |
| memory.recall | `{query:S, limit?:integer 1..4}` | `{episodes:[{id,confirmed,consent,project_scope,observed_at,expires_at,preference,evidence_refs}], semantic_version}`; 과거 기술 수치는 현재 정답 근거로 불가 |
| report.render (로컬) | `{claims:[{text,evidence_refs,uncertainty}], report_options:{format:fixed_sections/table/bullets,language:ko/en,sections:array[S],max_words:integer 100..2000}}` | `{raw_answer,presentation_input,answer,correction_log}`; 수집/사실성 점수에는 raw claims 사용 |

### 실제 정보원과 연결할 때의 차이

| 정보원 | 확인한 공개 문서 범위 | 다음 단계에서 확인할 사항 |
|---|---|---|
| OpenAlex | Works 목록/상세와 검색·필터 제공 | 날짜·types·sort 매핑, 초록 결측, 버전별 파라미터명·인증·이용 한도 |
| KIPRIS Plus | 국내 특허·실용 공개/등록공보 검색·서지·전문 API 안내 | 서비스 신청/이용 조건, 실제 operation/필드, 공개일 필터, 전문·상태 범위. 해외 검색은 v0 제외 |
| OpenDART | 단일회사 전체재무제표 `fnlttSinglAcntAll.json` 개발가이드 | list/본문 adapter, 기업코드 조회, 재무 기간과 단위, key·rate limit. key는 서버 보관 |
| 포스코홀딩스 IR | 공식 IR 자료실 존재 | 공개 API는 확인하지 않았음. 공식 자료 수동 등록 catalog→향후 허용된 수집 adapter; OpenDART와 중복 근거 처리 |
| 사내 Mock | 합성 DB 설계만 | 문서별 allowlist, 프로젝트/조직 경계, 권한 취소·조회 감사. 실제 내부 DB라고 표기하지 않음 |

일반 웹/상용 시장조사 Tool은 첫 Registry에 넣지 않는다. 따라서 시장 규모·해외 경쟁사
실적을 충분히 확인하지 못하면 그 한계를 답해야 한다. 다섯 정보원으로 모든 질문에
충분히 답할 수 있다는 가정은 하지 않는다.

## 6. 구현 우선순위와 완료 기준

| 순서 | 다음 작업 | 완료 기준 |
|---|---|---|
| P0 | 18개 사례·gold·정책·합성 근거를 사람 검수로 확정 | 사례 상속을 해석한 완전한 JSON, 금지 호출/대안/필수 증거에 평가자 합의. 현재는 명세만 존재 |
| P1 | Registry validator와 offline adapter, 환경 선조회 | 누락 RP/허위 ID/분류 오입력/외부 반출/초과 예산 거부. 기존 회귀 유지 |
| P2 | 고정 모델 호출 없이 plan scorer·retrieval replay | gold/대안/empty/deny/future/ACL fixture와 점수 단위 테스트; 모델 실행 성능 주장 금지 |
| P3 | Research→Analysis→Verification 연결 | 동일 Registry와 현재 환경으로 계획·실제 호출·근거 ledger 연결, 세션 내 surface 유지 |
| P4 | Memory ablation과 검색 행동 Alignment | 평가 이력 유출 없이 시계열 분리, 현재 조건과 충돌하는 Memory 무시, 승인/롤백 유지 |
| P5 | 승인된 소규모 모델 실험 및 실제 connector 검증 | 별도 실행 승인·예산 확정 후 진행. 기존 호출 한도를 임의 확대하지 않음 |
| P6 | 사내 서비스 조건 | SSO→서버 principal, 후보 검색부터 ACL, 분산 원장·세션 격리·반출 정책·부하 검증 |

18×4 조건×반복 실행 수는 평가 표본 수이지 기존 API 한도로 바로 실행 가능한 요청 수가 아니다.
역할별 호출과 재시도가 추가되므로 우선 offline deterministic replay로 검증하고 모델 실험은 별도 계획한다.

## 7. 차별화 가능성과 미검증 가정

차별화 후보는 역할별 말투가 아니라 **같은 기술 질문에서 검색 행동이 바뀌는 이유를
Profile/Environment/Memory로 추적**하고, 보안과 마감이 선호를 제한할 때의 준수까지
함께 평가하는 것이다. 논문·특허·공시·IR·내부 근거의 서로 다른 증거 효력을 검증하는
다단계 조사라는 점도 검토할 만하다. 기존 연구보다 새롭거나 우수하다는 결론은 아직 없다.

검증되지 않은 가정은 세 역할의 합성 Profile이 실제 수요를 대표한다는 점, 2개 주제만으로
일반화 가능하다는 점, gold 대안이 충분하다는 점, Memory가 현재 정보보다 추가 이득을
준다는 점, 세 역할 구조가 단일 Agent보다 비용 대비 낫다는 점이다. 실제 임직원 인터뷰,
전문가 annotation, 더 넓은 holdout 및 동일 예산 비교가 필요하다.

## 참고한 공개 자료

설계 확인을 위한 논문/공식 개발 안내만 소량 조회했다. 기술 논문·IR·내부 자료의 실제
벤치마크 코퍼스를 수집한 것은 아니며, 이번 작업에서 모델 API는 호출하지 않았다.

- ToolSpectrum, Cheng et al., Findings ACL 2025: https://aclanthology.org/2025.findings-acl.1063/
- PersonaAgent, Zhang et al., Findings ACL 2026: https://aclanthology.org/2026.findings-acl.1315/
- OpenAlex API: https://help.openalex.org/api/ 및 https://help.openalex.org/api/endpoints/
- KIPRIS Plus 국내 공보 안내: https://plus.kipris.or.kr/portal/data/service/DBII_000000000000001/view.do
- OpenDART 재무제표 개발가이드: https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS003&apiId=2019020
- 포스코홀딩스 공식 홈페이지/IR 입구: https://posco-inc.com/
