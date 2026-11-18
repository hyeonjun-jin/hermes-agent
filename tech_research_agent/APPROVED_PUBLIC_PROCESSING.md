# 승인 공개자료의 외부 모델 처리 경로

기준 `01c338ac`, 2026-11-17. 기본 비활성이다. 실제 반출 권한·서비스 약관 승인이나
유료 예산을 부여한 작업이 아니다. 유효한 승인 파일·서버 opt-in·비용 설정을 배포하지 않았다.

## 기존 차단과 새 경로

기존 `mock` / `real`은 유지한다. 기존 Real의 세 차단은 삭제하지 않았다.

1. application.ask는 공개 Connector와 기존 `real`의 동시 사용을 거부한다.
2. public_context는 기존 두 PUBLIC 합성 질문과 PUBLIC_SYNTHETIC Memory만 허용한다.
3. PayloadPolicy / inspect_labels는 실제 비합성 문서와 변조된 합성 span을 거부한다.

새 `approved_public` 모드는 ApprovedPublicAdapter와 ApprovedPayloadPolicy를 별도로 사용한다.
기존 RealAdapter의 모델·게이트웨이·원장 잠금·비용 예약·호출 제한을 재사용하고,
반출 검사 선택 지점과 전송 직전 재검사/응답 receipt 지점만 확장했다.
기존 경로에서 synthetic=false를 포괄적으로 허용하지 않는다.

현재 질문은 기존 두 개만 허용한다.

- `수소환원제철을 비교 조사해주세요.`
- `NCM LFP 양극재를 비교 조사해주세요.`

Profile과 Environment는 기존 서버의 합성 직무/프로젝트 fixture다. 실제 임직원 프로필,
실제 프로젝트 설명, 자유로운 사내 요청을 전송하는 경로로 확대하지 않았다.
INTERNAL/RESTRICTED, 프로젝트 식별자와 비공개 문자열 반출 차단은 유지한다.

## 문서별 승인 계약

서버 전용 ApprovalRegistry JSON 배열을 사용한다. 기본값은 빈 배열이며 UI·LLM에서
등록/승인하는 Tool은 없다. 관리자가 자료를 먼저 검수하고 다음을 기록해야 한다.

| 필드 | 조건 |
|---|---|
| approval_id | 중복 없는 서버 승인 식별자 |
| subject | document_subject(item), Memory 계약, 또는 company_catalog의 정확한 공개 행 |
| content_sha256 | subject의 정렬된 UTF-8 JSON SHA-256과 일치 |
| classification | PUBLIC |
| external_processing_approved / terms_approved | 둘 다 true. 공개성만으로 대신할 수 없음 |
| approved_by / approved_at / expires_at | 검수자, 시간대 포함 승인 시각/만료 시각 |
| verification_status | metadata_reviewed / text_reviewed / rows_reviewed / memory_reviewed |
| model / purpose | gpt-4o-mini / technical_research |
| users / projects | 현재 서버 사용자·프로젝트에 대한 명시적 허용 목록 |
| document_approvals | 연구 이력은 의존하는 문서 승인 ID 목록을 필수 지정 |

문서 subject에는 출처 URL·ID·출처 APP·PUBLIC 분류·실제 확보한 spans와 모든 검증 상태를
포함한 정규화 item 전체를 넣는다. 재조회 시 달라지는 retrieved_at만 문서 승인 해시에서
제외한다. 각 실제 item과 전체 Tool 결과 receipt에는 조회 시각까지 포함해 변조를 검사한다.
검색 메타데이터와 Read 결과가 다르면 **각 표현에 대한 별도 승인**이 필요하다.
검색 조건·페이지 범위·반환 필드가 달라져 해시가 바뀌면 새 승인이 필요할 수 있다.
검색 결과 중 하나라도 미승인이라면 그 자료만 몰래 빼고 보내지 않고 실행을 중단한다.

OpenDART의 서버 회사 Catalog도 실제 비합성 정보다. 모델에 넘길 각 공개 행에 대해
`{"kind":"company_catalog","item":행}`을 별도로 승인하고 현재 회사 접근 권한을 재검사한다.
회사 Catalog 검증과 외부 모델 처리 승인을 같은 것으로 취급하지 않는다.

content_sha256는 **전송할 정규화 자료의 해시**다. 논문 전문·원본 XML/ZIP 전체의 해시를
확보한 것으로 표현하지 않는다. IR의 원본 PDF SHA-256은 별도 original_sha256로 기록한다.
verification_status는 검수 범위를 나타내며 기술적 주장·이용권한의 법률적 타당성을 자동
증명하지 않는다. 관리자가 메타데이터/텍스트/재무 행의 적절한 검수 상태를 선택해야 한다.

일반 사용자가 파일을 수정할 수 없도록 서버 파일 권한을 설정해야 한다. v1은 서명 서비스나
승인 워크플로/결재 시스템을 구현하지 않는다. revoke(approval_id)는 현재 Registry에서 즉시
차단한다. 서버 파일 변경은 앱 리소스 재시작/재로드가 필요하며 여러 worker로 자동 전파하지 않는다.

