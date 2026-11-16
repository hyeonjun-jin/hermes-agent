# OpenDART v1 검증 기록

기준 `56c7e517`, 2026-11-16. 실제 OpenAI·OpenDART·OpenAlex·기타 정보원 API 호출은 **모두 0회**다.
실제 사내 자료, 실기업 재무 값, 운영 인증키를 사용하지 않았다. 공식 개발가이드 웹 페이지 조회와
API 실행은 구분했다. 테스트 회사 `12345678`과 금액·접수번호는 전부 직접 만든 fixture다.
테스트의 verified=true는 서버 Catalog 설정 형태를 재현한 것이며 실기업 검증 사실이 아니다.

## 실행과 결과

공식 runner를 사용했다. 이 환경의 Streamlit 포함 테스트 인터프리터는
`HERMES_PYTHON=/workspace/work/hermes-ui-test-python`, 자동 파일 재시도는
`HERMES_TEST_FILE_RETRIES=0`으로 비활성화했다.

```bash
scripts/run_tests.sh -j 4 \
  tests/tech_research_agent tests/persona_prototype tests/tech_research_benchmark \
  tests/agent/test_memory_provider.py tests/agent/test_memory_provider_caller_profile.py \
  tests/agent/test_memory_manager_fork_scope.py tests/tools/test_delegate_toolset_scope.py -q
python scripts/check --staged --base 56c7e517
```

- 최종 통합 회귀: **27개 파일, 399개 테스트 통과, 실패 0**, 151.7초.
- 포함: 신규 OpenDART 70개, OpenAlex 36개, 기존 Streamlit 3개,
  Persona·Memory·Multi-Agent·Alignment·Real 예산/반출 정책, P0/P1 보존 검사,
  Hermes MemoryProvider/프로필 격리/delegate 도구 범위.
- 전체 정적 검사 **19개 통과**. 마지막 안내 문구 정리 후 ruff·code health 및 관련 테스트를 추가 실행했다.
- Hermes 코어, P0/P1 데이터/Gold/Scorer, 운영 원장·유료 한도는 변경하지 않았다.

## 확인한 계약

| Stub 입력/조건 | 확인한 결과 |
|---|---|
| 회사별 기간/유형/결과 수 지정 | corp_code, bgn_de/end_de, pblntf_ty/detail_ty, page_count 매핑. 첫 페이지 1회 전송 |
| 제목 keyword 미매칭, total_page>1 | partial, 범위 제한 경고. 관련 공시 전체가 없다고 처리하지 않음 |
| 검색 → 원본 ZIP Read → Analysis → Verification | 검색 접수번호만 사용. 본문 span이 Analysis에 전달되고 Verification이 원본 재조회 |
| 재무 API → Verification | 동일 회사/사업연도/보고서 코드/CFS로 API 재조회. 임의 공시 ZIP Read로 바꾸지 않음 |
| CFS/OFS, 11011/11012/11013/11014 | 요청/응답 기준과 당기·누적 값을 분리 보존 |
| 공식 영업이익·투자현금흐름 ID | canonical ID 매핑, 금액 원문·부호·통화·회사 기준 보존 |
| 모르는 ID·빈 금액·회사/기간 불일치·미래 접수 | 추측 매핑/0 대체 없음. partial, 원자료 확인 완료 표시 차단 |
| 서로 다른 계정 집합 | source_id를 구분해 이전 근거를 덮어쓰지 않음 |
| 여러 접수번호/중복 계정 | 임의 합산/최신 선택 없이 별도 보존, partial |
| 정상 빈 결과/013 | 검색·재무는 empty; 원본 요청은 본문 미확보 unavailable |
| 인증·IP 실패 | denied. 요청 전 정책 차단과 실제 API 거부의 실행 여부/비용 구분 |
| 쿼터 020, HTTP 429/5xx, timeout, redirect, 잘못된 JSON | unavailable. 재시도/다른 URL 접근 없음 |
| 인증키 echo/오류 message | 키나 raw 오류 본문이 Trace에 들어가지 않음 |
| 손상 ZIP, 과도한 압축률/파일 수/파일 크기/총 해제량 | unavailable. 디스크 추출 없음 |
| 경로 이탈·절대경로·심볼릭 링크, DTD/외부 엔티티/UTF-16 DTD | 거부. 본문 검증 완료로 표시하지 않음 |
| 지원 XML + 미지원 첨부, section 부분 조회 | partial, full_text_read/original_verified=false |
| 합성/미등록 기업코드, 미확인 접수번호, 잘못된 OP/cursor | HTTP 전송 전에 denied |
| 사용자/프로젝트/정보원/분류/예산 위반 | 기존 정책 + 회사 Catalog 검사로 전송 전 차단 |
| 검색 후 회사 권한 취소 | Read 차단, 결과 문서 없음 |
| 재무 I/O 중 권한 취소 | 비용은 기록하되 반환 items/rows/경고에서 자료 제거 |
| 실제 공개자료 + Real 모델 | 첫 모델 요청 전 차단. PayloadPolicy도 synthetic=false를 계속 거부 |
| 공시 Read 실패 + 다른 정보원 근거 성공 | 다른 근거만으로 complete=true가 되지 않음. 실패 상태와 조회 한계를 보고서에 안내 |

개발 중 테스트 두 곳을 수정했다. ZIP helper가 입력 dict에 `.items()`를 적용하지 못한 괄호 문제는
fixture 생성 오류였고, 제목 필터의 미매칭 테스트는 검색어의 한 단어가 실제 제목에 포함되어 있어
겹치지 않는 검색어로 교체했다. 검사 조건을 삭제하거나 정책 조건을 완화하지 않았다.

실제 API의 인증·쿼터·최신 공시 형식·Taxonomy/회계기간, 실제 모델의 도구 선택·개인화·재무 해석·
인젝션 대응은 검증하지 않았다. 서버 설정과 남은 작업은 [OPENDART_CONNECTOR.md](OPENDART_CONNECTOR.md)에 있다.

마지막 변경 확인: Connector·UI **73개 통과**, 비용/쿼터 표시 정리 후 Connector **70개 통과**.
지원하지 않는 XML 인코딩의 LookupError도 발견해 처리하고 동일 Connector 70개를 재확인했다.
전송 시도 횟수는 기록하지만 외부 서비스의 실제 쿼터 차감은 확인하지 않았으므로
quota_units=null, quota_verified=false로 유지한다. `git diff --cached --check`도 통과했다.
