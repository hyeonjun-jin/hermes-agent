# 두 Persona 비교 전용 신규 12회 호출 허용

2026-11-18 사용자 승인: 기존 사용 기록을 보존하고 두 Persona 비교에 신규 최대 12회를
허용하도록 코드와 사전 검사를 수정한다. **실제 API 실행은 별도 승인 전까지 금지**다.
이번 구현·검증에서 실제 OpenAI·외부 정보원 API 호출은 각각 0회다.

## 적용 범위

기존 RealAdapter / ApprovedPublicAdapter와 일반 웹 UI의 기본 예산은 그대로다.
새 ComparisonRealAdapter / ComparisonPublicAdapter를 서버에서 명시적으로 사용하는
비교 경로에만 아래 한도를 적용한다. Hermes 코어·Agent Loop는 수정하지 않는다.

| 항목 | 비교 전용 한도 |
|---|---|
| 신규 요청 | 두 조건 합계 최대 12회 |
| 조건 | v1 / v2 각각 최대 6회, 조건 재실행 금지 |
| Research | 조건당 최대 3회 |
| Analysis / Verification | 기존대로 각각 조건당 최대 2회 |
| main / 새 Orchestrator | 허용하지 않음 |
| 모델 / 출력 / 외부 재시도 | gpt-4o-mini / 응답당 512토큰 / 0회 |
| 실제 전송 | 별도 live_execution_approved 기본 false |
| 신규 예약 비용 ceiling | 기본 0, 별도 명시 설정 필요 |

정상 R3/A1/V2는 6회씩 총 12회, 재무 직접 R2/A1/V2는 5회씩 총 10회다.
Research를 3회 허용해도 조건당 6회이므로 Analysis가 늘어나면 다른 단계에 여유가 없다.
재검색을 위한 자동 예산 확대는 없다. 초과·첫 외부 오류 시 failed로 중단하고 다른 조건도
시작하지 않는다. 조건당 6회는 예약 상한이지 실제 소비를 6회로 채우라는 지시가 아니다.

## 기존 원장 보존과 재시작

ComparisonPlan은 같은 canonical usage.json의 기존 calls 길이와 전체 prefix 해시를
고정한다. 기존 11개 기록이 있다면 누적 최대 23개가 되며 기존 11개를 삭제하거나
새 원장으로 복사하지 않는다. 이번에는 운영 원장에 plan·호출·비용 필드도 쓰지 않았다.

서버 관리자는 계획을 **한 번만** 읽기 전용으로 준비해 서버 설정에 고정해야 한다.
campaign_id, baseline_count, baseline_sha256, ledger_path 네 필드를 함께 보관한다.
서버 시작 때마다 capture()를 호출하면 안 된다. 비교 기록이 이미 있는 원장은 capture가
거부하며, 재시작은 원래 계획을 다시 로드한다. 모델·일반 사용자·UI는 계획을 생성/교체하지 않는다.

```python
# 한 번만 준비하는 읽기 전용 작업. 승인 부여·원장 갱신·API 호출은 하지 않는다.
from dataclasses import asdict
from tech_research_agent.comparison_budget import ComparisonPlan

plan = ComparisonPlan.capture(existing_usage_path, "approved-persona-pair")
server_plan_fields = asdict(plan)  # 서버 전용 설정에 검수·고정할 값. 일반 UI에 노출하지 않는다.

# 이후 모든 시작/재시작에서는 고정된 네 필드를 로드한다.
plan = ComparisonPlan(**server_plan_fields)
```

사전 검사는 기존 calls<=4 조건 대신 prefix 보존, 같은 campaign에 속한 suffix,
failed/pending 부재, 아직 시작하지 않은 조건과 전체 신규 잔여량을 검사한다.
첫 조건 시작 전 두 조건의 6회씩을 확보하고, 두 번째는 그 조건의 6회를 확보한다.
이 조건 검사를 원장 잠금 안에서 다시 수행한다. 원장 단독 소유는 기존과 같이 필수다.
다른 Backend의 추가 기록·기존 기록 변경은 차단하며 자동으로 기준점을 옮기지 않는다.

