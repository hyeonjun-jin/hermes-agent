# 피드백 기반 Persona 후보 검증

## 논문 확인과 구현 범위

저장소의 [PersonaAgent 논문](../references/personaagent.pdf) §2.2, Algorithm 1
(인쇄 페이지 26424), 부록 B/C (26432–26433)를 읽고 구현했다.

논문은 최근 사용자 상호작용을 `(질문 q, 재생 응답 r̂, 사용자 정답 r_gt)` 배치로 구성한다.
현재 Persona로 응답을 시뮬레이션하고, `LLM_grad`가 응답과 정답의 차이를 텍스트 손실/
피드백으로 기술한다. `LLM_update`는 집계한 텍스트 피드백으로 Persona 프롬프트를 수정하며
이를 E회 반복한다. 가중치 학습이 아니라 텍스트 프롬프트 최적화이고 도구 집합은 고정된다.
논문 부록 D의 최소 도구 호출 지침은 단순 인사에 도구를 쓰지 않는 이 앱의 정책과 달라
그대로 채택하지 않았다.

| 항목 | 논문 | 이번 프로토타입 |
|---|---|---|
| 목표 신호 | 사용자 정답 응답과 모델 응답 간 텍스트 손실 | 동의한 명시적 형식·검색 초점 라벨 |
| 후보 생성 | LLM 텍스트 피드백과 프롬프트 재작성, 반복 최적화 | 최소 3건의 일관된 선호로 한 후보 생성 |
| 평가 | 논문 데이터·작업별 지표 | 분리한 마지막 피드백 질문의 로컬 Mock Hermes 재생 |
| 데이터 | 최근 사용자 상호작용 배치 | 최대 12개의 동의한 서로 다른 턴, 최소 4개 |
| 안전성 | 논문의 프레임워크 | 출처·권한 검사, 승인, 불변 버전 이력·롤백 추가 |
| 적용 시점 | Persona를 반복 최적화 | 개선 후보 제안 → 별도 승인 → 새 세션부터 적용 |

**LLM_grad, LLM_update, TextGrad 반복 최적화와 실제 LLM 평가기는 구현하지 않았다.**
후보 생성은 결정적 규칙이며, 이번 구현을 논문 알고리즘의 완전한 재현으로 부르지 않는다.

## 기존 구조와 연결

기존 `build_persona()`는 Profile의 프로젝트·언어와 Semantic Memory의 명시적인 응답 형식을
결합했다. Episodic Memory는 확인된 선호만 prefetch하고, 모델의 새 응답은 unconfirmed로
저장했다. 웹 피드백은 `web_feedback`에 평가·의견을 저장할 뿐 Persona를 바꾸지 않았다.

이번에는 다음을 추가했다.

1. **수집**: 기존 피드백 저장은 유지한다. 별도의 동의와 allowlist 선호가 있는 피드백만
   `preference_feedback`에 들어간다. 자유 의견은 기본적으로 학습 데이터가 아니다.
2. **분석**: 마지막 1건은 검증용으로 남긴다. 나머지에서 같은 필드의 선호가 최소 3번
   일관되게 확인된 경우만 후보에 반영한다. 충돌·부족·현재와 같은 선호는 제안하지 않는다.
3. **비교**: 원 Persona/후보 Persona로 같은 검증 질문과 사실 조회 질문을 기존 Hermes
   Agent Loop·native Subagent로 재생한다. 양쪽은 동일한 가상 Profile/Environment와 초기
   fixture Memory를 사용한다. 운영 사용자의 Memory 전체를 복제하는 평가기는 아니다.
4. **제안**: 검증 점수가 엄격히 개선되고 개별 지표가 악화되지 않으며 양쪽의 기계적 안전
   검사를 통과해야 `proposed`가 된다. 나머지는 rejected/no_change/insufficient_feedback다.
   변경한 모든 필드는 분리한 검증 피드백에 명시돼 있어야 하며, 검증하지 못한 변경은 거절한다.
