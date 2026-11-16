# OpenDART Connector v1

기준 커밋 `56c7e517`. 실제 OpenDART·OpenAlex·OpenAI 호출 없이 구현했다.
공식 개발가이드 웹 페이지만 읽었고, 데이터 검증에는 가상 회사·공시·재무 값과 MockTransport를 사용했다.
기본은 기존 Offline Mock이다. Hermes 코어, 운영 usage.json·유료 한도, P0/P1 평가 자료와
Scorer는 수정하지 않았다. 실제 포스코 내부 자료와 실기업 기본 코드는 추가하지 않았다.

## 기존 구조 재사용

| 기존 경로 | 이번 변경 |
|---|---|
| PublicConnector.execute(api, params, cutoff) | 같은 인터페이스의 OpenDARTConnector 추가 |
| SourceAdapter → P1 validate → 실행·감사 Trace | 동일하게 사용. list_disclosures 결과 ID도 seen에 등록하고 회사 권한을 추가 확인 |
| ResearchProvider의 11 API / Analysis 도구 없음 / Verification read만 허용 | 권한 유지. 회사 Catalog와 공시 본문·재무 행의 근거 범위를 프롬프트에 명시 |
| Research → Analysis → Verification | 실제 조회한 공시 본문 또는 구조화된 재무 행을 전달. 일부 원문 미확인 시 완료 표시 차단 |
| Real 모델 경로 | 공개 Connector와 동시 사용 차단 유지. 실제 공개 자료의 외부 LLM 전송은 활성화하지 않음 |
| OpenAlex / 나머지 Offline 도구 | 기존 경로 유지. 화면과 보고서에 활성화된 공개 정보원 이름을 구분 |

서버는 도구를 자동 선택하지 않는다. 실제 Tool Call의 APP/API/RP/OP를 검증하고 그 호출만 실행한다.
Mock 모델의 회사코드 선택은 전달받은 Catalog를 사용하도록 바꿨다. Offline에서는 기존 합성 Catalog를,
OpenDART가 설정됐을 때는 사용자·프로젝트에 허용된 검증 Catalog를 본다.
이 Mock 선택 규칙은 실제 모델의 개인화 능력을 입증하지 않는다.

## 공식 명세와 인자 매핑

2026-11-16 확인:

- [공시검색 list.json](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001)
- [공시원본 document.xml: ZIP](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019003)
- [단일회사 전체 재무제표 fnlttSinglAcntAll.json](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS003&apiId=2019020)
- [XBRL Taxonomy의 계정 ID·기준일·라벨 정의](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS003&apiId=2020001)

Registry RP/OP는 변경하지 않았다. 인증키 crtfc_key는 모델 인자가 아닌 서버 설정에서 추가한다.

| APP/API | Registry 인자 → API/로컬 처리 |
|---|---|
| opendart/list_disclosures | corp_code 그대로; from_date/to_date → bgn_de/end_de(YYYYMMDD) |
| 동일 | report_type: material → pblntf_ty=B; annual → pblntf_detail_ty=A001; quarterly → A003; all → 유형 필터 생략 |
| 동일 | limit → page_count(1~10, 기본 3); page_no=1, sort=date, sort_mth=desc |
| 동일 | keyword는 API 인자가 아니다. 첫 페이지 report_nm에서 공백으로 나눈 단어 중 하나가 포함되는지 로컬 필터링. 본문 검색이 아님을 warnings에 명시 |
| 동일 | 비어 있지 않은 cursor는 전송 전에 거부. 자동 추가 페이지/재검색 없음 |
| opendart/read_disclosure | 검색에서 확인한 receipt_no → rcept_no; document.xml 다운로드 |
| 동일 | section은 API 인자가 아니다. 추출 텍스트의 문자 그대로 부분 일치하는 span만 반환하며 partial 처리. 구조적 목차 조회/전체 문서 검증으로 주장하지 않음 |
| opendart/read_financials | corp_code, bsns_year(2015년 이후), reprt_code, fs_div 그대로 전달 |
| 동일 | account_ids는 응답의 공식 ID를 내부 canonical ID로 매핑한 후 로컬 필터링. 미지원 canonical ID는 전송 전 거부 |

quarterly는 A003 분기보고서이며 반기보고서(A002)를 포함하지 않는다. 공시 목록은 접수일로 제한한다.
응답의 회사코드·접수번호·접수일·기간도 재검사한다. 첫 페이지만 본 경우 partial 경고를 남기며,
그 페이지에서 제목이 매칭되지 않았다는 사실을 관련 공시가 없다는 결론으로 쓰지 않는다.

## 회사 Catalog와 접근 권한

실기업 Catalog 기본값은 비어 있다. `00000001`, `00000002`는 Catalog 등록 자체를 거부하며
다른 실제 코드로 자동 치환하지 않는다. 주제 H/B가 특정 실기업이라는 추정도 하지 않는다.

