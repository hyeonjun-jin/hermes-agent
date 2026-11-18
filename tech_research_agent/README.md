> 현재 공개 정보원 연결: [OpenAlex Connector v1](OPENALEX_CONNECTOR.md), [OpenDART Connector v1](OPENDART_CONNECTOR.md), [KIPRIS Plus v1](KIPRIS_PLUS_CONNECTOR.md), [POSCO IR v1](POSCO_IR_CONNECTOR.md).
> 기본은 Offline SYNTHETIC이다. 서버 opt-in 시 지정한 Connector만 공개 조회로 전환되며
> 공개 Connector와 Real 모델의 동시 사용은 별도 반출 승인 전까지 차단된다.
> [승인 공개자료 처리 경로](APPROVED_PUBLIC_PROCESSING.md)는 별도 `approved_public` 모드다.
> 기본 비활성·비용 상한 0이며 문서/Memory별 서버 승인이 필요하다. 기존 `real` 차단은 유지한다.
> [기술조사 Persona Alignment](PERSONA_ALIGNMENT_INTEGRATION.md): 구조화 피드백 → 후보/Offline Replay → 명시 승인 → 프로젝트별 버전 적용·롤백. 실제 모델의 개선 효과는 미검증이다.
> [이력 검색·선호 우선순위·최소 공개 표현 승인](PREFERENCE_BOUNDARIES.md): PRIVATE 원본은 보존하며 approved_public의 관리자 승인으로 선정한 표현만 전달한다.
> [실제 LLM 통제 실험 준비](CONTROLLED_REAL_EXPERIMENT.md): 현재 NO-GO 조건, R3/R2 호출·비용 계획과 Offline 비교 실행 방법.
> [승인된 비교 전용 신규 12회 경로](PAIRED_CALL_ALLOWANCE.md): 기존 원장을 보존하며 Research 3회·조건당 6회, 실제 실행은 별도 승인 전까지 차단한다.
> [서로 다른 Persona의 Wire 통제 비교](PAIRED_COMPARISON_RUNNER.md): 기본 비활성 Stub 실행기, 입력 격리·전체 JSON body 차이·redacted 기록. 실제 유료 실행은 활성화하지 않는다.
> [실제 GPT-4o mini 비교 경로](LIVE_PAIRED_COMPARISON.md): 정확한 관리자 실행 승인·입력/옵션 해시·모델 응답 allowlist에 묶인 Live 분기. 기본 비활성이며 운영 설정은 변경하지 않는다.
> [맞춤 논문 추천 TOP 3](PAPER_RECOMMENDATIONS.md): SourceAdapter 조회 근거를 Profile·승인 Persona·Environment로 로컬 heuristic 정렬. 기본 Mock에서 같은 후보의 직무별 순위 차이를 재현한다.
> 아래 첫 버전 기록 이후 추가된 Real 실행·예산 정책은 기존 관련 문서를 함께 확인한다.

# 개인화 기술조사 Agent — 첫 작동 버전

현재 개발 목표는 포스코홀딩스 임직원을 위한 기술조사 애플리케이션이다.
벤치마크 구축·점수 계산·성능 평가 기능은 추가하지 않는다. 기존 P0/P1 파일과 데이터는
보존하고 P1의 OfflineAdapter / Policy Validator만 실행에 재사용한다. 통합 중 재무 조회가 IR의 IF01을 금융 F01로 잘못 포함하는 접미사 버그를 수정했다. 기준 코드에서 DART+IR 허용 시 재현했고 DEV 재무 원문 회귀로 검사한다. 평가 데이터·Gold·manifest는 바꾸지 않았다.

## 실행

저장소 루트에서 기존 Hermes 테스트/Streamlit 의존성이 준비된 Python을 사용한다.

```bash
python -m streamlit run tech_research_agent/ui.py
python -m tech_research_agent.demo
```

