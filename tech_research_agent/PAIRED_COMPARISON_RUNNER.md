# 서로 다른 Persona의 승인 경로 Stub 통제 비교

기준 `63ec0ca6aa`. ResearchApplication의 approved_public → Hermes 3역할 →
ComparisonPublicAdapter 경로를 두 번 실행하는 비교 실행기를 추가했다. 단순 Adapter
테스트와 달리 서로 다른 승인 표현을 사용한다. 이번 전송은 **Stub 전용**이며 실제 API
실행 기능을 활성화하지 않는다. 운영 원장·비용 설정·Persona 버전·승인은 변경하지 않는다.

## 기본 비활성과 재사용

`PairedPublicComparison(factory).run(actor, question)`는 기본 enabled=False이며
factory도 실행하지 않는다. enabled=True는 Stub rehearsal 허용이다. live=true,
실제 네트워크 모델·정보원은 거부한다. 기존 WorkflowStub 계열과 OpenAlexConnector의
httpx.MockTransport만 받는다. 다른 Connector와 기존 일반 UI는 변경하지 않았다.

factory(root)는 이미 준비된 v1/v2 ResearchApplication과 승인 Registry를 제공한다.
실행기는 승인 grant나 Persona를 만들지 않는다. 두 store는 달라야 하며, 조사 상태와
공통 Stub 원장 모두 실행기가 생성한 임시 root 아래에 있어야 한다. 운영 경로는 거부한다.
임시 원장은 합성 테스트용이며 운영 예산을 복사·초기화하는 수단이 아니다.

기존 ComparisonPlan/예산/전송 직전 승인 정책을 재사용한다. Agent Loop나 새
Orchestrator LLM은 없다. TechnicalMockReplay는 기존 Offline Alignment 검증에 유지하며,
새 실행기는 그 Mock responder로 우회하지 않고 공개자료 승인 Gateway를 직접 실행한다.

## 통제와 Wire 차이

시작 전 Profile/Environment/질문, 사용자·프로젝트의 전체 초기 episode, Legacy semantic,
서버 권한·ACL·cutoff, 역할별 Tool Schema를 비교한다. 다르면 모델 실행 전에 차단한다.
v1 실행 후 v2의 초기 상태와 Persona가 같은지 재검사한다. 조건 실행 후에도 Persona
원본이 바뀌지 않았는지 확인한다. 원래 revision 2/3을 동일 숫자로 덮어쓰지 않는다.

포착 지점은 RealAdapter의 policy.before_send 이후, Stub 전송 직전의 완성된 JSON body다.
HTTP 인증 헤더나 실제 TLS 바이트를 수집한 것은 아니다. 전체 digest와 순서를 보존한
digest, 모든 system/user/assistant/tool 메시지, Context, Schema, 생성 옵션을 검사한다.

첫 Research 요청에서 허용하는 차이는 다음뿐이다.

- approved_preferences.research_persona.preferences와 이에 따른 persona_guidance의
  preferences/overrides/source_focus/field_sources.
- 실제 persona_revision과 research_persona.version. 버전은 제거하지 않고 메타데이터
  교란 요인으로 기록하며 기존 승인 binding을 수정하지 않는다.

다른 system 지침, user 메시지, Profile/Environment/History, Schema·모델·옵션 차이는
통제 실패다. Context 필드 순서와 고정 dict 순서도 확인한다. PRIVATE 원본만 다르고
공개 표현은 같아도 거부한다. v2 첫 요청이 실패하면 그 Stub 전송은 호출하지 않는다.
그 시점의 예약/실패 기록은 기존 예산 정책에 따라 보존한다.

후속 요청은 `(role, role 내 순번)`으로 짝짓는다. evidence, previous_stages,
verification_audit, retrieval_limits, assistant/tool 메시지·배열 길이는 downstream_results로
구분한다. 다른 고정 입력의 차이는 계속 unexpected다. 한쪽 추가 요청은 unmatched로
기록하며 개수를 억지로 맞추지 않는다.

## 개인정보와 결과 기록

raw payload, PRIVATE 원본, Memory·자유 의견은 일반 보고서에 쓰지 않는다. 단계별 응답·
최종 보고서, RP/OP 값, 검색/Read 결과·인용 원문은 해시로 내보낸다. 검증된 PUBLIC
문서·인용 ID, 허용 APP/API 이름, 실제 버전, 완료 여부·호출 수는 별도 기록한다.
알 수 없는 필드 이름도 해시로 바꾼다. 실행기 내부 비교 값은 RAM에서만 사용하고 종료 때
폐기한다. 주입된 Stub 자체의 테스트 감사 메모리는 해당 Stub이 관리한다.
해시는 검증용이며 개인정보 익명화를 보장하지 않는다.

