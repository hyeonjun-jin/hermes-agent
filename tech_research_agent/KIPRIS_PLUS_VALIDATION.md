# KIPRIS Plus Connector v1 검증 기록

기준 커밋 `38a3f4e3`, 2026-11-16.
실제 OpenAI·KIPRIS Plus·OpenAlex·OpenDART·기타 정보원 API 호출은 **전부 0회**다.
공식 서비스 안내·약관·popup 입출력 명세 페이지를 확인했으며, 실제 특허 API의 응답을 수집하지 않았다.
명세의 XML 계층에 맞춰 출원번호·명칭·출원인·날짜·청구항을 직접 만든 합성 fixture로 검증했다.
서비스 신청·결제·키 발급과 실제 서버 활성화는 하지 않았다.

## 실행 결과

공식 테스트 runner를 사용했다. 이 작업 환경에서는 Streamlit이 설치된 인터프리터를
`HERMES_PYTHON=/workspace/work/hermes-ui-test-python`으로 지정하고
`HERMES_TEST_FILE_RETRIES=0`으로 자동 재시도를 끈 상태에서 실행했다.

```bash
scripts/run_tests.sh -j 4 \
  tests/tech_research_agent tests/persona_prototype tests/tech_research_benchmark \
  tests/agent/test_memory_provider.py tests/agent/test_memory_provider_caller_profile.py \
  tests/agent/test_memory_manager_fork_scope.py tests/tools/test_delegate_toolset_scope.py -q
python scripts/check --staged --base 38a3f4e3
```

- **28개 파일, 457개 테스트 통과, 실패 0**, 136.0초.
- 신규 KIPRIS Plus **58개**, OpenAlex **36개**, OpenDART **70개**, 기존 Streamlit **3개** 포함.
- Persona·Memory·Multi-Agent·Alignment·Real 예산/반출, P0/P1 데이터·정책 보존,
  Hermes MemoryProvider·사용자 홈·delegate 도구 범위 회귀도 포함했다.
- 정적 검사 **19개 통과**. 첫 ruff 검사의 테스트 bytes literal 표기는 수정했다.
- 운영 원장·유료 한도, Hermes 코어, P0/P1 데이터·Gold·Scorer는 변경하지 않았다.

## Stub에서 확인한 내용

| 조건 | 결과 |
|---|---|
| KR 검색, 공개일 기간, 출원인, 단일 IPC, date_desc, limit | 공식 word/openDate/applicant/ipcNumber/OPD/numOfRows 매핑, 첫 페이지 1회 요청 |
| 출원번호·공개번호·공고번호·등록번호 | 별도 필드 유지. 검색에서 반환한 출원번호만 Read 허용 |
| 공개일과 출원일 | published_at은 openDate만 사용. 공개일 누락을 출원일로 채우지 않음 |
| 검색 → 상세 → Analysis → Verification | 상세의 청구항 원문이 Analysis에 전달되고 Verification이 같은 출원번호로 재조회 |
| include_claims=true, 정상 claimInfoArray | patent_claim span에 원문 보존. 로컬 순서를 공식 청구항 번호로 만들지 않음 |
| 청구항 없음·개수 불일치·개수 미제공·중복 텍스트 | partial, original_verified/claims_complete=false. 전체 조사도 미완료 |
| include_claims=false | 초록·서지 근거만 채택. 초록을 청구항으로 바꾸지 않음 |
| 다른 XML 계층의 description/claim | 공식 청구항 경로가 아니므로 채택하지 않음 |
| 검색과 다른 상세 출원번호 | unavailable. 다른 특허의 텍스트를 근거로 붙이지 않음 |
| 정상 빈 items, totalCount=0 | empty |
| 총 결과가 첫 페이지보다 많음 | partial + first_page_only. 추가 요청 없음 |
| 잘못된 관할·미지원 정렬·다중 IPC·잘못된 IPC·미발급 cursor·과도한 limit | 전송 전에 denied. Schema와 정책 완화 없음 |
| 미래 날짜·내부 프로젝트 ID 검색 | 전송 전에 denied |
| 미활성·서비스 미승인·키 없음 | 전송 전 denied, 비용/도구 예산 0 |
| XML 접근/만료 오류·HTTP 401/403 | denied, 빈 결과와 구분 |
| XML 오류22·기타 코드·HTTP 429/5xx·timeout·redirect | unavailable. 자동 재시도/HTTP 전환/다른 호스트 요청 없음 |
| 잘못된 XML·JSON·DTD/외부 엔티티·UTF-16 DTD·미지원 인코딩 | unavailable. 원문을 읽었다고 표시하지 않음 |
| 응답 크기 한도 초과 | unavailable |
| 정보원·프로젝트·사용자·보안 등급·도구 예산 위반 | P1 정책이 요청 전에 차단 |
| 미확인 공개번호/등록번호를 Read 인자로 사용 | seen의 출원번호가 아니므로 차단 |
| 검색 후 권한 취소, I/O 중 권한 취소 | 전송 전 또는 반환 전 차단. 반환 항목·경고에 자료가 남지 않음 |
| 비공개 Memory 포함 실행 | Agent 실행 전에 차단 |
| 공개 실자료와 Real 모델 | 첫 모델 요청 전 차단, 기존 PayloadPolicy도 synthetic=false 자료 거부 |
| HTTPX INFO 로그 | 실제 transport에는 ServiceKey가 전달되지만 일반 요청 URL·Trace·로그에는 인증키 없음 |
| 특허 본문에 외부 다운로드 명령/URL 포함 | Mock의 데이터로만 전달. 요청은 정해진 KIPRIS 두 operation에만 발생 |

정상 RAV Stub 흐름에서 KIPRIS 요청은 검색 1회 + Research 상세 1회 + Verification 상세 1회였다.
동시에 기존 합성 논문 근거도 전달됐다. 특허 기재를 실험 검증 결과·상용화·현재 권리 유효성·FTO로
확정하지 않는 프롬프트/Mock 안내를 확인했다. 이는 실제 모델의 판단 능력을 검증한 결과가 아니다.

XML fixture는 공식 필드명·계층을 따르지만 실제 서비스의 모든 변형을 재현하지 않는다.
특히 claimCount와 배열 개수의 일치가 실제 청구항의 법률적 완전성을 증명하지는 않는다.
다운로드 경로 조회/PDF·TIFF 파싱은 구현하지 않았고 해당 요청은 발생하지 않았다.

공식 명세에서 확인한 기능, 제한 사항과 운영 활성화 조건은
[KIPRIS_PLUS_CONNECTOR.md](KIPRIS_PLUS_CONNECTOR.md)에 기록했다.
실제 HTTPS 접속·인증키·상품 승인·계정별 요금/쿼터·검색 품질·최신 응답·권리 상태 해석은 미검증이다.
