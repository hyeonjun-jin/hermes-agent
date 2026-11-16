# OpenAlex Connector 검증 기록

2026-11-16, 기준 커밋 `5eca36d1`.

실제 OpenAI 호출 **0회**, 실제 OpenAlex 및 다른 정보원 API 호출 **0회**.
공식 문서 웹 페이지를 확인했으며 API 호환성 검증에 사용한 응답은 모두 가짜 fixture다.
운영 usage.json·한도와 P0/P1 평가 자료는 변경하지 않았다.

## 재현 명령

저장소 공식 테스트 runner를 사용했다. 이 작업 공간에서는 Streamlit이 설치된 테스트
인터프리터를 `HERMES_PYTHON=/workspace/work/hermes-ui-test-python`으로 지정했다.
`HERMES_TEST_FILE_RETRIES=0`으로 자동 재시도 없이 실행했다.

```bash
scripts/run_tests.sh -j 4 \
  tests/tech_research_agent tests/persona_prototype tests/tech_research_benchmark \
  tests/agent/test_memory_provider.py tests/agent/test_memory_provider_caller_profile.py \
  tests/agent/test_memory_manager_fork_scope.py tests/tools/test_delegate_toolset_scope.py -q
python scripts/check --staged --base 5eca36d1
```

기존 P0/P1 테스트도 회귀 검증에 포함했으며 새 벤치마크나 채점 기능을 추가하지 않았다.

## 확인한 실행 결과

| 입력·조건 (전부 Stub) | 반환·실행 기록 |
|---|---|
| hydrogen 검색, 기간 2026-01-01~2026-09-30, article/review, limit=2, citations_desc | /works에 search/filter/per_page/sort 전달, ok |
| 검색에서 받은 W123을 read_work(include_abstract=true) | /works/W123, 실제 fixture 초록 span·DOI·저자·출처 반환, full_text_read=false |
| 같은 검색 2회 후 Read 1회 | source_requests 합계 3, 작업 호출 예산 3회 소모 |
| include_abstract=false | abstract=null, 원본에 초록이 있으면 abstract_available=true, metadata_only |
| 초록 없는 fixture | partial, metadata span만 반환, 전체 조사 complete=false |
| 정상 응답의 results=[] | empty |
| limit=11, 모르는 OP, 미래 기간, types 필터 주입, 미발급 cursor | denied, HTTP 전송 0회 |
| INTERNAL/RESTRICTED, 비허용 정보원, 예산 초과, 기밀 용어 포함 검색 | denied, HTTP 전송 0회 |
| 검색 전 임의 W123 Read / 검색 후 권한 취소 | denied, 문서 결과 없음 |
| Read I/O 중 권한 취소 | 전송 비용은 기록하되 반환 문서·경고에서 ID/본문 제거, denied |
| timeout·429·5xx·redirect·깨진 JSON | unavailable, 자동 재시도 없음, API 오류 본문/키 기록 없음 |
| 공개 Connector + Real 또는 비공개 Memory | 모델·정보원 요청 전에 차단 |
| 외부 텍스트에 명령 문구 포함 | Mock의 데이터로 전달; 허용 역할/도구 외 추가 실행 없음 |

Hermes 통합 경로에서 Research 검색 1회 → Read 1회 → Analysis → Verification Read 1회를
Mock 모델과 HTTP Stub으로 실행했다. Analysis 원응답에는 조회된 초록이 전달됐고,
별도 성공 기준으로 인용/숫자 확인이 필요하다는 기존 처리도 유지했다.
이는 실제 LLM의 검색 선택·인젝션 대응·기술 판단이 올바르다는 증거가 아니다.

## 검증 중 발견한 문제

첫 통합 실행에서는 새 공개 정보원 UI 테스트 하나가 실패했다. 앞선 AppTest에서 만든
`st.cache_resource`의 Offline 애플리케이션이 다음 테스트에도 남아서 새 Connector 설정이
보이지 않았다. 테스트마다 Streamlit resource cache를 시작/종료 시 비우도록 격리했다.
assertion은 유지했고 수정 후 Connector·UI 테스트를 다시 실행했다.

정적 검사에서는 새 정책 테스트의 긴 조건 분기가 지적돼 입력별 설정 표로 바꿨다.
정책 검사 조건은 완화하지 않았다.

최종 테스트 및 정적 검사 결과는 아래에 기록한다.

- 최종 통합 실행: **26개 파일, 329개 테스트 통과, 실패 0**, 232.9초 (`-j 4`).
- 그중 신규 Connector: **36개 통과**, Streamlit AppTest: **3개 통과**.
- 포함 범위: 기존 Persona·Memory·Multi-Agent·Alignment, Real 예산/역할/반출,
  P0/P1 Schema·정책·manifest, Hermes MemoryProvider/프로필 격리/delegate 도구 범위.
- 정적 검사: **19개 통과**. 마지막 변경에 대해 ruff·code health를 추가 확인했다.
- `git diff --cached --check`: 통과.

실제 공개 API의 응답·속도·쿼터와 GPT-4o mini의 개인화 품질은 이 테스트로 검증하지 않았다.
활성화 설정과 남은 제약은 [OPENALEX_CONNECTOR.md](OPENALEX_CONNECTOR.md)에 정리했다.
