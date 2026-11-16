# POSCO IR Connector v1 검증 기록

기준 `d7adc2ca`, 2026-11-16.
실제 OpenAI·POSCO IR·OpenAlex·OpenDART·KIPRIS Plus 정보원 API 호출은 **모두 0회**다.
공식 홈페이지의 공개 HTML·검색 색인을 확인했지만 실제 IR PDF는 다운로드하지 않았다.
실제 사내 자료·기업 실적 수치도 사용하지 않았다.

## 테스트 환경과 실행

기존 테스트 환경에는 pypdf가 없어 PM으로 별도 환경을 만들었다. 저장소에 이미 선언된
optional documents 의존성 pypdf 6.21.4와 Streamlit을 포함한다. 기존 환경·운영 원장·
한도·pyproject.toml·uv.lock은 변경하지 않았다. 이 작업에서는
`HERMES_PYTHON=/workspace/work/hermes-ir-test-python`, `HERMES_TEST_FILE_RETRIES=0`을 지정했다.
runner scratch 경로를 쓰기 가능한 임시 디렉터리로 설정한 환경 전용 wrapper를 사용했다.

```bash
scripts/run_tests.sh -j 4 \
  tests/tech_research_agent tests/persona_prototype tests/tech_research_benchmark \
  tests/agent/test_memory_provider.py tests/agent/test_memory_provider_caller_profile.py \
  tests/agent/test_memory_manager_fork_scope.py tests/tools/test_delegate_toolset_scope.py -q
python scripts/check --staged --base d7adc2ca
```

신규 테스트는 pypdf로 직접 생성한 합성 PDF를 **실제 별도 파서 프로세스**에서 읽는다.
외부 다운로드 경로는 httpx.MockTransport 응답만 사용했다. 테스트용 공식 호스트 URL은
접근 권한이나 실제 문서 존재를 주장하는 Catalog가 아니며 운영에 등록하지 않는다.
이전 508개 테스트 실행은 통과했고, 파일 크기·HTTP 오류·미활성 차단 테스트를 추가해
최종 회귀를 재실행했다.

- **29개 파일, 514개 테스트 통과, 실패 0**, 263.9초. 자동 재시도 없음.
- 신규 IR **57개**, 기존 OpenAlex **36개**, OpenDART **70개**, KIPRIS Plus **58개** 포함.
- 기존 Agent UI 3개·Persona Streamlit UI 4개와 Persona·Memory·Multi-Agent·Alignment,
  Real 예산/반출, P0/P1 보존, Hermes MemoryProvider/사용자 scope 회귀 통과.
- `scripts/check` **19개 검사 통과**, code health 차단/권고 항목 0.
- Hermes 코어·운영 원장·한도·P0/P1 데이터·Gold·Scorer 변경 없음.

## 확인한 동작

| 조건 | 확인 결과 |
|---|---|
| Catalog 등록 | 필수 필드·PUBLIC 검수·명시 ACL·공식 호스트·상대 PDF 경로·게시/검증 시각·버전/SHA 검사 |
| Catalog 불일치 | 중복 ID, 같은 버전의 변경 해시, 잘못된 URL·미래 검수일·언어/유형 거부 |
| 검색 | query, 게시 기간, earnings/strategy/all, ko/en, date_desc/relevance, limit 처리. 제목/keywords 외 본문 검색 없음 |
| 미지원 OP | cursor·citations 정렬·잘못된 kind/language/limit 등 denied. 조건을 제거해 실행하지 않음 |
| 정상 PDF | 페이지 텍스트·span ID·원본 SHA/버전·추출 결과 SHA·출처·조회 시각 유지 |
| 이미지/도형/빈 페이지 | image_or_graphic_only, partial_visual, no_extractable_text 구분. partial 및 미확인 페이지 유지 |
| 일부 페이지만 요청 | 해당 페이지 텍스트만 span에 포함. 나머지는 not_requested/unread, 전체 읽기 false |
| 잘못된 PDF | 손상·암호화·101페이지·파일 크기 초과를 unavailable 처리. 근거 생성 안 함 |
| 파서 제한 | subprocess timeout·출력 해시 불일치 차단. 과대 로컬 파일은 파서 실행 전 차단 |
| 외부 다운로드 | 등록 URL만 요청. redirect 불허. 401 denied, 429/잘못된 MIME/변경 바이트 unavailable |
| 로컬 경로 | symlink 차단. 응답에 로컬 경로 노출 없음 |
| 캐시 | 정상 반복 Read는 파싱 캐시 재사용하되 파일/해시 재확인. 파일 변조 후 unavailable·캐시 무효화 |
| 버전 변경·철회 | 캐시 제거. 이전 검색 binding Read 거부, 새 버전은 재검색 필요. 철회 문서는 검색에 없음 |
| 사용자·프로젝트·자료 정책 | 현재 서버 Context와 Catalog ACL 확인. 미확인 ID·비공개 프로젝트 검색어·RESTRICTED·예산 초과 차단 |
| 조회 중 권한 취소 | 파싱 도중 철회하면 반환 전 denied, 항목 없음·캐시 무효화 |
| 비활성 Connector | 실행·외부 요청·도구 예산 차감 없음 |
| Hermes RAV | 전략실 Mock의 IR 검색 → PDF Read → Analysis → Verification 재조회. 실제 추출 텍스트 전달 |
| IR와 DART | 별도 source_id·origin·synthetic 표시 유지. 공시 일치/회계기간 검증을 자동 true로 바꾸지 않음 |
| 읽지 못한 IR | 이미지 전용 항목은 원문 근거에서 제외. 다른 출처가 성공해도 전체 조사 미완료 |
| Real 반출 | 공개 Connector 동시 실행 차단 및 synthetic=false PayloadPolicy 거부 유지 |

첫 실행에서 이미지 전용 PDF의 페이지 진단 정보가 빠지는 문제를 발견했다.
허가된 문서의 진단 정보는 남기되 텍스트 없는 항목을 Analysis 원문 근거에 넣지 않게 수정했다.
P1의 사전 denied 응답은 items 키가 없을 수 있어 기존 무자료 계약에 맞춰 검사했다.
정적 검사의 광범위 예외 포착은 구체적인 파서/내장 예외로 바꿨다.

## 해석과 남은 확인

Mock의 선택 규칙·분석 문구가 실행됐다는 결과다. GPT-4o mini의 자율 도구 선택,
개인화 품질, IR 의미 해석 또는 DART와의 사실 일치를 검증한 것이 아니다.
실자료 전송·유료 예산·추가 모델 호출은 활성화하지 않았다.

실제 공식 PDF의 한글 폰트·스캔·표/차트·복잡한 레이아웃·큰 파일과 현재 다운로드 경로는
미검증이다. OCR과 표/차트 수치 복원은 미지원이다. 성공한 텍스트 추출도 주장의 진실성을
증명하지 않는다. Catalog의 회계기간·법인 범위는 관리자 기재값이며 별도 원문 검수가 필요하다.

공식 자료의 공개성·이용조건 검수, 운영 파서 sandbox, SSO/실 ACL 연결, 여러 worker의
Catalog 변경/철회 전파, 저장 보고서의 철회 후 재열람·삭제 정책은 운영 전 작업이다.
새 벤치마크·Scorer 기능과 Hermes 코어는 변경하지 않았다. P0/P1 테스트 실행은 기존
데이터·정책 보존 확인용이며 Gold를 Agent/Connector 실행 입력으로 읽지 않는다.

활성화 설정과 공식 자료실 확인 범위는 [POSCO_IR_CONNECTOR.md](POSCO_IR_CONNECTOR.md)를 참고한다.
