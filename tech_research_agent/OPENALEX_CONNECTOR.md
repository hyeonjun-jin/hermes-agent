# OpenAlex 공개 논문 Connector v1

기준: `5eca36d1`. 기본 실행은 기존 Offline Mock이다. 이번 작업에서 OpenAlex API와
OpenAI API는 호출하지 않았다. 공식 문서 웹 페이지만 확인했고, 실행 검증에는 직접 만든
OpenAlex 형태의 fixture와 `httpx.MockTransport`를 썼다. 실제 기업·논문 수치를 추가하지 않았다.

## 연결 구조와 변경 범위

기존 `ResearchProvider → OfflineAdapter → Policy Validator`에서 실행 어댑터만 확장했다.
서버가 `source_connectors`에 지정한 APP 호출은 `SourceAdapter`가 기존 Schema/정책 검사 후
해당 Connector로 보낸다. APP/API/인자는 여전히 모델의 Tool Call에서 결정한다.
서버가 사용자 직무에 따라 도구를 선택하거나 Gold를 읽어 라우팅하지 않는다.

Research는 기존 11개 API, Analysis는 도구 없음, Verification은 기존 read 권한을 유지한다.
Read로 확보한 근거만 다음 역할에 전달하는 ledger, 인용·숫자 감사, 호출 예산 검사도 재사용한다.
Hermes 코어, P0/P1 데이터·Gold·Scorer, 운영 usage.json과 유료 한도는 변경하지 않았다.

추가한 부분:

- OpenAlex `search_works`, `read_work`의 HTTP 변환 및 응답 정규화.
- 공개 자료와 SYNTHETIC 자료의 항목별 구분. 보고서/프롬프트/화면도 정보원 구성을 표시한다.
- 초록 없는 항목은 `metadata_only`. 이런 항목이 보고서 근거에 있으면 조사 미완료로 처리한다.
- 공개 Connector 실행에 비공개 Memory/승인 선호를 섞는 경우 거부한다.
- 공개 Connector와 Real 모델의 동시 사용은 첫 모델 요청 전에 거부한다.
  기존 외부 LLM 정책이 승인한 것은 PUBLIC **합성** 자료이므로, 공개 논문까지 자동 승인하지 않는다.

`PublicConnector.execute(api, params, cutoff)`는 정규화된 실행 결과를 반환하는 공통 인터페이스다.
추가 정보원도 같은 인터페이스와 SourceAdapter의 정책/감사 경로를 쓸 수 있다.
OpenDART·KIPRIS Plus·POSCO IR의 실제 Connector는 구현하지 않았으며 기존 합성 실행을 유지한다.

## APP / API / RP / OP

Registry Schema는 그대로다. 검색 조건과 보고서 출력 형식은 섞지 않는다.

| API | RP | OP와 실제 요청 |
|---|---|---|
| openalex/search_works | query | search=query; from_date/to_date는 from_publication_date/to_publication_date; types는 type OR 필터; limit은 per_page(1~10, 기본 3) |
| 동일 | 동일 | sort: relevance / date_desc / citations_desc → relevance_score:desc / publication_date:desc / cited_by_count:desc |
| 동일 | 동일 | language: ko/en, open_access: boolean → language / open_access.is_oa 필터 |
| openalex/read_work | work_id | include_abstract(기본 true). false면 메타데이터만 반환 |

`to_date` 생략 시에도 서버 cutoff를 강제한다. 응답의 날짜·유형·언어·OA 필터도 다시 확인한다.
잘못된 날짜, 미래 요청, Schema에 없는 OP, 필터 구문을 주입한 types는 호출 전에 거부한다.
Read에는 검색 결과의 source_id(W 식별자)를 그대로 사용한다. 첫 버전은 한 페이지만 조회한다. 비어 있지 않은 cursor는 호출 전에 명시적으로 거부하며
자동 페이징·재시도·대량 수집은 하지 않는다. API가 반환한 총 건수를 권한 있는 결과 수로 주장하지 않는다.

## 근거와 오류 의미

