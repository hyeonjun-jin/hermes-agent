# GPT-4o mini 실행 경로 (실제 API 미실행)

기준 7e24a3ad. Mock 기본값을 유지하고 Real gateway를 별도로 추가한다.
실제 모델·외부 정보원 API 호출은 이번 작업에서 0회다. Source API는 Real에서도 P1 Offline Adapter다.
벤치마크·채점 기능은 추가하지 않는다.

## 분리된 실행

ResearchApplication.ask(..., execution_mode='mock')은 기존 스크립트 응답을 사용한다.
execution_mode='real'은 명시적으로 구성한 RealAdapter가 필요하며, Mock search_plan/respond는
호출하지 않는다. 세 Hermes AIAgent는 같은 실행 구조를 사용하되 gpt-4o-mini를 대상으로 한다.
Research에 5 APP/11 API, Analysis에 도구 없음, Verification에 read/financial API를 제공한다.
실제 전송 전 PUBLIC 전용 역할 system prompt를 구성해 Hermes 호스트 경로/기본 시스템
메타데이터를 외부 프롬프트에서 제외한다. user/tool/assistant 메시지는 그대로 검증한다.

Stub 검증에서 **연구소 Profile인데도 Stub 모델이 opendart.read_financials를 선택**했고
Hermes와 P1이 해당 호출을 수행했다. 이는 Mock의 '연구소→논문/특허' 분기가 Real 경로에
적용되지 않는다는 연결 검사다. GPT-4o mini의 실제 선택·추론 품질을 검증한 결과는 아니다.

## 현재 PUBLIC 범위

- Profile/Environment는 config.py의 공개 합성 개발용 fixture만 사용한다. quick/PUBLIC만 허용.
- 현재 허용 질문은 정확히 `수소환원제철을 비교 조사해주세요.` 또는
  `NCM LFP 양극재를 비교 조사해주세요.`다. 임의 자유 텍스트를 공개 자료라고 추정하지 않는다.
- 내부 project_id는 보내지 않고 공개 topic H/B로 표현한다. P1 실행에는 서버 project_id를 유지한다.
- INTERNAL/RESTRICTED 환경은 시작 전에 중단한다. 내부 문서 ID/원문·호스트 경로·키 패턴,
  알려진 비공개 span, PRIVATE Memory를 포함한 payload는 전송 전에 차단한다.
- PUBLIC source_id의 classification/synthetic/original spans를 서버 Corpus와 대조한다.
  인용 원문을 변경하거나 다른 자료가 섞이면 중단한다. 구조화된 tool content JSON도 재귀 검사한다.
- 기존 DB Memory와 기존 승인 선호는 기본 비공개/미분류다. 자동 공개 전환하지 않는다.
  현재 공개 합성 질문으로 생성된 Real 이력과 PUBLIC_SYNTHETIC으로 명시 승인한 제한된
  source_focus만 허용한다. 자유 피드백·비공개 이력은 전송하지 않는다. 미분류 항목이 섞이면
  조용히 누락시키지 않고 작업을 차단한다. 과거 Mock 이력이 있으면 이 이유로 Real이 차단될 수 있다.
- Profile/Environment/Memory/명시 요청과 역할 결과가 포함된 실제 최종 messages와 tools 전체에
  반출 검사를 적용한다. 모델 응답도 다음 단계에 사용하기 전에 검사한다.

이는 고정된 합성 입력에 대한 제한적 반출 경계다. 실제 직원의 임의 Profile/자유 질의에 대한
완전한 DLP가 아니며, 비공개 문자열의 모든 패러프레이즈/인코딩 공격까지 검출한다고 주장하지 않는다.
실 데이터 전환에는 서버 데이터 분류·출처 계약·독립 DLP 검증이 필요하다.

## 기존 원장과 예약

기존 persona_prototype.web_backend.PersistentBudget를 상속하고 같은 usage.json 형식을 유지한다.
총 12회, specialist별 2회, main 2회, 출력 512 token, request 64KB 제한을 바꾸지 않는다.
같은 canonical usage.json의 과거 calls/failed를 읽고, 새 원장을 생성하거나 예산을 초기화하지 않는다.
잔여 8회 미만, failed, 미결 pending이면 실행하지 않는다. 역할 회계는 서버 역할 marker로 결정하며
모델의 사후 설명으로 바꾸지 않는다. 기존 기록은 보존하고 새 호출만 추가한다.

