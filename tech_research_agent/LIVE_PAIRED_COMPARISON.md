# 실제 GPT-4o mini 비교 경로 — 기본 비활성

기준 `1f9cf038b1`. 기존 PairedPublicComparison의 Stub 동작을 유지하면서 실제 네트워크
분기를 추가했다. 이번 개발에서는 실제 OpenAI·외부 정보원 호출 **0회**, 운영 usage.json,
비용 ceiling, 실제 실행 승인 설정 변경 **0건**이다. 기존 Hermes 3역할과 예산을 재사용한다.
이 문서는 실행 승인이나 관리자 grant를 생성하는 파일이 아니다.

## 두 실행 모드

- 기본 run(): disabled, factory도 실행하지 않는다.
- enabled=True, execution_mode='stub': 기존 임시 원장·WorkflowStub·MockTransport 경로.
- enabled=True, execution_mode='live', live_enabled=True: 유효한 LiveExecutionApproval이
  있어야 시작한다. actor/질문/프로젝트/환경·endpoint/model을 확인한 뒤에만 factory를 부른다.

Live factory는 임시 root 안에 이미 준비된 **서로 다른 조사 store**를 제공한다. 승인된
Persona 버전과 초기 Memory를 정확히 보존한 준비본이어야 한다. 실행기는 원본 운영
Persona나 승인 정보를 만들거나 변경하지 않는다. 운영 시스템으로부터 준비본을 만드는
작업은 관리자 책임이며 해당 버전·Memory의 유효성/반출 승인을 별도로 확인해야 한다.

Live의 두 ComparisonPublicAdapter는 기존 canonical usage.json과 하나의 고정
ComparisonPlan을 공유해야 한다. 새 원장·자동 재캡처·예산 초기화는 허용하지 않는다.
두 store는 독립적이며 초기 Profile/Environment/Memory/Legacy/Schema/권한 해시가 같아야
한다. v1의 결과는 v2에 복사하지 않는다. 각 Persona의 원래 버전과 원본 해시는 유지한다.

## 필요한 서버 승인 레코드

LiveExecutionApproval.load(server_path)는 **서버가 미리 검수한 JSON을 읽기만** 한다.
이 레코드는 source ApprovalRegistry와 별개인 실제 실행 승인이다. 공개자료·Persona·Memory
승인을 대신하지 않는다. 서버 파일 접근 통제는 필수이며 서명/SSO 결재 시스템은 구현하지 않았다.
일반 UI/모델/피드백에서 이 레코드를 생성하거나 바꾸는 인터페이스는 없다.

| 필드 | 필요한 검수 내용 |
|---|---|
| approval_id, approved_by | 관리자 실제 실행 승인 식별·주체 |
| approved_at, expires_at | timezone 포함, 현재 유효 기간 |
| actual_execution_approved | 명시적 true; 기본 설정에서 자동 부여하지 않음 |
| user_id, project_id, question_sha256 | 정확한 고정 사용자·프로젝트·질문 |
| model, endpoint | gpt-4o-mini / https://api.openai.com/v1 |
| comparison_plan | 기존 ledger_path, campaign_id, baseline_count, baseline_sha256 네 필드 |
| initial_inputs_sha256 | input_snapshot의 고정 Context/Memory/Schema/권한 전체 해시 |
| personas_sha256 | v1/v2 승인 Persona 전체 레코드의 각각 정확한 해시 |
| max_new_calls | 기존 비교 정책과 같은 12, 추가 증액 아님 |
| max_reserved_usd | 관리자가 승인한 신규 캠페인 비용 ceiling; 어댑터 설정도 양수이며 이 값 이하 |
| wire_options_sha256 | research/analysis/verification 각각 최종 JSON options 전체의 정확한 해시 |
| response_model_ids | 실제 확인·검수한 유한한 정확 식별자 목록 |
| response_model_evidence_sha256 | 그 확인 근거의 해시; 코드가 근거의 진위를 자동 입증하지 않음 |

