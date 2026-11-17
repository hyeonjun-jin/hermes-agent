# Persona Alignment 검증 기록

2026-11-17. 기준 `20a87a24`. 실제 OpenAI·공개 정보원 API 호출은 **0회**다.
사내 실자료를 사용하지 않았고 운영 usage.json·유료 한도·Hermes 코어·기존
persona_prototype Alignment 코드와 P0/P1 데이터·Scorer를 변경하지 않았다.

## 기능 검사 범위

신규 테스트 파일에서 비-loopback socket과 실제 RealAdapter._network_send를 실패시키도록
했다. Hermes는 localhost Mock/Stub gateway만 사용한다. Replay 앱에는 실제 Connector나
Real Adapter를 넘기지 않으며 기존 SYNTHETIC Corpus를 사용한다.
후보 합의·transaction 단위 테스트는 명시적인 가상 조사 스냅샷/UnitReplay로 검사하고,
별도 통합 테스트에서 네 번의 실제 Hermes Mock 조사와 paired TechnicalMockReplay를 실행한다.
가상 입력과 실제 공개자료 수집을 혼동하지 않는다.

| 검사 | 확인 결과 |
|---|---|
| 사용자별 피드백·원래 조사 연결 | 원래 질문/Profile/Environment/버전/실제 Trace/결과 스냅샷과 해시 보관 |
| 확인·동의 없는 피드백, 미완료 조사 | 저장은 하되 후보 입력에서 제외 |
| 한 조사 반복 편집 | 한 경험으로만 계산. 네 번 편집해도 부족 상태 |
| 자유 의견/권한 변경 지시문 | PRIVATE 저장, 모델 컨텍스트와 후보 지시문에서 제외 |
| APP/API/기간/limit/sort/분석 기준/표현 선호 | allowlist 스키마 검사. 권한·보안·자유 지시문·미지원 정렬 거부 |
| 후보 생성·승인 전 | 활성 v1 유지. 같은 Profile/Environment의 before/after 입력·Trace 분리 |
| 명시 승인 | v2 생성. 다음 조사에서 source APP/OP와 컨텍스트 버전·분석 기준·보고 형식 반영 |
| 오래된 후보 | 피드백 변경/동의 취소·Legacy 선호 변경·버전 변경 후 승인 차단 |
| 중복 승인·거절 후 승인 | 차단. 이전 버전과 변경 로그 보존 |
| 사용자·프로젝트 경계 | 타인 조사 ID/제안 ID 피드백·활성화 차단. 다른 프로젝트 Persona는 v1 유지 |
| 현재 프로젝트 권한 취소 | 조회·롤백 등 작업 거부 |
| 롤백 | v1 선호를 복원한 새 v3. 이후 v2 선호 복원도 새 v4로 기록 |
| 현재 '논문만' 요청 | 논문·특허 선호보다 우선 적용되는 Mock 예제 확인 |
| restricted Environment | 외부 APP 선호로 권한 확장 안 됨. 기존 내부 Mock 정책 유지 |
| 기간·결과 수 선호 | 현재 Environment보다 넓은 60개월/10건 선호를 quick의 기존 범위/3건 안내로 제한 |
| 보고서 형식만 변경 | 연구소/전략실/재무팀의 기존 검색 인자 그대로 유지. report_format이 OP에 없음 |
| Tool Schema 경계 | Persona 승인 전후 동일. 버전은 컨텍스트/감사 정보에만 추가 |
| PRIVATE Persona | 기존 PUBLIC 처리 경로에서 차단. 사용자 승인이 공개 반출 승인이 되지 않음 |
| 버전 변경/롤백 후 기존 승인 해시 | 같은 선호라도 새 버전이면 기존 preference grant로 전송 불가 |
| Real 실행 경로 + Stub | Persona는 논문/특허 선호지만 Stub이 선택한 OpenDART를 그대로 실행. 서버가 선호 APP를 강제하지 않음 |
| Streamlit | 후보 생성/거절/승인, 활성 버전, 다음 조사 버전, 구조화 피드백 저장, 이력, 롤백, 사용자 전환 확인 |

## 실행 예제에서 본 변화

SYNTHETIC 수소환원제철 질문 / 연구소 / quick, 기존 papers_only 선호.