매 외부 시도 전 actor/campaign/condition/role과 비용 예약을 pending 상태로 영구 기록한다.
따라서 재시작이나 새 Adapter 인스턴스가 예산을 되돌리지 못한다. 한 번 시도한 조건은
재실행하지 않는다. pending/failed의 수동 조정이나 새로운 캠페인은 후속 관리자 절차이며
이번 승인으로 자동 허용하지 않는다.

## 비용과 반출 승인

이전 원장에는 예약 필드가 없을 수 있다. 기존 항목을 수정하거나 과거 비용을 0원으로
간주하지 않는다. 비교 전용 클래스의 max_reserved_usd는 **새 캠페인 suffix의 예약 상한**이다.
기존 일반 approved_public의 누적 비용 정책은 바꾸지 않는다. summary에는 전체 원장 totals와
신규 비교 comparison_totals를 나눠 기록한다. 과거 비용·예약의 미확인은 별도로 남는다.

코드 준비 승인은 신규 비용 ceiling 설정이나 실제 결제를 자동 승인하지 않는다.
기본 비용 ceiling=0으로 실행 불가다. 각 전송의 신규 예약액과 캠페인 누적액을 검사하고,
사전 검사에서도 미시작 조건의 전체 비용 envelope를 확보해야 한다. 기존 단가·64KB
payload·512 출력 기준으로 두 조건을 시작할 보수적 신규 예약 여유는 $0.1188864다.
실제 가격·사용량과 예약액은 다르다. 실제 실행 승인 시 비용 ceiling을 별도로 확정한다.

ComparisonPublicAdapter는 기존 approved_public prepare/context/before_send 정책을 그대로
상속한다. 서버 opt-in, 문서·회사 Catalog·Memory 이력 승인, PRIVATE Persona 최소 공개
표현 승인, 최신 권한·해시·만료·취소 검사는 생략하지 않는다. 비교용 호출 승인은 반출
승인이 아니다. 실제 Connector와 기존 synthetic-only real의 동시 사용 차단도 유지된다.

## 실제 실행 승인 이후 사용할 서버 경로 — 이번에는 미실행

```python
from tech_research_agent.comparison_real import ComparisonPublicAdapter

adapter = ComparisonPublicAdapter(
    existing_usage_path,
    comparison_plan=plan,
    condition="v1",  # 다음 조건은 동일 plan/원장의 v2, 독립된 초기 Memory/Persona 상태 사용
    approvals=administrator_registry,
    enabled=False,  # 실제 실행 승인 후에만 서버 관리자가 활성화
    exclusive_ledger_owner=True,
    public_processing_enabled=False,
    max_reserved_usd=0,
    live_execution_approved=False,
)
# 별도 실행 승인·반출/비용 승인 전에는 app.ask(...approved_public)를 호출하지 않는다.
```

기존 UI에 유료 비교 시작 버튼이나 사용자가 예산을 바꾸는 기능은 추가하지 않았다.
활성화 전에 두 조건의 Profile/Environment/초기 Memory/질문/접근 권한/모델 설정을 고정하고
각각의 승인 Persona를 구성해야 한다. 기존 Offline 실행기는 계속 Mock 전용이다.
[통제 실험 계획](CONTROLLED_REAL_EXPERIMENT.md)의 자료 승인·교란 요인 검토도 계속 필요하다.

## Offline 검증 항목

실제 전송 함수는 차단하고 기존 WorkflowStub/공개자료 HTTP MockTransport로 검증한다.
이전 11개 항목 보존, R3 쌍 12회·R2 쌍 10회, 재시작/재실행/계획 재캡처 차단,
역할 한도·조건 한도·신규 13번째 요청 차단, pending 선기록과 첫 오류 중단,
비용 0/한 조건 비용만 있는 경우 사전 차단을 검사한다. 공개자료 두 조건에서도 PRIVATE
Persona 원본을 유지하고 승인된 최소 표현만 보내는지 확인한다.

이 결과는 새 호출 예산 경계의 기능 검증이며 실제 LLM의 개인화 개선 결과가 아니다.

최종 공식 runner 회귀: 32개 파일 **578 passed, 0 failed**, 파일 재시도 0.
신규 비교 예산 테스트는 14개, 공개자료 승인 테스트는 55개가 통과했다.
scripts/check --base 11233f78a8의 정적 검사 19개도 통과했다. 운영 원장의 전후
SHA-256은 동일하며 실제 호출은 하지 않았다.