wire options는 messages/tools를 제외한 최종 body다. Stub 포착으로 model/max_tokens/
stream 및 temperature/top_p/seed의 존재·부재를 먼저 검수한다. 옵션은 매 전송마다
승인 해시와 비교하며 값이 다르면 전송하지 않는다. 한 번의 승인으로 새 Persona나 초기
Memory를 임의로 바꿀 수 없다. 생성 설정을 같게 해도 모델 확률성까지 제거하지는 못한다.

승인 취소는 같은 프로세스에서 approval.revoke()로 즉시 반영된다. 시간·설정·승인은
조건 시작 전과 각 전송 직전에 재검사한다. 서버 파일 변경은 명시적 재로드/프로세스별
반영이 필요하다. 자동 파일 감시나 여러 worker의 취소 전파는 구현하지 않았다.

## 실제 전송과 관찰 훅

Live 어댑터의 transport는 None으로 유지한다. 기존 _network_send가 환경변수의 키를
읽고 기존 네트워크 정책과 HTTPS endpoint를 사용한다. 관찰을 위해 transport를 임시
callable로 바꿔 live 실행 승인 검사를 건너뛰지 않는다.

RealAdapter.request_observer는 기존 정책의 before_send 다음에 최종 JSON 복사본을
받는다. 원본을 변경할 수 없고, 관찰 후에도 반출 정책을 재검사한다. 관리자 실행 승인과
옵션 해시도 재검사한다. 인증 헤더/키는 관찰하거나 보고서에 저장하지 않는다.

pending attempt·역할·비용 예약을 먼저 영구 기록하고, 실제 전송 메서드 호출 직전에
transport_invoked를 기록한다. 따라서 예약됐지만 정책/통제 검사로 중단된 요청과 전송
메서드가 호출된 요청을 구분한다. 전송 호출 횟수가 성공 응답이나 실제 청구 횟수와 같다는
뜻은 아니다. root failed/pending과 기존 기록은 보존하며 자동 외부 재시도는 0회다.

## 응답 모델 식별자

기본 정책은 기존처럼 응답 gpt-4o-mini만 정확히 허용한다. 날짜형 응답은 자동 탐색하거나
startswith로 허용하지 않는다. 별도 ResponseModels에 정확한 alias/날짜 ID, 검수자,
근거 해시를 지정하고 실제 실행 승인에도 같은 목록·근거를 묶어야 한다. 임의 suffix,
다른 모델, 잘못된 날짜, wildcard는 거부한다. 요청 모델은 항상 승인된 alias 그대로다.

허용 목록 안에 있어도 한 조건의 실행 중 응답 식별자가 바뀌면 즉시 중단한다.
두 조건의 관찰된 식별자가 다르면 model_identity_changed로 보고하며 성공한 통제 비교로
표시하지 않는다. alias와 날짜 ID를 근거 없이 같은 실제 snapshot으로 정규화하지 않는다.

테스트는 가짜 근거로 특정 날짜 ID의 명시 허용과 그 외 ID 거부를 검증했을 뿐,
실제 공급자가 그 식별자를 반환한다는 사실을 확인하지 않았다. 실제 확인 증거가 없다면
날짜 ID를 설정하면 안 된다. 이 확인은 실제 실험의 GO/NO-GO 조건으로 남는다.

## 기록과 개인정보

기존 redacted Wire 비교, 단계별 응답·RP/OP·검색/Read 결과 해시와 PUBLIC 문서/인용 ID를
유지한다. 실제 응답 model은 승인된 식별자만 감사 기록에 남긴다. 실제 모드에서는 조건별
reported token/추정 비용, 누적 사용량, 예약 시도 수와 upstream_dispatches를 구분한다.
응답 내용/모델이 차단돼도 이미 반환된 정상 usage는 보존한다. Live의 usage 누락·잘못된
형식은 즉시 중단하며 비용은 None/미확인으로 남겨 0원으로 간주하지 않는다. 단가는 기존 provisional
rate다. paid_calls 필드는 전송 메서드 호출 시도의 보수적 합계이며 청구 확정 수가 아니다.

Connector가 보고한 source_requests도 별도 기록하지만 전체 외부 정보원 실제 패킷 수를
관찰한 것은 아니다. 확인하지 못한 총 외부 source 호출 수는 None으로 남긴다.
Stub은 계속 실제 사용량·비용 0으로 기록한다. 민감 원문/PRIVATE Memory/키는 일반 보고서에 없다.