- v1: OpenAlex 검색·Read, limit=3, date_desc.
- 네 완료 조사에 구조화된 논문+특허·실험 조건/재현성·청구항·조건을 맞춘 비교 피드백 확인/동의.
- 후보 Replay: v1/v2를 격리된 앱에서 같은 질문·환경으로 실행하고 두 Trace를 보존.
- 승인 후 v2: Mock이 OpenAlex+KIPRIS를 선택. limit=2, OpenAlex relevance, KIPRIS date_desc.
  기간은 기존 근거가 있는 2025-10-01~2026-09-30을 유지한다. 보고서 형식은 별도 표 선호로 반영.
- 롤백 후 v3: 원래 papers_only 선호로 복원. 이전 v2 조사 기록은 그대로 남는다.

6개월로 줄인 별도 후보는 합성 자료의 발행일 범위에 근거가 없어 replay_failed로 남고
승인을 거부했다. 자료 날짜를 바꾸거나 빈 결과를 근거 확보로 처리하지 않았다.

Real 경로 Stub은 다른 검증이다. 수집된 가상 피드백에 기반한 Persona를 명시적으로
PUBLIC_SYNTHETIC 테스트 값으로 지정하고, 실제 전송 없는 임시 usage.json을 사용했다.
Stub은 선호와 다른 OpenDART 재무 API를 선택했고 R2/A1/V2, 총 다섯 요청으로 실행됐다.
이는 Context가 모델에 전달되고 선택 경계가 유지된다는 확인이며 모델의 학습·개인화
판단 능력을 입증하지 않는다. 운영 원장/예산과 실제 반출 승인은 활성화하지 않았다.

## 테스트 실행

기존 PM 테스트 환경의 Streamlit/pypdf를 재사용했다. 공식 runner와 자동 재시도 0 설정으로
실행했다. 환경 전용 interpreter wrapper는 쓰기 가능한 임시 scratch 경로를 사용한다.

```bash
HERMES_PYTHON=/workspace/work/hermes-ir-test-python HERMES_TEST_FILE_RETRIES=0 \
scripts/run_tests.sh -j 4 \
  tests/tech_research_agent tests/persona_prototype tests/tech_research_benchmark \
  tests/agent/test_memory_provider.py tests/agent/test_memory_provider_caller_profile.py \
  tests/agent/test_memory_manager_fork_scope.py tests/tools/test_delegate_toolset_scope.py -q
python scripts/check --staged --base 20a87a24
```

중간 통합 회귀 31개 파일/580개 통과. 보고서 형식만 변경할 때 기존 deep 검색 정렬이
의도하지 않게 달라지는 Mock 문제를 수정하고, 해당 회귀를 포함한 신규 Alignment 28개와
기존 Application 11개가 통과했다.

- 최종 **31개 파일, 581개 테스트 통과, 실패 0**, 313.1초, 자동 재시도 없음.
- 신규 기술조사 Alignment **28개**에 paired Hermes Replay와 Streamlit 전체 흐름 포함.
- 기존 PersonaAgent Alignment **8개**, 승인 공개자료 **38개** 통과.
- 기존 OpenAlex **36개**, OpenDART **70개**, KIPRIS Plus **58개**, POSCO IR **57개** 통과.
- Persona/Memory/사용자 scope, Multi-Agent, 예산, 기존 UI, P0/P1 보존 회귀 포함.
- 정적 검사 **19개 통과**, code health 차단/권고 항목 0.

## 검증하지 않은 것

실제 모델의 APP/API/파라미터 선택 개선, 자연어 피드백 이해, 개인화 만족도, 상세 분석·
사실 정확성 향상은 검증하지 않았다. 현재 후보 생성은 제한된 구조화 값의 합의이고,
Replay의 완료/정책 검사는 성능 평가나 benchmark 점수가 아니다.

실제 사내 SSO·프로젝트 ACL은 기존 개발용 접근 계약/fixture를 대체해야 한다.
장기/대용량 이력의 저장·삭제, 다양한 업무 환경의 전문가 검수, 자동 선호 제안 모델과
충돌/망각 정책은 후속 작업이다. 새 버전은 기본 PRIVATE이므로 공개 모델 사용에는
별도 분류와 정확한 Memory 재승인, 기존 공개자료 승인·운영 예산 조건이 필요하다.

설계·스키마·UI 사용 흐름은 [PERSONA_ALIGNMENT_INTEGRATION.md](PERSONA_ALIGNMENT_INTEGRATION.md)에 기록했다.
