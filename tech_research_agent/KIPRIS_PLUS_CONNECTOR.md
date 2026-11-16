# KIPRIS Plus 국내 특허 Connector v1

기준 `38a3f4e3`, 명세 확인일 2026-11-16. 실제 KIPRIS Plus·OpenAlex·OpenDART·OpenAI API는
호출하지 않았다. 공식 안내/명세 웹 페이지만 조회했다. 테스트의 특허·출원인·번호·청구항은 합성 fixture다.
기본 Offline Mock, 운영 원장·유료 한도, Hermes 코어, P0/P1 평가 자료·Scorer는 변경하지 않았다.

## 확인한 공식 명세

- [특허·실용 공개·등록공보의 공식 서비스 목록](https://plus.kipris.or.kr/portal/data/apiClas/DBII_000000000000001/view.do)
- [전체검색 getAdvancedSearch 명세](https://plus.kipris.or.kr/portal/popup/DBII_000000000000001/SC002/ADI_0000000000002944/apiDescriptionSearch.do)
- [서지상세 getBibliographyDetailInfoSearch 명세](https://plus.kipris.or.kr/portal/popup/DBII_000000000000001/SC002/ADI_0000000000002130/apiDescriptionSearch.do)
- [별도 청구항 patentClaimInfo 명세](https://plus.kipris.or.kr/portal/popup/DBII_000000000000001/SC002/ADI_0000000000015124/apiDescriptionSearch.do)
- [공공데이터포털 서비스 안내](https://www.data.go.kr/data/15065437/openapi.do)
- [KIPRIS Plus 이용약관](https://plus.kipris.or.kr/portal/main/contents.do?menuNo=200031)
- [공식 OpenAPI 이용 절차](https://plus.kipris.or.kr/eng/main/contents.do?menuNo=300026)

목록 페이지의 동적 탭만으로 필드명을 추측하지 않았다. 공식 popup 명세의 입출력 데이터에 들어 있는
계층·필드명과 요청 예시를 확인했다. 상세 API의 claimInfoArray/claimInfo/claim이 확인되어
청구항은 이 응답에서 읽는다. 별도 patentClaimInfo는 목록/명세 확인만 했고 v1에서는 호출하지 않는다.
폐기 예정으로 표시된 getWordSearch/getNumberSearch는 사용하지 않는다.

공식 요청 예시는 HTTP로 표기돼 있다. 구현은 인증키 보호를 위해 HTTPS만 사용하며 HTTP fallback을 하지 않는다.
실제 API의 HTTPS 호환성은 이번 작업에서 확인하지 않았다. 활성화 전 운영자가 확인해야 한다.

## 기존 경로 연결

`ResearchProvider → SourceAdapter → P1 Policy Validator → KIPRISPlusConnector.execute`를 사용한다.
PublicConnector 인터페이스와 Registry의 5 APP/11 API, RP/OP Schema는 유지했다.
서버는 직무별로 도구를 강제 선택하거나 Gold를 읽어 라우팅하지 않는다.
Research는 모델이 생성한 Tool Call을 실행하고, Analysis는 도구가 없으며 Verification은 read 권한만 가진다.
OpenAlex·OpenDART·그 밖의 합성 도구는 기존대로 동작한다.

search_patents에서 반환된 applicationNumber만 seen에 등록한다. read_patent 전에는 현재 권한과 seen을
다시 검사한다. 상세 응답의 출원번호·공개일·공개번호가 검색에서 확인한 대상과 맞는지도 확인한다.
실행 뒤 권한이 취소되면 항목·경고를 반환하지 않는다. 조회한 특허 원문 span만 다음 역할의 근거로 전달한다.
누락 청구항·원문 확인 실패는 기존 미완료 처리와 조회 제한 안내로 이어진다.

## 검색 인자 매핑과 지원 범위

API 경로의 `patUtiModInfoSearchSevice` 철자는 공식 명세 그대로다.

| Registry | 실제 API 처리 |
|---|---|
| kipris_plus/search_patents | getAdvancedSearch |
| RP query | word |
| RP jurisdiction=KR | 국내 서비스만 사용. patent=true, utility=false로 국내 특허만 조회 |
| OP from_date/to_date | openDate=YYYYMMDD~YYYYMMDD. **공개일** 기준이며 출원일이나 공고일로 대체하지 않음 |
| OP applicant | applicant. 출원인명 또는 공식 특허고객번호 검색 인자 |
| OP ipc | 단일 IPC를 ipcNumber에 전달. IPC 배열의 여러 항목을 합치는 연산 의미는 확인하지 못해 다중 항목을 거부 |
| OP sort=date_desc | sortSpec=OPD, descSort=true: 공개일 내림차순 |
| OP limit | numOfRows(1~10, 기본 3), pageNo=1 |
| OP cursor | 비어 있지 않으면 전송 전 거부. 자동 다음 페이지 없음 |
| sort=relevance/citations_desc | 해당 정렬의 공식 대응을 확인하지 못해 전송 전 거부. 다른 정렬로 몰래 대체하지 않음 |

기간 생략 시 시작은 1900-01-01, 종료는 서버 cutoff다. sort 생략 시 공개일 내림차순을 쓴다.
API에 적용한 필터와 별도로 반환 공개일을 다시 검사한다. 출원인명·IPC 필터와 명백히 다른 항목도 제외한다.
특허고객번호 필터는 검색 응답의 출원인명만으로 독립 검증할 수 없으므로 경고한다.
원격 검색 언어의 복잡한 논리 연산을 로컬에서 재현하지 않는다.
첫 페이지 제한, 필터 검증 불가, 일부 레코드 제외는 partial과 경고로 남긴다.
어떤 페이지에서 결과가 없다는 사실을 관련 특허 전체가 없다는 결론으로 쓰지 않는다.

검색 XML은 `response/header`와 `response/body/items/item`, `response/count`를 사용한다.
필수 성공 코드·페이지·전체 건수의 계층이 없으면 정상 빈 검색으로 추정하지 않고 unavailable이다.
정상 성공 응답의 빈 items와 totalCount=0만 empty로 처리한다.

## 서지상세·청구항

| Registry | 실제 API 처리 |
|---|---|
| kipris_plus/read_patent RP application_id | getBibliographyDetailInfoSearch의 applicationNumber. 검색에서 확인한 13자리 국내 특허 출원번호만 사용 |
| OP include_claims=true | `body/item/claimInfoArray/claimInfo/claim`의 실제 텍스트를 span으로 반환 |
| OP include_claims=false 또는 생략 | 청구항을 반환 근거로 채택하지 않음. 서지·초록 범위만 표시 |

서지는 `body/item/biblioSummaryInfoArray/biblioSummaryInfo`에서 읽는다.
IPC는 ipcInfoArray/ipcInfo, 출원인명은 applicantInfoArray/applicantInfo/name,
초록은 abstractInfoArray/abstractInfo/astrtCont에서 읽는다. 다른 위치의 claim이나 발명의 설명을
청구항으로 끌어오지 않는다. 확인되지 않은 필드명에 대한 대체 경로를 만들지 않았다.

include_claims=true인데 청구항이 없거나 claimCount와 반환 텍스트 개수를 대조할 수 없으면 partial이다.
이미 확보한 청구항은 보존하되 claims_complete/original_verified=false로 둔다.
서지상 claimCount와 텍스트 개수 대조는 기계적 확인이며 최신 권리 범위나 청구항 법률 해석의 승인이 아니다.

청구항 원문은 그대로 보존한다. span ID의 claim-1과 sequence_in_response는 로컬 배열 순서다.
공식 명세에 별도 청구항 번호 필드가 없으므로 claim_number는 null이며 원문의 번호를 임의로 생성하지 않는다.
초록과 청구항은 각각 patent_abstract와 patent_claim로 구분한다.

## 번호·날짜·근거 의미

| 원격 필드 | 내부 의미 |
|---|---|
| applicationNumber / applicationDate | 출원번호 / 출원일 |
| openNumber / openDate | 공개번호 / 공개일. published_at에는 이 공개일만 사용 |
| publicationNumber / publicationDate | 공고번호 / 공고일. 공개번호·공개일과 다름 |
| registerNumber / registerDate | 등록번호 / 등록일 |
| registerStatus | 조회 시 서비스가 반환한 등록상태. 현재 권리 유효성에 대한 별도 확인이 아님 |

표시된 등록상태, 출원인, IPC, 번호·날짜·명칭은 원 응답에서 받은 값만 쓴다. 없는 선택 필드는
null/빈 목록으로 남기며, 이것이 해당 정보가 현실에 없다는 뜻은 아니다. 공개일이 없으면 출원일로
대체하지 않고 해당 레코드를 제외한다. 요청 기준일 이후 날짜가 있는 레코드도 채택하지 않는다.
현재 응답의 등록상태를 과거 cutoff 시점의 상태로 소급하지 않는다. rights_status_as_of는 미확인이다.

정규화된 verified 플래그·evidence_coverage·로컬 span ID는 실행 상태를 나타내는 내부 메타데이터다.
KIPRIS가 이러한 내부 플래그를 제공한다고 표시하지 않는다.

역할 프롬프트와 Mock 안내에서 아래 구분을 유지한다.

- 출원 사실과 등록 사실은 다르다.
- 특허 기재·청구항은 발명의 설명이나 실험으로 검증된 성능과 다르다.
- 등록상태만으로 현재 권리의 유효성, 실제 상용화, 기술 우수성, FTO를 확정하지 않는다.
- Verification은 출원번호·공개일·청구항 인용을 받은 원문과 대조한다. 법률적 FTO 감정은 수행하지 않는다.

## 전문 다운로드: v1 미지원

공식 목록에는 공개/공고 PDF와 전문파일정보 조회가 별도 기능으로 존재한다. v1은 이 API들의
다운로드 경로 조회와 PDF/TIFF 본문 파싱을 구현하지 않았다. 서지상세의 이미지 경로를 전문 PDF 경로로
간주하지 않는다. full_text_download_urls=[], full_text_available=null,
full_text_download_metadata=not_requested_in_v1, full_text_read=false로 명시한다.
따라서 청구항을 확보해도 공보 전문을 읽었다고 표시하지 않는다.

원격 문서에 URL이 있어도 서버가 따라가지 않는다. 허용 호스트는 고정된 HTTPS plus.kipris.or.kr의
두 API operation뿐이다. redirect·임의 URL·로컬 파일 접근은 없다.
다운로드를 후속 구현하려면 공식 파일 호스트·서비스 권한·용량·파일 형식과 파서를 별도 검증해야 한다.

## 보안·감사·비용

서버 P1 정책으로 사용자/프로젝트, PUBLIC 분류, allowed_sources, 기간, 호출 예산,
비공개 검색 인자를 검사한다. INTERNAL/RESTRICTED 또는 비공개 Memory가 포함된 실행은 기존대로 차단한다.
공개 실자료와 Real GPT-4o mini의 동시 사용도 첫 모델 요청 전에 차단한다.
운영 usage.json과 모델 호출 한도, 질문 제한, 예산 승인 정책은 그대로다.

응답은 2 MiB, XML 깊이 64·노드 30,000·텍스트 1,000,000자 이내로 제한한다.
DTD/외부 엔티티를 파서에서 거부하고 지원하지 않는 XML·인코딩·계층은 unavailable로 처리한다.
외부 텍스트는 untrusted_external_data이며 새로운 도구 권한이나 명령으로 취급하지 않는다.

Trace에는 원래 APP/API/RP/OP, 실행 여부, 결과 상태/경고, 공개일·식별자·UTC 조회 시각,
키가 빠진 실제 요청 URL과 확보한 span을 남긴다. 원격 오류 메시지·raw XML·인증 헤더를 로그에 남기지 않는다.
인증키는 실제 전송 transport에서만 ServiceKey에 추가한다. 일반 HTTPX 요청/응답 URL과 INFO 로그에는
키가 들어가지 않으며 전역 logger 설정을 바꾸지 않는다. 키가 응답에 예기치 않게 나타나도 결과에서 마스킹한다.

Tool Call 하나는 API 요청 하나다. 상세 응답에 청구항이 없다고 다른 API나 PDF를 자동 추가 호출하지 않는다.
전송 시도 source_requests=1, 도구 예산 1회를 소비한다. 실패·중복도 같은 방식으로 기록한다.
전송 전 거부는 0이다. 실제 요금/쿼터 차감은 usd=null, quota_units=null과 미검증 플래그로 남기며 모델 비용과 합산하지 않는다.
HTTP 인증 거부·서비스 접근/만료 코드(20/31)는 denied, HTTP 429·기타 실패 코드는 unavailable이다.
알 수 없는 XML 오류 코드를 임의로 빈 검색으로 해석하지 않는다. 실제 계정의 오류·쿼터 의미는 운영 검증이 필요하다.

## 실제 서비스 활성화 조건

약관상 회원 가입, 인증 Key 발급과 이용할 상품의 신청·승인이 필요하다. 유료상품은 해당 조건에 따라
수수료 납부 후 이용한다. 공공데이터포털은 이 서비스에 월 1,000회 무료 호출을 안내하지만,
그 안내가 모든 직접 가입 상품·운영 계정에 동일하게 적용된다고 가정하지 않는다.
조직 계정의 상품 범위·승인·계약·쿼터를 실제로 확인해야 하며 이 코드는 신청·결제·키 발급을 하지 않는다.

서버 `.streamlit/secrets.toml`의 기본 설정은 생략 또는 false다.

```toml
[technical_research_sources]
kipris_enabled = false
kipris_service_approved = false
# kipris_api_key = "서버 전용 ServiceKey 원문값"
```

관리자가 두 operation의 사용 권한과 HTTPS 접속 가능 여부를 확인한 뒤 두 플래그를 true로 바꾸고 재시작한다.
키는 미리 URL 인코딩하지 않은 원문값으로 관리한다. 화면에는 키를 입력/출력하는 칸이 없다.
Python에서는 `KIPRISPlusConnector(enabled=True, service_approved=True, api_key=server_key,
transport=mock_transport)`를 ResearchApplication의 source_connectors['kipris_plus']에 주입해 테스트할 수 있다.
운영에서는 transport를 생략한다. 실제 서비스를 활성화하는 설정 변경은 이번에 수행하지 않았다.

## 남은 확인과 검증 범위

Stub에서 XML 경로·필터 매핑·청구항 성공/누락·권한/오류/키 보호와 RAV 연결을 검사했다.
실제 HTTPS·키·상품 승인·계정별 쿼터, 원격 검색 언어/필터 효과, 최신 응답 형식·청구항 개수 의미,
누락 필드와 실제 검색 적합성은 아직 검증하지 않았다. 실제 LLM의 개인화·특허 해석·인젝션 대응도 미검증이다.

다중 IPC, 관련도/피인용 정렬, 다음 페이지, 자동 재시도, 별도 청구항 API, 파일 링크 조회·다운로드,
최신 권리 유지/연차료/소멸 이력과 FTO 검토는 미지원이다. 공개 조사 이력을 공개 Memory로 자동 승인하지도 않는다.
기존 이력이 PRIVATE로 검색되면 후속 공개 Connector 실행이 차단될 수 있다.
테스트 결과는 [KIPRIS_PLUS_VALIDATION.md](KIPRIS_PLUS_VALIDATION.md)에 기록한다.