Streamlit 개발용 사용자 선택 → 프로젝트(H/B) → 환경(quick/deep/restricted)을 고른 뒤 질문한다.
화면에서 Persona·승인 선호, 현재 Environment, 대화, 선택 도구·인자·실행 상태,
Research/Analysis/Verification, 원문 span·출처, 보고서, 피드백을 확인할 수 있다.
기존 `persona_prototype.ui_output` 렌더러를 재사용한 별도 기술조사 진입점이며,
기존 `persona_prototype/ui.py` 챗봇과 동작은 그대로 둔다.
대화·선호는 `.technical-research-state/`의 사용자별 SQLite/홈에 저장한다. 이 경로는 Git에서 제외한다.
UI 대화 탭은 브라우저 세션 동안 유지되고, 서버의 조사 이력/승인 선호는 SQLite에 남는다.
재시작 후 모든 UI 탭을 자동 복원하는 기능은 아직 없다.

모델은 내부에서 만든 loopback HTTP Mock으로 고정된다. 실 API endpoint나 키를 입력하는
옵션은 없다. 모든 자료는 SYNTHETIC, 업무 Environment 기준일은 2026-10-01인 개발 시나리오다.
실제 현재 포스코 프로젝트/마감/권한이 아니다. 개발 UI의 사용자 선택은 SSO가 아니다.

## Hermes 연결

1. 서버 Profile·Environment를 선택하고 인증 주체의 Memory 소유자를 확인한다.
2. 기존 MemoryStore에서 현재 사용자/프로젝트 이력과 명시 승인 선호를 읽는다.
3. Research → Analysis → Verification을 순차 실행한다. 각 역할은 별도의 Hermes AIAgent와
   MemoryManager/MemoryProvider를 사용하며 내부 도구 호출 루프는 Hermes에 맡긴다.
   기존 native delegate_task 기반 챗봇은 수정하지 않았다.
4. Research에는 5 APP/11 API Schema가 제공된다. APP/API/파라미터는 모델 응답의 tool call로
   결정한다. 실행기가 직무를 보고 Gold 도구로 재라우팅하지 않는다.
5. 모든 도구 호출은 provider → P1 adapter.execute → Policy Validator를 거친다.
   Analysis는 도구가 없고, Verification은 read/financial API만 사용할 수 있다.
6. 원문 read 결과만 다음 역할의 근거 ledger로 전달한다. 검색 snippet만으로 완료하지 않는다.
   Verification은 원문을 재조회하고 Analysis 초안과 함께 제공된 인용/숫자 감사 결과를 검토한다.
7. 목적·기준일·마감·보고 대상과 세 역할 결과를 보고서로 묶는다. 인용/숫자 누락, 정책 거부,
   역할 오류, 원문 부재가 있으면 미완료로 표시한다. complete는 실행 완료이며 사실성 승인 점수가 아니다.

범용 내장 memory/terminal/web 도구는 모델 surface에서 제외한다. 역할별 tool schema는
각 역할 대화 동안 고정한다. `bind_profile_scope`로 사용자 홈·secret·terminal 정책을 함께
바인딩하고 종료 시 복원한다. 앱의 RLock으로 같은 앱 인스턴스 내 실행을 직렬화한다.
다중 worker 전역 동시성·예산·세션 격리는 구현하지 않았다.

## 개인화와 Memory 우선순위

Profile: 부서·직무·전문 분야·관심 기술·판단 기준. 역할은 권한 부여의 근거가 아니다.
현재 서버 fixture는 세 직무에 동일 프로젝트 권한을 부여한다. ACL·allowed_sources·보안은
별도 ServerContext에서 P1이 확인하며 Persona/Memory로 변경할 수 없다.

Environment: 프로젝트·목적·마감·보안·보고 대상·자료 기준일·정보원·조사 깊이.
quick는 최근 1년/3건, deep는 2022년 이후/5건 및 역할별 내부 근거,
restricted는 승인된 내부 문서만 조회한다. 다른 프로젝트의 기술 질문은 먼저 범위를 묻는다.