5. **승인**: 별도 승인 요청만 Semantic preference를 갱신한다. 진행 중 세션은 원래 Persona를
   유지하며 새 세션부터 바뀐다. Episodic Memory를 ground truth로 자동 승격하지 않는다.
6. **롤백**: 과거 버전을 덮어쓰지 않고, 이전 선호를 복구하는 새 버전을 추가한다.

`format`은 bullets/table/explanation, `focus`는 delivery/risk/onboarding만 허용한다.
승인한 `focus`는 과거 Memory의 검색 초점보다 우선하고, Research Context에
`source=approved_persona`와 버전을 전달한다. 도구 자체와 project 인자의 허용 범위는 바꾸지 않는다.

## 평가와 해석

`MockReplay`는 설정된 실제 Backend/키를 사용하지 않는다. 별도 로컬 Mock endpoint와 임시
DB만 만들고 최대 24회 로컬 모델 요청으로 전후 비교를 수행한다. 외부 API 요청은 0회다.
평가 중 새 사용자 메시지가 들어오면 단일 worker의 직렬 실행 때문에 기다릴 수 있다.
논문처럼 비동기 백그라운드 최적화를 구현하지 않았다.

평가 지표는 원하는 형식으로 렌더링됐는지, 실제 Research/RAG 호출 tag가 원하는 초점인지다.
원응답·표시 답변·형식 fallback 여부를 별도로 기록한다. 형식 점수는 **표시 결과**의 지표이며
모델 원응답이 그 형식을 따랐다는 지표가 아니다. 안전 검사는 workflow 완료, 도구 오류와
Profile/Environment 사실 출처를 확인하며 임의 문장의 의미 정확성을 증명하지 않는다.

Mock은 Persona/Context의 선호를 따르는 결정적 응답기다. 따라서 이 비교는 버전·전달 경로·
도구 인자·표시 형식의 작동 검증이며 실제 GPT-4o mini의 개인화 효과나 통계적 일반화 성능을
검증한 결과가 아니다. 마지막 1건의 작은 검증 집합도 일반화 보증이 될 수 없다.

## 사용 방법

기존 Backend/UI 실행 명령을 그대로 사용한다. 이번 개발 검증에서는 `--mode mock`을 사용한다.
각 답변의 피드백에서 **이 선호를 Persona 후보 검증에 사용하는 데 동의합니다**를 선택하고
형식/검색 초점을 지정한다. 서로 다른 턴 최소 4개에서 저장한 후 사이드바의
**피드백 기반 Persona 개선 → Mock으로 후보 검증**을 누른다.

개선된 후보는 지표·도구 인자·전후 답변과 함께 표시된다. 별도 승인 체크박스와
**후보 승인·적용**을 눌러야 반영된다. **새 대화**를 시작해 새 버전을 사용한다.
필요하면 이전 버전을 선택하고 롤백을 승인한다. 동의 없이 저장한 기존 피드백은 자동
전환하지 않는다. 같은 턴에 여러 번 저장해도 반복 선호 횟수는 늘지 않는다.
동의를 해제해 다시 저장하면 해당 턴의 Alignment 참여를 철회하고 미적용 제안을 무효화한다.

API는 기존 세션 Bearer credential로 같은 사용자에 대해서만 접근한다.

| 경로 | 동작 |
|---|---|
| POST `/sessions/{id}/feedback` | 기존 필드 + `consent_for_alignment`, `preference: {format, focus}` |
| GET `/sessions/{id}/alignment` | 활성 버전, 버전 이력, 최근 후보·평가 |
| POST `/sessions/{id}/alignment/proposals` | 명시적인 로컬 Mock 후보 평가 |
| POST `/sessions/{id}/alignment/{proposal}/approve` | 본문 `{"confirm": true}`로 승인 |
| POST `/sessions/{id}/alignment/rollback/{revision}` | 본문 `{"confirm": true}`로 롤백 |

자유 의견 분석은 오인식을 줄이기 위해 전체 문장이 일치하는 6개 문구만 지원한다.
예: `응답은 표로 보여주세요`, `위험 중심으로 검색해주세요`. 그 밖의 의견은 검토용으로
저장만 한다. 권장 입력은 UI의 구조화된 선호 선택이다.