## 전체 요청 검사

1. 서버 Connector 결과를 기존 P1에서 Schema·RP/OP·현재 접근 권한으로 검증한다.
2. SourceAdapter는 미분류/비공개 Connector 항목을 거부하고, 새 경로에서는 반환 item의
   정확한 승인 해시·모델·목적·유효기간·사용자/프로젝트를 확인한다.
3. 실제 관찰한 Tool 결과의 전체 receipt를 보관한다. 승인된 item 밖의 재무 행이나
   알 수 없는 응답 필드를 허용하지 않는다. 미승인 결과는 로컬 Trace에 정책 거부를 남기고
   모델에 전달하지 않는다. 이후 Tool 실행과 모델 요청도 중단한다.
4. 전송 payload의 messages·tools·Tool Call 인자·검색 결과·원문 span·이력·선호·이전 역할
   응답 전체에 분류/민감 문자열/크기 검사를 적용한다. 문자열 속 JSON도 검사한다.
5. system의 TECH_CONTEXT는 서버 스냅샷과 일치해야 한다. 사용자 메시지는 현재 허용 질문과
   서버 역할 접두사 하나만 허용한다. 추가 첨부·미관찰 assistant 이력·Tool 결과 변조·역할별
   Schema 변경을 거부한다. Tool 결과 ID도 실제 모델 응답에서 관찰한 ID여야 한다.
6. 모델 원응답도 검사한 뒤에만 Hermes에 반환하고 후속 이력으로 인정한다. 원본 tool_calls는
   기존 감사 기록에 남긴다. Hermes의 인자 JSON 키 정렬/공백 변경은 값으로 비교하되, 값 변조와
   중복 JSON 키는 거부한다. 원문 텍스트·인용·숫자는 이 과정에서 수정하지 않는다.
7. 예산 예약 직후 실제 transport 호출 직전에 승인을 다시 확인한다. 반환 뒤에도 현재
   문서/Memory 승인을 확인하므로 취소된 근거로 다음 단계를 진행하지 않는다.

PUBLIC 합성 fixture는 기존 PayloadPolicy의 ID/span 대조를 그대로 거친다. 실제 자료와
합성 자료의 출처 표시는 유지하며, 합성 fixture를 실제 공개 조사 결과로 바꾸지 않는다.

## Memory와 개인화

기존 MemoryStore·OwnerOnly·명시 승인 approve()와 PreferenceAlignment.propose 인터페이스는
유지한다. 이후 추가된 [기술조사 Alignment](PERSONA_ALIGNMENT_INTEGRATION.md)의 사용자
후보 승인은 외부 처리 승인이 아니다. [최소 공개 표현 승인 경계](PREFERENCE_BOUNDARIES.md)를
통해 PRIVATE Persona 원본을 보존하고 관리자가 검수한 허용 필드만 별도로 승인할 수 있다.

- 선호는 명시 승인 상태와 PUBLIC/PUBLIC_SYNTHETIC 정책이 있어야 하며, 그 정확한 semantic
  payload에 대한 별도 외부 처리 승인이 필요하다. UI의 합성 선호 확인은 반출 승인이 아니다.
- 이력은 사용자·프로젝트를 먼저 제한한 뒤 관련도 순위를 계산한다. 선택된 개별 episode마다 별도 PUBLIC 승인 sidecar가
  필요하다. subject는 kind(history/preference), 사용자, 프로젝트, 저장 레코드 전체를 묶는다.
- 이력은 문서 승인 의존성을 지정해야 한다. 의존 문서의 승인·접근 권한·알려진 버전도
  재검사한다. 다른 사용자의 Memory를 승인 파일만으로 읽을 수 없다.
- 전송마다 Memory 접근 권한과 실제 저장 내용이 승인 스냅샷과 같은지 확인한다.
- 기존 레코드를 PUBLIC으로 바꾸거나 `[PUBLIC_SYNTHETIC_RESEARCH]` 접두사만으로 새 경로의
  재전송을 허용하지 않는다. 공개 조사 보고서를 저장한 뒤 재사용하려면 다시 명시적 검수가 필요하다.
- 선호 순서는 서버 정책 → 현재 요청·Environment → 승인된 기술조사 Persona → 기존 선호
  → 과거 이력이다. PRIVATE Persona의 guidance는 승인된 공개 표현에서만 생성한다. 실제 모델이 이 우선순위를
  올바르게 판단하는지 검증한 것은 아니다.

Memory sidecar는 서버 검수자가 분류를 명시하는 수단이다. PRIVATE 선호를 자동 승격하지 않는다.
전체 보고서가 아닌 기존 검색 상위 이력/요약 길이를 사용하며, 승인되지 않은 선택 이력이
섞이면 조용히 삭제하고 실행하지 않고 차단한다. 보고서 보관·삭제·전사 ACL은 별도 운영 과제다.