서버가 검증한 코드별로 name, verified=true, verified_at, verification_source,
allowed_users, allowed_projects를 제공한다. 코드는 8자리, 검증일은 미래가 아니어야 하고
검증 출처는 HTTPS OpenDART 공식 도메인이어야 한다. 회사코드 진위 확인은 **서버 운영자의 검증 책임**이다.
이 코드가 verified 플래그만으로 실제 회사코드를 새로 검증하거나 API로 조회하는 것은 아니다.

현재 사용자와 프로젝트에 허용된 항목만 모델의 entity_catalog에 제공한다. P1의 사용자·프로젝트·
allowed_sources·PUBLIC 분류·기간·비공개 인자·예산 검사를 유지하고, 회사 Catalog 권한도 호출 직전과
응답 반환 직전에 확인한다. 직무나 Persona로 권한을 부여하지 않는다.
검색 전 임의 접수번호 조회, 권한 취소 후 Read, 합성 공시 ID를 실제 원본 API에 보내는 행위를 차단한다.
재무 API에서 접수번호를 받았다는 사실만으로 공시 ZIP 다운로드 권한(seen)을 부여하지 않는다.

## ZIP/XML 원문 범위

- HTTP 응답: 압축 해제된 전송 스트림 기준 최대 8 MiB. 자동 HTTP 재시도·redirect 없음.
- ZIP: 최대 32개 항목, 파일당 최대 2 MiB, 전체 선언 압축 해제량 최대 16 MiB, 압축률 최대 100배.
- 파일 실제 읽기도 한도를 적용한다. 암호화, 지원하지 않는 압축 방식, 중복 파일명, 심볼릭 링크,
  절대경로·상위경로·역슬래시·콜론을 포함하는 경로를 거부한다. 파일 시스템에 추출하지 않는다.
- `.xml`만 파싱한다. DOCUMENT 또는 XML로 정상 파싱되는 HTML 루트만 지원한다.
  DTD는 파서 단계에서 거부한다. UTF-16 선언을 이용한 우회도 테스트했다.
- XML 깊이 64, 노드 50,000, 파일당 텍스트 200,000자 한도. PDF/이미지/비정형 HTML/손상 XML은 읽었다고 표시하지 않는다.
- 텍스트는 공백을 정규화하고 3,000자 span으로 나눈다. 파일명·정규화 텍스트 offset을 남긴다.
  원본 XML byte offset과는 다르다. 표의 시각적 배치나 첨부 PDF 내용을 복원했다고 주장하지 않는다.
- 일부 XML만 읽었거나 첨부를 해석하지 못하면 partial, 지원되는 본문이 없으면 unavailable.
  모든 지원 대상 텍스트를 읽고 누락 경고가 없을 때만 full_text_read/original_verified를 true로 둔다.
  이는 기계적 조회·파싱 완료 신호이며 공시 내용의 진실성이나 모델 해석의 정확성을 승인하는 신호가 아니다.

외부 텍스트에는 untrusted_external_data를 표시한다. 역할 프롬프트는 이 안의 명령을 데이터로 다루며,
도구·서버 권한은 변경하지 않는다. 실제 모델의 프롬프트 인젝션 저항성은 이번 Stub 검사로 입증하지 않는다.

## 재무 계정과 회계기간

| canonical account_id | 수용하는 공식 account_id | 재무제표 |
|---|---|---|
| operating_profit | dart_OperatingIncomeLoss | IS/CIS |
| cash_flow_investing | ifrs-full_CashFlowsFromUsedInInvestingActivities, 구버전 ifrs_CashFlowsFromUsedInInvestingActivities | CF |

계정 이름이 같다는 이유로 비표준 ID를 추측 매핑하지 않는다. 빠진 계정, 미지원 ID, 빈 금액은
0으로 채우지 않는다. 요청 계정 누락은 partial이며, 중복 계정·여러 접수번호도 합산하거나 하나를
임의 선택하지 않고 별도 행으로 보존하면서 partial로 표시한다. 실기업·적용 기준일별 계정 가용성과
Taxonomy 매핑은 실제 API 활성화 전에 추가 검수가 필요하다.

- 금액 원문 문자열과 쉼표만 제거한 값 문자열을 함께 저장한다. 부동소수점으로 바꾸거나 배율을 적용하지 않는다.
- currency를 단위로 보존한다. currency 미제공은 미확인 행으로 제외하며 원화라고 가정하지 않는다.
- 당기금액(thstrm_amount)과 당기누적금액(thstrm_add_amount)을 구분한다. 분·반기 IS/CIS의 당기는
  공식 명세상 3개월 금액이다. 전기 금액·명칭과 원 응답 행도 별도로 남긴다.
- CFS/OFS는 요청을 그대로 보존한다. 전체 재무제표 API가 fs_div를 응답하지 않으면 요청 기준임을 유지한다.
  응답에 다른 fs_div가 있으면 제외한다. CFS 실패를 OFS로 자동 대체하지 않는다.
- 사업연도·보고서 코드·당기명을 유지하되, 이 API에서 정확한 기간 시작/종료일이 없으면 null/미확인으로 둔다.
  비12월 결산 법인에 임의의 1월 1일~12월 31일을 붙이지 않는다.