## 사용자·권한·버전 보호

- feedback/proposal/version/active는 모두 owner로 조회·수정한다. 다른 사용자의 턴·후보는 거절한다.
- `persona:read/propose/approve/rollback` 권한을 별도로 검사한다. Semantic 변경에는 memory 권한도
  필요하다. 개발용 세션 Principal에만 이 권한을 부여하며 피드백이 권한을 생성하지 않는다.
- 프로젝트명·stage·문서·규정·system prompt·언어·scopes는 학습 필드가 아니다. API extra 필드는
  거절하고 자유 의견에 든 사실이나 지시문으로 Persona를 재작성하지 않는다.
- 제안 후 기준 Persona나 피드백이 바뀌면 적용을 거절한다. 중복 승인과 검증 실패 후보도 거절한다.
- SQLite 트랜잭션으로 새 버전/active pointer/Semantic 갱신을 함께 저장한다. rollback도 이력을
  추가한다. 세션의 이미 생성된 Persona와 시스템 프롬프트는 변경하지 않는다.
- 사용자 선택은 여전히 개발용이며 운영 인증이 아니다. Public 포트 공개·적대적 다중 tenant
  환경은 지원하지 않는다. 피드백 원문 보존/삭제 정책과 운영 인증은 별도 구현이 필요하다.

## Mock 검증과 향후 실제 모델 검증

```bash
scripts/run_tests.sh -j 2 tests/persona_prototype/test_alignment.py -q
scripts/run_tests.sh -j 2 tests/persona_prototype/ -q
# 선택적인 브라우저 검사: Mock Backend 8002 / UI 8503 실행 후
python3 tests/browser/persona_alignment_smoke.py
```

최종 검증에서 개인화/웹 Mock 및 선택된 Hermes 회귀 테스트 **154개**, 저장소 필수 검사
**19개**가 통과했다. 전체 Hermes 테스트를 모두 실행한 것은 아니다. Chromium에서는 동의한
선호 저장, 후보 비교, 체크박스를 통한 승인, 새 대화의 risk 검색/doc-3 표시, 롤백을 확인했다.
브라우저 스크립트는 Alice가 기본 선호로 시작하거나 롤백된 별도 Mock 상태에서 사용한다.

Mock 테스트는 다음 가상 반복 피드백을 사용한다.

| 사용자 | 기존 형식 / Memory 초점 | 후보 형식 / 승인할 초점 |
|---|---|---|
| Alice | bullets / delivery | table / risk |
| Bob | table / risk | explanation / onboarding |
| Carol | explanation / onboarding | bullets / delivery |

세 경우 모두 held-out 표시 형식·실제 검색 tag 점수 0→1을 확인하며 프로젝트 ID·Environment
stage는 동일하게 유지한다. 이 점수는 정의한 두 Mock 지표의 평균이다. 승인 전 미적용,
승인 후 새 세션 적용, 기존 세션 유지, 재시작 후 버전 보존, 롤백, 검증 선호 불일치 후보 거절,
중복 피드백, 동의 없음/철회, 다른 사용자 접근 및 승인 권한 거절을 시험한다.

실제 모델 검증은 **미구현·미실행**이다. 향후 별도 승인 후 공용 비용 원장에 연결하는 평가기를
구현하고 같은 Profile/Environment/Memory/질문을 고정해 전후를 비교해야 한다. 형식·도구 tag뿐
아니라 원응답 사실성, 출처와 무관한 주장의 오류, 비용을 별도로 평가해야 한다. 한 사용자부터
총 12회 이하의 쌍 비교 계획을 잡고 호출 전 필요한 예산을 예약한다. 세 역할 전체를 전후로
재생하면 16회 이상이므로 현재 12회 상한에서는 수행할 수 없다. 상한을 자동 변경하거나
원장을 지워서는 안 된다. 논문의 LLM 피드백·후보 생성 호출도 같은 비용 계획에 포함해야 한다.
