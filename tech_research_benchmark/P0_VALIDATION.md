# P0 구현 및 검증 기록

기준: 29b1c92c. 실제 모델/정보원 API 호출 0, 실제 내부 자료 0.
Hermes 코어·기존 Persona/Memory/Multi-Agent·API 원장·호출 제한 변경 없음.

- 평가 입력 JSON 18개 + Gold JSON 18개. 모든 Profile/Environment와 인자가 펼쳐져 있다.
- Corpus: SYNTHETIC 필수 24개, 방해 4개. 문서에서 정의한 값만 수치로 사용했다.
- 데이터·Gold·Corpus JSON Schema, 11 API별 RP/OP Schema, 참조/순서/기간/권한/상속 검증.
- 입력 전용 로더는 Gold/Corpus를 로드하지 않는다. 실제 Agent 연결이나 도구 실행은 없다.
- SHA-256 manifest는 수정 검출용이다. 전문가 검수 전이며 평가셋 최종 동결은 아직 아니다.
- 개발용 DEV 사례/문서 ID/질문/문장은 평가 파일과 분리한다.

실행:

```bash
python -m tech_research_benchmark.offline
HERMES_TEST_FILE_RETRIES=0 scripts/run_tests.sh -j 3 tests/tech_research_benchmark tests/persona_prototype tests/agent/test_memory_provider.py tests/agent/test_memory_provider_caller_profile.py tests/agent/test_memory_manager_fork_scope.py tests/tools/test_delegate_toolset_scope.py -q
```

검증기: 18개 유효. 공식 runner 통합: **228 통과 / 0 실패** (83.7초, 재시도 0).
기존 회귀 210개(기존 205+안정화 5), 신규 검사 18개. Streamlit 4개 포함.
추가 단독 신규 검사: **18 통과 / 0 실패**.
Streamlit 포함 테스트 환경과 기존 writable scratch wrapper를 사용했다.
외부 DNS 차단과 runner의 자격 증명 제거를 유지했다.

## 미완료와 사람이 확인할 사항

18개별 검수 목록은 README.md 표에 있다. query 의미 동등성, 원문 entailment,
기술적 타당성·업무 품질은 자동 성공으로 판정하지 않는다. structural_success와
business_success를 구분하고 보안 위반이면 후자는 false, 그 밖에는 null이다.

sort의 명시적 대안은 기계적으로 지원한다. 원문 미정인 DA01/IA01/IFA01/ALT 대안과
동의어 query는 pending으로 보관한다. 미정 원문을 지어내 승인된 Gold로 넣지 않았다.
상세 실험 조건·특허 청구항·경쟁기술 일정이 설계 문서에 없으므로 Corpus는 합성 골격이다.
이 상태로 실제 기술 조사 품질이나 전문가 승인 평가 성능을 주장하면 안 된다.
Scorer는 trace의 구조 검사다. supplied_evidence와 read의 연결은 확인하지만 실제 실행
성공·문서 이해를 증명하지 못한다. 반출 탐지도 알려진 span/프로젝트 문자열의 기초 검사다.
향후 전문가 검수, 대안 코퍼스 작성, scorer 의미 평가 확장 후 동결한다.
