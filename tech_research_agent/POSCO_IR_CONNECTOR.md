# POSCO Holdings 공개 IR Connector v1

기준 `d7adc2ca`, 2026-11-16. 관리자가 검수한 Catalog 검색과 PDF 텍스트 조회를
기존 PublicConnector에 연결했다. 자동 수집기나 공개 API를 구현한 것은 아니다.
기본 Offline Mock, 5 APP / 11 API, Research → Analysis → Verification 흐름은 유지한다.

## 공식 자료실 확인 범위

- [국문 IR 자료실](https://www.posco-inc.com/hs91a1-front/app/ir/ir-material.html)
- [영문 IR 자료실](https://www.posco-inc.com/hs91a1-front/app/en/ir/ir-material.html)
- [IR 개요](https://www.posco-inc.com/hs91a1-front/app/ir/overview.html)
- [기존 영문 자료실](https://www.posco-inc.co.kr/poscoinc/v3/eng/investor/s91e3000100c.jsp)

현재 자료실에는 IR활동·감사보고서·정기보고서 구분이 있다. 검색 색인에 남은 공식 기존
자료실에서 Earnings Release, Datapack, CEO Investor Day, Value-Up Plan 등의 자료명을
확인했다. 동적 페이지의 정적 HTML에 자료 건수가 0으로 보이는 것은 실제 자료 부재의
증거가 아니다. 기존 자료실 직접 접속은 502여서 현재 다운로드 호환성은 확인하지 못했다.

공개된 API 명세는 확인하지 못했다. JavaScript 내부 호출이나 비공개 endpoint를
역공학하지 않았다. 공식 페이지 푸터는 POSCO HOLDINGS의 All Rights Reserved를 명시한다.
IR 문서별 재사용·재배포를 포괄적으로 허용하는 별도 이용조건은 확인하지 못했다.
POSCO 철강회사 사이트의 약관을 Holdings 자료의 허가로 대신하지 않는다.
관리자는 등록 전 공개 여부·출처·보관 및 사용 권한을 확인해야 한다.
이번에는 실제 PDF 다운로드, 서비스 신청, 외부 정보원 API 호출을 하지 않았다.

## Catalog 계약

서버 전용 JSON 배열로 관리한다. 배포 기본값은 미활성이고 실제 문서 Catalog는 넣지 않았다.
다음 키를 각 항목에 등록한다.

| 필드 | 의미·검증 |
|---|---|
| id | `ir-`로 시작하는 고유 ID. DART 접수번호와 별개 |
| title / published_at | 제목 / 게시일 `YYYY-MM-DD` |
| material_type | earnings_release, ir_datapack, investor_day, strategy_presentation, other |
| language | ko 또는 en |
| source_url | 관리자가 확인한 공식 자료실·출처 HTTPS URL |
| pdf_url 또는 local_path | 둘 중 하나만 지정. 승인 PDF URL 또는 서버 루트 아래 상대 `.pdf` 경로 |
| registered_at / verified_at | 시간대가 있는 ISO 시각. 등록 ≤ 검증 ≤ 현재, 게시 ≤ 검증일 |
| version / sha256 | 비어 있지 않은 버전 / 원본 바이트의 소문자 SHA-256 |
| classification / approved | PUBLIC / true만 허용 |
| allowed_users / allowed_projects | 명시적인 사용자·프로젝트 ID 배열. 빈 배열은 접근 불가 |
| keywords | 선택. 관리자가 등록한 검색어 배열 |

선택 필드 reporting_period, entity_scope, related_disclosures는 **Catalog 기재값**으로만
전달한다. 회계기간·법인 범위·관련 공시 일치를 자동 검증한 것으로 표시하지 않는다.
검색 결과의 `hash_verified=false`는 검수자가 기록한 해시이며, Read에서 바이트를 대조해야
true가 된다. 로컬 경로와 접근 목록은 모델 입력이나 반환 문서에 넣지 않는다.

허용 호스트는 `www.posco-inc.com`, `posco-inc.com`이다. 다른 공식 계열사·과거 도메인도
자동 허용하지 않는다. HTTPS, 사용자정보 없는 URL, 이동 경로 없는 경로만 허용한다.
PDF는 `.pdf` 경로 또는 공식 기존 `/poscoinc/servlet/FileDown`의 PDF file 인자로 제한한다.
다운로드는 등록된 URL 그대로만 수행하며 redirect를 따르지 않는다. 호스트 허용만으로
문서 검수를 대체하지 않으므로 관리자는 비공개·토큰 포함 URL을 등록하면 안 된다.

IRCatalog.register / Connector.register_material은 항목과 해시를 검증한다. 같은 ID·버전에
다른 해시를 덮어쓸 수 없다. Connector.withdraw_material은 철회한다. 변경/철회하면
해당 ID 캐시를 비우고, 이전 검색의 catalog_binding으로는 Read할 수 없다.
UI는 시작할 때 Catalog를 로드하므로 파일 변경은 앱 리소스 재시작/재로드가 필요하다.
여러 프로세스에 대한 Catalog 동기화 서비스는 v1 범위 밖이다.

## APP/API/RP/OP

기존 Registry를 변경하지 않았다. P1이 Schema·RP/OP·현재 서버 Context를 확인한 뒤 실행한다.

| API | RP | OP 및 의미 |
|---|---|---|
| search_materials | query | from_date/to_date: 게시 기간, kind: earnings/strategy/all, language: ko/en, sort: date_desc/relevance, limit: 기존 Schema 범위 |
| read_material | material_id | pages: 1부터 시작하는 중복 없는 페이지 번호 배열. 생략하면 전체 페이지 시도 |

검색 대상은 제목과 관리자 keywords다. 공백으로 나눈 query 중 하나 이상을 포함하는 항목을
찾는다. relevance는 일치하는 검색어 개수이며 동점은 게시일·ID 내림차순이다. 본문 검색이나
의미 검색으로 표현하지 않는다. 기본 language=ko, kind=all, sort=date_desc, limit=3이다.
earnings_release/ir_datapack은 earnings, investor_day/strategy_presentation은 strategy로
분류하고 other는 all에서만 나온다. cursor·citations 정렬 등 미지원 조건은 거부한다.
결과 제한으로 일부만 반환하면 partial이며 다음 페이지를 임의로 만들어 주지 않는다.

Read는 현재 사용자·프로젝트의 **검색에서 확인한 ID와 Catalog 버전**만 허용한다.
검색 전 임의 ID 조회, 권한 취소, 현재 allowed_sources·보안 등급·자료 기준일 위반은 차단한다.
I/O 전과 반환 전에 다시 확인하며 denied에는 비인가 문서 메타데이터·건수를 넣지 않는다.

## PDF 근거와 제한

관리자가 보관한 로컬 PDF 또는 명시적으로 승인된 다운로드 PDF만 읽는다. 로컬 파일은
루트 아래 상대 경로, 일반 파일만 허용하고 symlink를 거부한다. 읽을 때마다 원본 해시를
대조한다. 캐시 hit여도 바이트 재확인은 생략하지 않는다.

- 원본 10 MiB, 최대 100페이지. 암호화 PDF와 루트의 자동 동작·JavaScript·첨부 파일 거부.
- 별도 Python `-I` 프로세스에서 pypdf 사용. URL·파일 경로 대신 바이트를 전달한다.
- POSIX 자원 제한: 주소 공간 768 MiB, CPU soft 6초/hard 7초, 부모 timeout 12초.
- 페이지 content stream 2 MiB, 페이지 텍스트 10만 자, 전체 100만 자 제한.
- 파서 실패·시간 초과·해시 불일치는 unavailable. 성공한 빈 검색 empty와 구분한다.

실제로 추출한 문자열만 `ir_pdf_text` span으로 전달한다. span마다 페이지·텍스트 offset·
공식 출처·원본 SHA-256·문서 버전을 남기며 전체 추출 결과에도 해시를 기록한다.
페이지 상태와 read_pages / text_extracted_pages / unread_pages / not_requested_pages를 구분한다.
텍스트가 없는 이미지/빈 페이지는 근거로 넘기지 않지만 진단 정보는 남긴다.
부분 조회·이미지/도형 포함 페이지·일부 추출 실패는 partial이고 전체 조사도 미완료로 표시한다.

OCR, 표 구조 복원, 차트 수치 판독은 지원하지 않는다. 시각 연산자 검출은 보수적인
휴리스틱이다. 감지하지 못한 레이아웃이 있을 수 있어 layout_semantics_verified와
tables_charts_parsed는 항상 false다. 모든 페이지 텍스트가 추출돼도 full_text_read /
original_verified는 **텍스트 확보 상태**이며 문서 주장의 진실성·표/차트 검증을 뜻하지 않는다.
별도 프로세스와 자원 제한은 OS 보안 sandbox를 대신하지 않는다. 운영 전 파서 격리가 필요하다.

캐시는 ID·버전·원본 해시·Catalog binding·요청 페이지를 키로 최대 8개를 보관한다.
새 버전은 재검색해야 한다. 철회는 새 Read/캐시 반환을 차단하며 이미 저장된 보고서·감사
이력을 소급 삭제하지 않는다. 저장 이력의 재열람·폐기는 별도 운영 정책이 필요하다.

## Agent 연결과 의미 구분

Real Research의 Tool 선택 권한과 기존 Schema는 유지했다. 서버는 직무로 도구를 강제
선택하지 않는다. Mock의 기존 도구 선택도 그대로다. Research가 읽은 실제 IR 텍스트를
Analysis에 넘기고 Verification이 재조회한다. 외부 문서는 untrusted_external_data이며
명령·도구 권한·서버 Context를 바꿀 수 없다.

역할 프롬프트에 IR 계획/실적, 기업 전체/특정 기술사업, 회사 전망/독립 시장 검증,
발표일/회계기간, DART 공시와의 중복·불일치 확인을 명시했다. IR ID와 DART ID를 합치지
않고 출처별로 유지한다. 동일 주장의 일치 여부를 Connector가 자동 확정하지 않는다.
이 안내가 실제 모델의 올바른 판단을 보장하는지는 아직 검증하지 않았다.

비공개 Memory·프로젝트 정보 차단, 현재 서버 정책 우선순위, 기존 사용량 원장과 상한은
바꾸지 않았다. 공개 Connector와 Real GPT-4o mini의 동시 실행은 계속 차단하며,
PayloadPolicy도 synthetic=false 자료를 거부한다. 현재 검증은 Mock 모델 + 공개형 합성 PDF다.

## 서버 활성화

서버 설정 예시다. **이번 작업에서 활성화하지 않았다.** 먼저 Catalog JSON을 검수·배치한다.
앱 Python 또는 posco_ir_pdf_python에는 기존 optional `documents` 의존성 pypdf가 필요하다.
환경 설치는 저장소 PM 절차를 사용한다. dependency/lock 파일은 변경하지 않았다.

```toml
[technical_research_sources]
posco_ir_enabled = true
posco_ir_catalog_path = "/srv/reviewed-ir/catalog.json"
posco_ir_local_root = "/srv/reviewed-ir/pdfs"
posco_ir_allow_downloads = false
# posco_ir_pdf_python = "/srv/hermes-documents/bin/python"
```

로컬 Catalog만 쓰면 IR 외부 요청은 없다. URL 항목을 실제 읽으려면 문서별 검수 후
posco_ir_allow_downloads도 별도로 true로 설정해야 한다. API 키는 필요하지 않다.
위 경로·Python 설정은 모델이나 브라우저 사용자가 변경할 수 없어야 한다.
기존 개발 UI는 SSO가 아니므로 사내 사용자 서비스로 바로 배포할 수 없다.

cost는 tool_units, source_requests, local_reads, parser_runs, cache_hit을 구분한다.
로컬 조회도 도구 예산을 사용한다. 중복 Read는 다시 파일/HTTP를 확인하고 그 비용을 기록한다.
금액·외부 쿼터는 확인하지 않았으므로 usd/quota_units=null, verified=false다.
모델 비용이나 기존 usage.json을 이 값으로 대체하지 않는다.

실제 공식 PDF의 한글 폰트·페이지 구성·스캔·복잡한 차트·대용량, 다운로드 MIME/URL 변화,
배포 환경 자원 제한과 보관 권한은 실제 운영 전 확인해야 한다.
Stub 결과는 [POSCO_IR_VALIDATION.md](POSCO_IR_VALIDATION.md)에 기록한다.