각 결과에는 source_id(W 식별자), DOI, 제목, 저자, 발행일/연도, 출처,
OpenAlex URL, 실제 조회 요청 URL(키 제외), UTC 조회 시각, 분류와 provenance를 기록한다.
외부 메타데이터에 없는 DOI·저자·출처는 임의로 보완하지 않는다.

- abstract_inverted_index를 위치 순서로 복원한다. 누락·중복 위치 등 모호한 인덱스는 근거로 채택하지 않는다.
- spans의 metadata는 받은 제목, abstract는 실제 복원한 초록이다. 제목으로 기술적 사실을 증명하지 않는다.
- `abstract_available`은 원본 인덱스 존재 여부, `abstract`는 이번 호출에서 반환한 텍스트다.
- `full_text_available`은 OpenAlex의 **공개 전문 존재 신호**(open_access.is_oa)다. null은 미확인이다.
- OA URL은 메타데이터일 뿐이다. PDF·출판사 페이지·전문은 가져오지 않는다. `full_text_read`는 항상 false다.
- 초록이 없다는 사실을 기술적 사실이 존재하지 않는다는 의미로 해석하지 않는다.

| 상황 | 결과 |
|---|---|
| 정상 검색/초록 포함 Read | ok |
| 정상 검색, results가 빈 배열 | empty |
| 초록 미제공 / 일부 레코드 사용 불가 | partial + 구체적 경고; 추정 초록 없음 |
| 서버 정책 거부 / Connector 비활성 / HTTP 401·403 | denied |
| timeout / 404·429·5xx / redirect / 잘못된 응답 JSON | unavailable; empty로 변환하지 않음 |

실제 전송이 발생한 실패·중복 호출도 source_requests=1, 작업 호출 예산 1회로 센다.
전송 전 거부는 0이다. mock_units는 실제 Connector에선 0이며, 달러 비용은 확인하지 않았으므로
usd=null, billing_verified=false다. 운영 OpenAI 원장과는 별개이며 새 유료 예산이 아니다.
원래 계획·실제 실행 여부·RP/OP·거부 이유·반환 문서와 span은 기존 Trace에 분리해 남긴다.

## 보안 경계

- PUBLIC Environment와 allowed_sources, 서버 사용자/프로젝트 권한, 기간, 예산 검사 후에만 전송한다.
  INTERNAL/RESTRICTED 환경에서 공개 Connector로 나가지 않는다.
- 내부 프로젝트 ID와 서버 private_terms, 비공개 corpus의 원문은 기존 외부 인자 검사로 차단한다.
  비공개 Memory가 있는 실행은 추가로 시작 전에 차단한다. 배포 시 실제 기밀 용어 분류/정책 공급은 필요하다.
- search에서 받은 ID만 read할 수 있다. ID는 W+숫자 또는 정식 OpenAlex ID URL만 받는다.
  HTTP 대상은 코드에 고정된 api.openalex.org의 /works 경로뿐이다. 응답 URL/PDF는 따라가지 않는다.
- 검색 후 read 직전, I/O 후 반환 직전에 권한을 다시 확인한다. denied는 문서 ID·제목·건수·본문을
  결과로 돌려주지 않는다. 모델이 이미 만든 요청 인자는 감사 Trace의 계획에 보존한다.
- 외부 텍스트는 untrusted_external_data. 역할 프롬프트는 그 안의 명령을 따르지 않도록 안내한다.
  역할별 권한과 서버 정책은 외부 문서로 변경할 수 없다. 이 조치가 모든 인젝션 공격을 막는다는 주장은 하지 않는다.
- 기본 API 키 인증은 서버 설정의 Bearer 헤더다. Trace/화면/에러에 헤더나 upstream 본문을 기록하지 않는다.
  별도 Streamlit 공개 시연은 `api_key_parameter=True`로 query 인증을 사용하며 반환 URL의 키를 제거하고 HTTPX 로그를 필터링한다. 기본 Bearer 모드는 그대로다.
- 기존 PayloadPolicy는 synthetic=false 자료의 외부 LLM 전송을 계속 거부한다.