## Research → Analysis → Verification

Research의 APP/API/RP/OP는 실제 모델 경로의 Tool Call에서 결정한다. 서버는 직무에 따라
정답 도구를 지정하지 않는다. 승인된 검색 정보로 문서를 고르고 승인된 Read 근거를 확보한다.
Analysis에는 기존 도구 없는 역할 권한을 유지하며, 논문·특허·공시·IR의 증거 유형과
기술 주장/검증 성능, 계획/실적, 회사/사업 범위, 발표일/회계기간을 구분하도록 지시한다.
Verification은 읽은 출처를 재조회하고 문서 ID·인용·숫자·시점을 대조한다.

외부 텍스트는 untrusted_external_data다. 문서에 명령이 있어도 서버 Context·승인·Tool 권한을
변경하는 코드는 없다. 모델이 지시문에 설득되지 않는다는 실험 결과가 아니며, 근거의 의미적
진실성이나 개인화 품질을 보장하지 않는다. 기계적인 인용/숫자 감사와 전문가 검수는 구분한다.

## 예산과 서버 설정

기존 usage.json과 동일한 canonical 파일·잠금을 사용한다. 기존 Backend와 동시 소유하지 못하며
재시작해도 calls/failed/pending을 유지한다. 원장을 없애거나 다른 경로로 새 예산을 만들지 않는다.

- 기존 전체 12회, 역할당 2회, 출력 512 token, payload 64,000 byte와 시작 시 8회 envelope 유지.
- R5/A2/V3·작업당 10회 제안은 유료 경로에 적용하지 않았다.
- 새 경로의 추가 max_reserved_usd 기본값은 **0**이다. 양수 상한을 별도 지정하기 전 시작 차단.
- 추가 상한은 기존 원장 전체의 예약액 + 다음 예약액에 적용한다. 미확인 과거 예약액도 차단하며
  초기화·환불·한도 확장을 하지 않는다. 병렬 요청은 비용 검사부터 예약/응답까지 직렬화한다.
- 요율은 기존 provisional 입력 0.15/출력 0.60 USD/백만 token이다. 최신 가격 확인이나 실제 청구액
  측정이 아니다. 비용 예약은 보수적인 byte 상한이며 허가된 결제 금액을 만들어 내는 기능이 아니다.

아래는 **비활성 상태의 설정 구조**다. 실제 사용 전에 관리자가 문서·이용조건·모델 처리와
허용 비용을 각각 승인해야 한다. 이번 작업에서 이 설정을 배포하지 않았다.

```toml
[technical_research_public_processing]
enabled = false
approval_registry_path = "/srv/reviewed-public/processing-grants.json"
max_reserved_usd = 0
```

별도로 기존 technical_research_real의 enabled, exclusive_ledger_owner, 기존 usage_path와
서버 API 키·네트워크 허용 정책이 필요하다. 각 정보원의 활성화·키/서비스 승인·Catalog도
별도 필요하다. UI는 승인 상태를 편집하지 못하며 사용 동의로 이 조건을 대신하지 못한다.

일반 검색 조사는 R3+A1+V2=6회이므로 현재 유료 역할 제한으로는 Research의 세 번째 요청에서
중단된다. 재무 원문 직접 조회처럼 R2+A1+V2로 가능한 흐름과 구분한다. 완주를 위해 원장을
초기화하거나 예산 제한을 바꾸지 않는다. Stub 전용 확장 예산은 테스트에서만 사용했다.

## 알려진 한계

원격 출처를 전송마다 자동 재수집하지 않는다. 새 Read에서 내용이 달라지면 해시 승인 불일치로
차단하고, 승인 철회·만료·권한 취소·IR Catalog 버전 변경도 재검사한다. 로컬 IR 파일은 전송
검사에서도 해시를 재확인한다. 그러나 원격 사이트의 변경/삭제를 조회 없이 즉시 알아내지는
못한다. 관리자 승인 만료·철회 및 재검수 절차가 필요하다. 이미 진행 중인 외부 전송은 되돌릴 수 없다.

분류와 권한의 신뢰 기반은 서버 Connector/Context와 관리자 승인 파일이다. 문자열 검사는
완전한 DLP가 아니며 오탐도 가능하다. 자유로운 직원/프로젝트 개인정보 반출, 전사 SSO,
문서 ACL, 여러 worker의 승인 전파, 암호화·서명·감사 저장소 접근 정책은 후속 작업이다.
IR의 OCR/표/차트, 논문 전문, 특허의 법률적 유효성, IR와 공시의 의미적 일치는 기존 미지원
범위를 유지한다. 현재 응답 모델 ID는 정확한 gpt-4o-mini만 허용하므로 실제 API의 snapshot 이름,
추가 응답 필드·Hermes 메시지 변형은 호환성 검수가 필요하다. 이름 접두사만으로 자동 허용하지 않는다.
[검증 기록](APPROVED_PUBLIC_VALIDATION.md)에 Stub 확인 범위를 별도로 적었다.