- 회사 전체 연결/별도 실적이다. 영업이익·투자활동현금흐름을 수소환원제철이나 양극재 사업의 ROI로 해석하지 않는다.
- financial_rows는 조회한 구조화 원자료의 근거이며 공시 ZIP 전문 조회와 다르다. full_text_read=false다.
  source_id에 회사·사업연도·보고서·CFS/OFS·접수번호·계정 집합을 넣어 서로 다른 기준이나 선택 계정의 행을 덮어쓰지 않는다.

Analysis는 계획과 실적을 구분하고 Verification은 재무 API를 같은 회사·기간·CFS/OFS로 재조회할 수 있다.
숫자 토큰 대조는 기존 기계적 검사일 뿐이며 회계기간·금액 의미의 최종 판단은 사람 검수가 필요하다.

## 상태·감사·비용

정상 결과 ok, 조회 데이터 없음(013 및 정상 빈 목록) empty, 인증/IP/권한 문제 denied,
쿼터(020)·HTTP 장애·원본 없음(014)·잘못된 응답 unavailable, 제한된 결과 partial을 구분한다.
원본 ZIP 요청의 013/014는 본문 미확보이므로 unavailable이다. 장애를 empty로 바꾸지 않는다.
조회 제한·partial 경고는 retrieval_limits로 다음 역할에도 전달하고 최종 보고서에 남긴다.
다른 정보원의 근거가 있더라도 denied/unavailable 실행이 있으면 조사 완료로 표시하지 않는다.

Trace에는 계획, 실제 실행 여부, RP/OP, 거부 사유, 문서·원문 span·회사·접수일·출처 URL·UTC 조회 시각을 남긴다.
인증키가 포함된 실제 요청 URL은 기록하지 않는다. source API 경로와 키를 제외한 RP/OP로 요청을 추적한다.
API 키는 서버에서 query crtfc_key에 추가하며, 헤더·raw HTTP 예외·upstream 오류 message는 로그로 보내지 않는다.

실제 전송은 실패·중복을 포함해 source_requests=1, 작업 도구 예산 1회를 소모한다.
전송 전 차단은 0이다. 외부 서비스의 실제 쿼터 차감은 확인하지 않았으므로 quota_units=null,
quota_verified=false다. source usd=null, billing_verified=false이며 OpenAI 모델 비용과 합산하지 않는다.
실제 서비스 계정의 비용·쿼터는 이번 테스트로 확인하지 않았다.

## 서버 활성화

`.streamlit/secrets.toml`에서 서버만 설정한다. 기본은 생략/false다.

```toml
[technical_research_sources]
opendart_enabled = false
# opendart_api_key = "서버 전용 40자리 인증키"
```

활성화 전 `technical_research_sources.opendart_companies`에 검증된 코드별 Catalog를 등록한다.
각 항목은 위 name/verified/verified_at/verification_source/allowed_users/allowed_projects 필드를 가져야 한다.
실제 코드를 임의 예시로 넣지 않았다. Python 테스트 주입 방식은 다음과 같다.

```python
connector = OpenDARTConnector(
    enabled=True, api_key=server_key, company_catalog=server_verified_catalog,
    transport=test_transport,  # 테스트에서만 MockTransport; 운영에서는 생략
)
app = ResearchApplication(state_dir, source_connectors={"opendart": connector})
```

운영자가 Catalog의 회사 식별/권한과 인증키·사용 조건을 확인한 뒤 enabled를 true로 바꾸고 서버를 재시작한다.
기존 OpenAlex 설정과 함께 사용할 수 있다. UI에는 활성 정보원과 현재 사용자에게 허용된 회사 Catalog를 표시한다.
이 작업에서는 설정을 활성화하거나 키를 발급하지 않았다.

외부 GPT-4o mini와 공개 Connector의 동시 실행은 여전히 첫 모델 요청 전에 차단된다. 반출 승인 전까지
기존 PUBLIC 합성 질문 제한·원장·유료 예산은 그대로다. 비공개 Memory/승인 선호가 포함된 실행도 차단된다.
공개 조사 이력의 별도 공개 Memory 분류는 아직 없으므로, 기존 이력이 PRIVATE로 검색되면 후속 실행이 차단될 수 있다.

## 실제 API에서 남은 확인

실제 회사 Catalog, 최신 Taxonomy/계정 적용 기준일, 인증키/IP·쿼터, 정정공시, 원문 XML의 인코딩/DTD와
첨부 구조, 큰 공시의 제한 초과 빈도, 분·반기/비12월 결산 재무기간과 단위가 남아 있다.
읽지 못하는 원문이 많으면 지원 포맷을 안전하게 확대해야 하며 제한을 조용히 완화하지 않는다.
현재 자동 페이징·재시도·캐시·원문 PDF 파싱은 없다. 실제 LLM의 Tool 선택·재무 해석·개인화 품질은 검증하지 않았다.
검증 결과와 재현 명령은 [OPENDART_VALIDATION.md](OPENDART_VALIDATION.md)에 기록한다.
