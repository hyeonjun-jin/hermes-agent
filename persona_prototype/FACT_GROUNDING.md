# 프로젝트명·진행 단계의 출처 보장

## 원인과 변경

기존 Main 프롬프트는 단일 사실에 바로 답하도록 안내했다. 최신 단계 조회와 이미 아는
Profile 정보가 구분되지 않았고, prefetched Episode를 상태 근거로 사용하는 오류를
막는 필드 검증도 없었다. `hermes-agent`는 저장소 이름이지 Alice의 프로젝트 ID가 아니며,
`focus=delivery`는 사용자 선호이지 진행 단계가 아니다.

출처 계약을 세 가지로 나눴다.

| 필드 | 허용된 출처 | 예시 |
|---|---|---|
| 프로젝트 ID | 사용자 Profile | Alice: atlas |
| 관심 태그·응답 형식 | 확인된 Memory·Persona | delivery / bullets |
| 최신 진행 단계 | 현재 턴의 권한 있는 Environment 조회 | atlas: prototype |

`PROFILE_FACTS_JSON`과 고정된 출처 규칙을 시스템 Context에 전달한다. prefetched Memory는
선호 근거라고 명시하고, 이전 Environment 관측은 별도 historical 항목으로 전달한다.
세션 중 시스템 프롬프트·도구 스키마를 질문마다 바꾸지 않는다. Environment의 project
인자 스키마는 해당 Profile ID 하나만 허용하며 Backend 권한 검사도 유지한다.

## Main 실행 정책

- 인사: 기존 직접 답변 경로. 불필요한 조회·위임을 추가하지 않는다.
- 프로젝트 이름만 묻기: Profile 근거로 답하며 도구 선택을 `none`으로 제한한다.
- 현재 단계·진행 상태 묻기: Main의 첫 모델 요청에 `mock_environment` 선택을 요구한다.
  한 차례 조회 시도 후 도구를 닫는다. 단순 상태 조회에 Subagent는 실행하지 않는다.
- 명시적인 이전 조회 당시의 단계: 같은 사용자의 같은 세션에서 실제로 관측한 Snapshot만
  사용한다. 조회 권한을 다시 검사하고 `현재 상태 미확인`이라고 표시한다. 과거 답변이나
  Episode의 텍스트를 Snapshot 근거로 인정하지 않는다.
- 조사·분석·검증을 모두 요청하는 복합 질문: 기존 native Hermes 세 역할 흐름을 유지한다.

정책은 애플리케이션의 결정적 안전 규칙이다. Mock 또는 실제 모델의 자율적인 판단 능력을
입증하는 것이 아니다. `tool_choice`를 무시하는 모델, 잘못된 인자, 권한 거절, Backend 실패,
빈 stage 등의 경우에는 실제 조회가 성공했다고 주장하지 않는다.

## 출력 검증과 기록

좁은 프로젝트명·단계 질문에는 별도의 `fact_validation`을 적용한다. 최종 화면 답변은
검증된 필드에서 구성하고 `[profile:alice]`, `[environment:atlas]`처럼 출처를 표시한다.
Profile의 atlas는 알지만 조회에 실패했다면 단계는 **미확인**으로 표시한다. 문서 조회가
없는 상태 질문에 가짜 doc ID를 붙이지 않는다.

원래 모델 출력은 `raw_answer`에 보존하고 잘못된 프로젝트 값, Environment 근거 없는 단계,
선호를 단계로 제시하는 오류를 감사 항목으로 기록한다. 세션의 방금 생성된 최종 메시지는
검증된 표시 답변으로 저장하여 다음 턴에 같은 오류를 다시 주입하지 않는다. 과거 메시지는
수정하지 않는다. 기존 Memory sync의 모델 출력은 unconfirmed Episode로 남을 수 있으며,
이것을 최신 상태 근거나 확인된 선호로 승격하지 않는다.

이 검증은 기존의 손실 없는 bullets/table 형식 보정과 별개다. 사실 보장은 지정된 Profile/
Environment 필드에 대한 것으로, 임의 자연어 주장의 의미 정확성을 보증하는 일반 검증기는
아니다. 한국어·영어 패턴 기반 질문 분류와 오류 탐지에는 표현 범위의 한계가 있다.

## 오프라인 검증

`tests/persona_prototype/test_project_facts.py`는 같은 질문으로 다음을 확인한다.

| 사용자 | 프로젝트 | 조회 단계 | 실행 |
|---|---|---|---|
| Alice | atlas | prototype | Main의 mock_environment |
| Bob | beacon | review | Main의 mock_environment |
| Carol | cedar | learning | Main의 mock_environment |

추가로 모델의 hermes-agent/delivery 오답, 강제 도구 무시, 다른 프로젝트 접근, 조회 권한 없음,
Backend 장애, stage 누락, Memory의 가짜 프로젝트 값, 근거 없는 과거 답변, 단계 변경 후 최신
재조회와 과거 Snapshot 재사용을 시험한다. 같은 세션의 시스템 프롬프트·도구 목록이 유지되는지,
인사와 Profile 조회가 도구·Subagent 없이 처리되는지도 확인한다.

```bash
scripts/run_tests.sh -j 2 tests/persona_prototype/ -q
```

모든 검증은 로컬 Mock으로 수행하며 실제 OpenAI API는 호출하지 않는다. 기존 12회 호출 상한,
응답당 512토큰, 자동 외부 재시도 금지와 비용 원장은 변경하지 않는다.
이번 실행에서 개인화/웹 Mock 테스트와 선택된 Hermes 회귀 테스트 **146개**, 저장소 필수 검사
**19개**가 통과했다. 전체 Hermes 테스트를 실행했다는 의미는 아니다.

Codespaces에서 변경을 사용하려면 기존 브랜치를 pull하고 Backend를 재시작한다. 상태 디렉터리와
`usage.json`은 유지한다. 기존 대화의 오래된 오류가 남을 수 있으므로 수정 검증은 **새 대화**로
시작하는 것이 좋다. 실제 모델 재검증은 이번 작업 범위에 포함하지 않는다.