## 서버 설정과 활성화

기본 설정은 생략 또는 false다. UI에서 사용자가 외부 검색을 켤 수 없다.
`.streamlit/secrets.toml`의 서버 설정 예:

```toml
[technical_research_sources]
openalex_enabled = false
# openalex_api_key = "서버에서만 관리하는 키"
```

관리자가 외부 API 이용 조건과 공개 검색 인자의 반출 정책을 확인한 뒤 true로 바꾸고
Streamlit 앱을 재시작해야 실제 OpenAlex 요청이 가능하다. 이번 작업에서는 활성화하지 않았다.
키는 공식 문서상 기본 조회에 필수는 아니지만 조직의 승인된 키/쿼터 관리가 권장된다.
키 발급, 결제 설정, API 한도 증액은 이 코드가 수행하지 않는다.
기존 `[technical_research_real]` 설정·원장·동시 실행 잠금·질문 제한은 변경하지 않는다.
PUBLIC quick 환경에서 로컬 Mock 모델과 공개 Connector 조합을 사용할 수 있으나,
이때 검색 선택은 스크립트 Mock이다. GPT-4o mini의 자율 검색 품질을 검증한 것이 아니다.

Python에서 테스트용으로 연결할 때도 서버가 `ResearchApplication(...,
source_connectors={'openalex': OpenAlexConnector(enabled=True, transport=...)})`를 구성한다.
호출자 Tool 인자에 backend/enable/credential 필드를 추가하지 않는다.

## 확인한 공식 문서 (2026-11-16)

- [Works와 상세 조회](https://help.openalex.org/data/works/)
- [키워드 검색](https://help.openalex.org/api/searching/)
- [필터: 기간, 유형, OR와 OA](https://help.openalex.org/api/filtering/)
- [정렬](https://help.openalex.org/api/sorting/)
- [Works 필드: 초록 인덱스, authorships, primary_location, open_access](https://help.openalex.org/data/works/attributes/)
- [인증: Bearer 또는 query key, 사용 제한](https://help.openalex.org/api/authentication/)

문서 웹 조회와 API 실행은 별개다. 이 구현의 실서비스 호환성은 아직 공개 API로 확인하지 않았다.

## 검증과 남은 작업

신규 테스트는 모두 가짜 논문 fixture를 쓴다. 정상 검색→상세 조회→Analysis→Verification,
필터 변환, 초록 누락/잘못된 레코드, Schema/기간/보안/예산 거부, 권한 취소,
HTTP 실패와 중복 비용, 기존 Real 반출 제한을 검사한다.
Mock으로 프롬프트 인젝션 문구를 받은 뒤 허가되지 않은 도구가 추가 실행되지 않는지 확인했지만,
실제 모델의 공격 저항성·주장 정확성은 별도 검증이 필요하다.

실제 API 활성화 후 확인할 항목은 키·쿼터·오류 응답, 실제 검색 적합성, 한국어 검색 품질,
초록/저자 누락과 라이선스, 운영 네트워크 환경이다. 자동 페이징/캐싱/재시도는 아직 없다.
외부 LLM과 연결하려면 PUBLIC 실자료 payload에 대한 **별도 반출 승인 및 구현**이 먼저 필요하다.
그 다음에 기존 유료 예산 승인 절차 아래 실제 모델의 Tool 선택·근거 활용·인젝션 대응을 확인한다.
사내 다중 사용자 서비스로 가기 전 SSO 주체와 권한 Context 연결, 기밀 입력 분류,
worker 간 호출 예산/감사 저장소, 민감 로그 접근 제어도 별도로 구현해야 한다.
현재 공개 검색 보고서를 승인된 공개 Memory로 재분류하는 기능은 없다. 기존 저장 이력은
PRIVATE로 취급되므로 다음 조사에 그 이력이 검색되면 공개 Connector 실행이 차단된다.
공개/비공개 Memory의 분리·검수는 후속 작업이며, 이 제한을 해제해 이력을 자동 반출하지 않는다.