이전 조사 이력은 현재 사실의 근거가 아닌 참고 자료로 프롬프트에 넣는다. 다른 프로젝트 또는 현재 권한으로 읽을 수 없는 출처를 포함한 이력은 전달하지 않는다.
이전 질문/보고서나 자유 피드백으로 선호를 자동 활성화하지 않는다. UI의 명시 승인 버튼으로
source_focus만 갱신한다. 현재 명시 요청(첫 Mock은 '논문만', '재무 중심'을 지원)과
Environment/서버 정책이 그 선호보다 우선한다. 현재 요청의 모든 자연어 제약을 이해하는
구현은 아니며 Mock의 범위 밖 표현은 실제 모델 검증이 필요하다.
기존 피드백 Alignment 최적화기는 변경하지도 새 앱에서 자동 실행하지도 않는다.

## 세 사용자 작동 예시

동일 질문: `수소환원제철을 비교 조사해주세요.` / quick / 동일 서버 권한.

| 사용자 | Research가 선택한 검색/조회 | 주요 조건 | 원문 근거 |
|---|---|---|---|
| 연구소 박사 | OpenAlex search_works + KIPRIS search_patents | 2025-10-01~2026-09-30, limit=3, article/review, KR 특허 | H-A01, H-P01 |
| 전략실 임원 | OpenDART list_disclosures + POSCO IR search_materials | 같은 기간/3건, material 공시·strategy IR | H-D01, H-IS01 |
| 재무팀 | OpenDART read_financials + POSCO IR search_materials | 2025/11011/CFS, 투자현금흐름·영업이익, earnings IR | H-F01, H-IF01 |

검색 후 Research와 Verification에서 원문 read가 수행된다. 금융 API의 원본 rows는 바로 근거가 된다.
위 도구 선택과 조건은 **Mock 응답기가 생성**하고 Hermes가 실제 도구 루프로 실행한 것이다.
학습된 모델이 Profile과 Environment를 올바르게 추론했다는 증거가 아니며 성능 수치도 아니다.
Model prompt에는 직무·환경·승인 선호·이력과 도구 Schema가 들어간다. 실 모델에 연결해
그 선택이 재현되는지는 아직 검증하지 않았고 이번에는 연결 옵션도 제공하지 않는다.

## 검증과 남은 문제

Mock 기능/보안/Streamlit 회귀만 수행한다. Gold/Scorer는 Agent 실행 경로에서 읽거나
호출하지 않는다. P1이 내부적으로 공유하는 Schema 유틸리티 모듈에 기존 scorer 정의는
남아 있으나 해당 함수/Gold 파일은 실행 입력으로 사용되지 않는다.
기존 P0/P1 회귀를 실행하는 것은 새 벤치마크·점수 기능 추가가 아니다.

원문 재조회와 숫자 토큰 감사는 의미적 사실 검증을 보장하지 않는다. Mock Analysis는
조건부 비교/한계와 기존 합성 span을 사용하며 실제 과학·사업 분석 능력을 뜻하지 않는다.
SSO·실 문서 ACL·실 정보원 connector·실제 모델·분산 원장·권한 취소 시 저장 이력 삭제 정책,
장기 대화 압축과 사용자 선호 버전/롤백 UI는 후속 작업이다. 기존 API 사용량 원장과 상한은
바꾸지 않았다. 이번 앱은 작업당 별도 로컬 Mock 호출 12회/도구 12회로 제한한다.

## 선택적 Real 경로

[REAL_MODE.md](REAL_MODE.md)에 GPT-4o mini용 gateway, 전체 payload 반출 정책,
기존 원장·역할 한도, UI 설정과 Stub 검증 범위를 기록했다. 기본 Mock 동작은 유지한다.
이 문서의 앞선 '실 API 옵션 없음'은 첫 Mock 버전의 기록이며, 현재는 명시적인 서버 설정으로만
Real 경로를 활성화할 수 있다. 실제 모델/API 실험은 이번에도 수행하지 않았다.

## 실행 예산 안정화 후속 작업

[WORKFLOW_BUDGET_PLAN.md](WORKFLOW_BUDGET_PLAN.md)에 Stub 요청 수, 중단 표시,
공유 원장 잠금과 **미승인** 신규 예산안을 정리했다. 기존 Real 한도는 그대로다.
`python -m tech_research_agent.stub_workflow`는 네트워크가 금지된 별도 Stub 경로이며 유료 실행 옵션이 아니다.