paired_records.write_report는 신규 파일에만 기록한다. usage.json 및 기존 파일/심볼릭
링크를 덮어쓰지 않는다. 실행기에서 만든 redacted report를 사용해야 하며 임의 Python
dict의 개인정보를 자동 판별하는 DLP는 아니다. Stub actual_api_usage는 항상 0이다.
stub_protocol_this_condition/campaign_cumulative는 조건별·누적 가짜 공급자 사용량이다.
이 토큰·예약액은 실제 청구액이 아니다.
성능은 not_evaluated, actual_execution_go는 false다.

## 재현과 합성 승인

가짜 승인은 테스트 전용 tests/tech_research_agent/paired_fixtures.py에만 있다.
approved_by는 운영 승인이 아님을 명시한다. 애플리케이션은 이 모듈을 import하지 않는다.
공개자료 모양의 합성 기록은 승인 정책을 Stub에서 검사하기 위한 것이며 실제 자료나
관리자 반출 승인으로 취급하지 않는다.

- v1: OpenAlex 선호, 실험 조건, 검색 결과 3개, 간략 기술 설명·bullets.
- v2: OpenAlex/KIPRIS 선호, 재무 위험, 결과 2개, 상세 기술 설명·table.
- 비공개 financial_detail·PRIVATE reason은 원본에만 남긴다.
- 두 초기 Memory/Legacy semantic/권한/질문은 동일하다.
- Stub은 두 조건 모두 OpenAlex를 고르지만 query/limit과 문서 W123/W456은 달라진다.
  APP 선택이나 LLM 성능이 개선됐다고 주장하지 않는다.

```bash
HERMES_TEST_FILE_RETRIES=0 scripts/run_tests.sh \
  tests/tech_research_agent/test_paired_comparison.py -q
```

```python
from tech_research_agent.paired_comparison import PairedPublicComparison
from tech_research_agent.paired_records import write_report

runner = PairedPublicComparison(server_supplied_stub_factory)
disabled = runner.run(actor, question)  # 비활성: factory도 실행하지 않음
report = runner.run(actor, question, enabled=True)  # Stub만 허용
write_report(report, new_output_path)
```

## 모델 식별자와 남은 NO-GO

approved_policy의 정확 일치 정책은 그대로다. alias gpt-4o-mini는 Stub에서 통과하지만
gpt-4o-mini-2024-07-18, 임의 suffix, 다른 모델은 차단한다. 실제 공급자 응답 식별자를
확인하지 않았으므로 날짜형 식별자를 자동 허용하지 않는다. 실제 확인 뒤 정확한 식별자와
승인 모델 정책의 관계를 검토해야 한다. startswith 허용은 하지 않는다.

완료 범위는 서로 다른 Persona의 Stub 통제 비교다. 실제 유료 전송은 이번 실행기에
지원하지 않는다. 향후 실제 실행 승인·지원 확장, 비용 ceiling 확정, canonical 원장과
고정 plan 검수, 문서·Catalog·Persona 최소 표현·Memory 재전송 승인, 네트워크·정확한
응답 모델·생성 기본값 확인이 필요하다. 실제 모델 품질·확률적 호출 수는 미검증이다.
운영 비용·live 설정·원장·일반 UI 한도·Hermes 코어는 변경하지 않았다.

## 확인 결과

2026-11-18: 공식 runner로 기술조사·기존 Persona 전체와 Hermes MemoryProvider/위임
범위 회귀 **33개 파일, 599 passed, 0 failed**를 확인했다. 조건별/누적 Stub 사용량
기록을 분리한 뒤 관련 2개 파일도 **35 passed**로 재확인했다. 정적 검사 19개가 통과했다.

서로 다른 가상 승인 Persona revision 2/3은 각각 R3/A1/V2, 6회로 완료됐다.
첫 요청의 차이는 공개 선호와 버전 메타데이터 4개 component뿐이었다. 후속 차이는
downstream으로 설명됐고 unexpected/unmatched는 없었다. 원본 Persona는 유지됐다.
actual_api_usage는 모두 0이며 운영 usage.json의 전후 SHA-256이 일치했다.