실제 전송 전에 pending attempt와 보수적인 비용 예약 상한을 원자 교체로 디스크에 기록한다.
실패/timeout도 예약을 환불하지 않고 failed로 중단한다. reported usage가 없으면 비용은 unknown이다.
사용량·가격은 기존 provisional rate를 사용한 추정이며 실제 청구액/최신 가격 보장은 아니다.
호출 수는 예약/시도 횟수와 실제 보고 usage를 구분해서 확인한다.

동일 원장에 대해 새 실행기끼리는 파일 잠금을 사용한다. **기존 Backend는 이 잠금을 사용하지
않으므로 반드시 중지하고 원장의 단독 소유를 서버 관리자가 명시해야 한다.** 동시 운영은
지원하지 않는다. UI에서 원장 경로를 바꾸거나 초기화하는 기능은 없다.

Research의 검색→read→최종 응답은 3회가 필요할 수 있지만 기존 specialist 한도는 2회다.
이 경우 세 번째 전송 전에 차단하고 조사 미완료/별도 예산 승인 필요를 보고한다. 실제 3역할
워크플로에 맞는 한도 증액은 **별도 명시적 승인** 없이는 하지 않는다. 예산이 남았다고 역할
한도를 우회하지 않는다. 이번 환경에서는 운영 usage.json이 발견되지 않아 실제 잔여 예산은
확인하지 못했고 운영 원장은 생성·변경하지 않았다.

## 서버 설정과 UI

기본은 Mock이며 Real 선택에는 비용 경고와 사용자 확인 checkbox가 있다. 서버 구성 없이는
Real 입력을 비활성화한다. 서버 전용 .streamlit/secrets.toml의 설정 형태는 다음과 같다.
이 예시는 실행 승인이 아니며 실제 값을 만들거나 원장을 복사해서 예산을 확보하면 안 된다.

```toml
[technical_research_real]
enabled = false
exclusive_ledger_owner = false
usage_path = "/absolute/path/to/EXISTING/usage.json"
```

서버가 별도 활성화한 뒤에만 UI Real 선택이 가능하다. API 키는 기존 PERSONA_API_KEY 서버
환경에서만 읽는다. 화면 입력/프롬프트/감사 기록에 넣지 않는다. 고정 OpenAI endpoint,
TLS 검증, redirect 금지, HTTP 재시도 없음이며 기존 network policy 확인도 유지한다.
이번에는 이 네트워크 전송 함수를 실행하지 않고 모든 Real 테스트에 Stub transport를 주입했다.

UI에는 적용 입력, 원본 모델 tool_calls, APP/API/RP/OP, 정책·실행 결과, 역할 원응답,
보고서, 호출 예약 수/usage/비용 추정이 표시된다. tool_call에는 공급된 입력 snapshot/hash를
연결한다. 이 정보는 **제공된 입력의 출처 기록이며 도구 선택의 인과 증거가 아니다**.
모델의 선택 이유·사후 설명도 같은 이유로 인과 입증으로 취급하지 않는다.

## 실제 API 없이 확인한 것 / 확인하지 못한 것

Stub으로 예산 선예약·재시작 보존·미결 원장 차단·역할 한도·실패 미환불, 전체 payload 반출
차단, 실제 Hermes의 원본 tool_calls 파싱·P1 실행, 역할별 도구 surface, Mock 회귀·UI 경고를 검사한다.
실제 GPT-4o mini의 개인화 선택, 의미 추론, 형식·근거 준수, latency와 실제 token/청구액은
확인하지 못했다. 실제 API 실험은 기존 원장/역할 한도 점검과 별도 예산 승인 후에만 진행해야 한다.

## 이번 구현 검증 기록

- 통합 회귀: **281 통과 / 0 실패** (104.1초, 파일 재시도 0).
- 마지막 입력 출처/예산 안내 변경 후 앱 검사: **27 통과 / 0 실패**.
- 필수 정적 검사 19개 통과, 최종 Ruff/health 2개 재검사 통과.
- 기존 Mock, 사용자/프로젝트 격리, 역할 도구 권한, Memory 우선순위, Streamlit Mock/Real
  표시와 Real 비활성 경계까지 회귀 검사했다. 모든 Real 전송은 Stub만 사용했다.
- 실제 모델/외부 정보원 API 호출 0. 운영 usage.json 생성/초기화/변경 0.
- 파일 잠금은 Linux/POSIX 개발 환경에서 검증했다. 기존 Backend와 동시 운영하지 않는다.
