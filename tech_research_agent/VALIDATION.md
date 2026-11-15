# 첫 작동 버전 구현 기록

기준 1da7e0b5. 이번 작업은 기술조사 제품 기능과 Mock 기능·보안 회귀다.
벤치마크 개발, 점수 계산, 실제 모델 성능 평가는 추가하지 않았다.

## 실행 결과

- Hermes 기반 Research → Analysis → Verification 순차 실행, 동일 질문의 세 사용자 예제 재현.
- 최종 통합 회귀: **266 통과 / 0 실패**, 177.3초, 3 workers, 파일 자동 재시도 0.
- 신규 앱 기능/보안 검사: **12 통과 / 0 실패**. 사용자별 도구·조건, 승인 선호보다 명시 요청,
  제한 환경, 내부 근거가 포함된 과거 이력의 공개 환경 재사용 차단, 프로젝트/사용자 격리,
  수소환원제철·양극재 전환, scope 복원, Streamlit 요청·도구 패널·사용자 전환을 검사한다.
- P1 회귀는 기존 DEV 데이터만 사용한다. 재무 조회에 IR IF01이 섞이지 않는 검사를 강화했다.
  기준 P1에서 DART와 IR을 함께 허용하면 DEV-B-IF01까지 재무 원문에 포함되는 것을 재현했다.
- 정적 검사 19개 통과. 마지막 UI 원응답 표시 변경의 별도 AppTest 1개와 Ruff/health 2개 재검사도 통과했다.
- 실제 OpenAI/외부 정보원 호출 0, 실제 포스코 내부 자료 0, 기존 원장·상한·Hermes 코어 변경 0.
  기존 P0 평가 입력·Gold·manifest 수정 0. main 병합 없음.

공식 회귀 명령:

```bash
HERMES_TEST_FILE_RETRIES=0 scripts/run_tests.sh -j 3 tests/tech_research_agent tests/persona_prototype tests/tech_research_benchmark tests/agent/test_memory_provider.py tests/agent/test_memory_provider_caller_profile.py tests/agent/test_memory_manager_fork_scope.py tests/tools/test_delegate_toolset_scope.py -q
```

Streamlit 포함 PM 테스트 환경을 사용했다. 환경의 기본 임시 경로가 읽기 전용이어서
기존 외부 scratch wrapper를 사용했으며 공식 runner의 자격 증명 제거/네트워크 차단은 유지했다.

## 실제 작동 예제 (Mock)

[examples/working.json](examples/working.json)은 `python -m tech_research_agent.demo`로 생성했다.
세 사용자 모두 `수소환원제철을 비교 조사해주세요.`를 입력하고 동일 quick 권한을 사용했다.
각 사용자에게서 Hermes가 local Mock 모델 요청 6회를 수행했다. Research의 검색·원문 조회,
Analysis, Verification의 원문 재조회·응답이 실행됐다. 모델 호출은 loopback Mock으로만 향했다.

- researcher: OpenAlex+KIPRIS, 논문/청구항, 최근 1년, limit=3, KR. 근거 H-A01/H-P01.
- strategy: DART material 공시+IR strategy, 최근 1년, limit=3. 근거 H-D01/H-IS01.
- finance: DART 2025 연간 CFS·투자현금흐름/영업이익+IR earnings. 근거 H-F01/H-IF01.
  IR은 Research와 Verification에서 별도로 read_material을 호출한다.

이 도구 선택은 스크립트형 Mock 응답기가 만든 것이다. APP/API를 모델 tool call 형식으로
선택하고 Hermes와 P1이 실제 실행한 연결 동작을 확인한 것이며, 실제 모델의 개인화 추론이나
기술조사 품질이 검증됐다는 의미가 아니다. raw stage 출력과 로컬에서 묶은 보고서를 구분한다.

## 남은 작업

실제 모델을 연결하기 전 명시 요청의 범위/기간/비교 기준을 안정적으로 처리해야 한다.
현재 Mock은 정해진 fixture 표현과 source focus만 처리한다. 실제 API connector, SSO,
문서 ACL/철회와 저장 이력 보존·삭제, 분산 세션/예산, 실 자료 반출 정책은 미구현이다.
의미적 주장 검증·실제 실험/특허·재무 분석은 기계적 인용/숫자 검사로 대체할 수 없다.