## 사용 형태 — 이번에는 실행하지 않음

```python
from tech_research_agent.live_execution import LiveExecutionApproval
from tech_research_agent.paired_comparison import PairedPublicComparison

approval = LiveExecutionApproval.load(protected_server_approval_path)
runner = PairedPublicComparison(server_prepared_live_factory, execution_approval=approval)
disabled = runner.run(actor, question, execution_mode='live')
# 별도 실제 실행 승인을 받은 이후에만:
# report = runner.run(actor, question, enabled=True, execution_mode='live', live_enabled=True)
```

Factory가 설정하는 어댑터도 enabled/exclusive/public_processing/live_execution_approved가
모두 명시적으로 true이고, 비용 설정·response_models가 승인과 일치해야 한다. 실행기는
이 설정을 대신 활성화하지 않는다. 일반 Streamlit UI나 기존 일반 Real 한도는 변경하지 않았다.

## 실제 실험 GO/NO-GO

현재 **NO-GO: 실행 기능은 구현됐지만 운영 활성화·실제 실행 승인은 하지 않았다.**
관리자는 다음을 완료해야 한다.

1. canonical 기존 원장의 failed/pending/잔여량을 확인하고 다른 Backend를 중지해 단독
   소유·잠금을 확보한다. 승인된 고정 plan을 재사용하고 기록을 삭제/복사하지 않는다.
2. 실제 승인 Persona 두 버전과 동일한 초기 Memory 준비본을 검수하고 정확한 입력 해시를
   승인에 묶는다. 실제 서비스 사용자 인증/프로젝트 ACL은 별도 운영 연동 검토가 필요하다.
3. 정보원 서비스 권한과 문서·Catalog·Persona 최소 공개 표현·각 Memory 재전송 승인을
   확인한다. 실제 요청/결과의 해시가 승인과 다르면 그대로 중단한다.
4. 신규 12회·조건당 6회·Research 3회·출력 512, 비용 ceiling과 생성 옵션을 명시 승인한다.
   보수적 신규 예약 여유 $0.1188864 계산은 기존 단가 기준이며 가격 확인/승인을 대신하지 않는다.
5. 환경변수/Secrets의 PERSONA_API_KEY, PERSONA_BASE_URL, PERSONA_MODEL과 실제 네트워크
   정책·모델 접근 권한, 정확한 응답 식별자 확인 증거를 검수한다. 키는 채팅/Git에 저장하지 않는다.
6. 별도 실제 유료 실행 승인을 부여하고 그 후에만 서버 설정과 명시적 호출을 활성화한다.

R3/A1/V2 두 조건은 정상 최소 12회이며 재검색 여유는 없다. 512토큰 중단, 실제 모델 선택,
새 문서·서비스 오류에 따라 완주하지 못할 수 있다. 이번 테스트는 실제 모델 성능 평가가 아니다.

## 개발 검증 결과

2026-11-18, 실제 네트워크 메서드를 Stub으로 대체하고 모든 원격 socket을 차단하여 검증했다.
Fake 공급자 usage와 Fake 승인만 사용했다. 두 조건 6회씩, 입력 격리·전송 직전 전체 body·
Tool Calling·조건별 사용량/비용·원장 prefix 보존을 확인했다.

- 공식 runner 전체 회귀: 34개 파일 **629 passed, 0 failed**, 파일 자동 재시도 0.
- 최종 모델 식별자 일관성 검사 후 관련 3개 파일 **108 passed**. 신규 Live 검증 32개 포함.
- 정적 검사 **19개 통과**.
- 중간 전체 실행에서 기존 Alice 테스트의 임시 log 폴더 삭제 경합 1건이 발생했다.
  해당 파일 분리 실행 13개 통과, 이후 위 전체 회귀도 통과했다. 관련 코드는 변경하지 않았다.
- 실제 OpenAI/외부 정보원 호출 0회. 운영 usage.json의 전후 SHA-256이 일치했다.

이 수치는 실제 공급자의 모델 식별자·연결 가능성·성능을 확인한 결과가 아니다.
