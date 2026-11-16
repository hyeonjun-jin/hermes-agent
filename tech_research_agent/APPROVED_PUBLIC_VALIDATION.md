# 승인 공개자료 경로 검증 기록

2026-11-17, 기준 `01c338ac`. 실제 OpenAI 및 공개 정보원 API 호출은 **0회**다.
실제 포스코 내부 자료·실제 수집 IR/논문/특허/공시는 사용하지 않았다. 기존 운영 usage.json,
유료 한도·서버 secrets·Hermes 코어·벤치마크·Scorer는 변경하지 않았다.

## 네트워크 차단과 데이터

신규 테스트에서는 socket.connect의 비-loopback 연결과 실제 RealAdapter._network_send를
실패시키도록 했다. Hermes SDK는 로컬 gateway에만 연결하고 외부 응답은 in-process Stub이다.
OpenAlex/OpenDART는 httpx.MockTransport, IR은 직접 생성한 합성 텍스트 PDF를 사용한다.
기존 Connector 4종도 기존의 MockTransport/합성 fixture 회귀만 수행했다.

테스트 자료의 실제 Connector 출력은 계약 검증을 위해 synthetic=false 형태지만, 출처의
실자료를 수집했다는 뜻이 아니다. 제목·검수자에는 STUB/합성임을 표시했다.
테스트 승인 레코드는 테스트 임시 메모리/파일에서만 구성하며 운영 승인 파일을 만들지 않았다.

## Stub 통합 결과

| 경로 | Research | Analysis | Verification | 결과 |
|---|---:|---:|---:|---|
| OpenAlex 검색 → Read → 분석 → 재조회 | 3 | 1 | 2 | 6회 완료. 기존 Stub 전용 확장 예산에서만 실행 |
| 같은 검색 경로 + 현재 유료 역할 한도 | 2 | 0 | 0 | 세 번째 Research 요청 차단. 미완료 표시·별도 예산 승인 안내 |
| OpenDART 재무 원문 → 분석 → 재조회 | 2 | 1 | 2 | 5회 완료. 기존 역할당 2회 유지, 모델 transport는 Stub |
| 이력·선호 각각 승인 후 OpenAlex 흐름 | 3 | 1 | 2 | 세 역할에 같은 승인 Memory 전달. 자동 선호 갱신 없음 |
| Stub 비용 상한 0 | 0 | 0 | 0 | 첫 transport 전 차단 |

위 호출은 **Stub 모델 요청 수**이며 실제 유료 요청 수가 아니다. 테스트의 usage=10/5 등은
고정된 가상 값으로 실제 가격·토큰 실측 근거가 아니다. 원본 Tool Call·P1 Trace·반출 판단·
세 역할 원응답·최종 보고서·진행 상태를 확인했다. Gold/Scorer를 Agent 입력으로 사용하지 않았다.

## 차단 및 무결성 검사

| 조건 | 확인 내용 |
|---|---|
| 관리자 opt-in 없음, 승인 없음, 비용 설정 0 | 모델 transport·비용 예약 전 차단 |
| 잘못된 모델/목적·이용조건 미승인·해시 불일치 | 승인 Registry 거부 |
| 미승인 문서·PUBLIC/PRIVATE 혼합·미분류 | 전체 Tool 결과 차단. 일부만 남겨 전송하지 않음 |
| 문서/승인 철회, 만료, 사용자·프로젝트 불일치 | 다음 전송 전 현재 승인/접근 정책으로 차단 |
| 원문 span·게시일·조회 시각·URL 변조 | 문서 승인 + 실제 관찰 receipt 대조로 차단 |
| 문자열 TECH_CONTEXT 내부의 변조/비공개 근거 | 실제 JSON을 다시 검사해 시스템 프롬프트 속 자료도 차단 |
| Tool Call 인자·추가 사용자 메시지·미관찰 assistant 이력·Schema 변경 | 전체 payload 검사에서 차단 |
| 모호한 중복 JSON 인자 | 거부. JSON 키 순서/공백만 바뀐 경우 값의 동일성을 확인 |
| 승인 item 밖의 재무 행·알 수 없는 Tool 결과 필드 | 차단 |
| 실제 회사 Catalog 외부 처리 미승인 | PUBLIC 검증 Catalog여도 첫 전송 전에 차단 |
| PRIVATE 선호·승인 없는 과거 이력 | 차단, 기존 저장 레코드 분류/값 변경 없음 |
| 다른 사용자 Memory 접근·승인 후 내용 변경·접근 취소 | 기존 Authorizer 및 현재 저장 내용 재검사로 차단 |
| 승인된 보고서를 저장한 뒤 재실행 | 새 이력 승인 없으면 차단. 공개 조사 수행이 재전송 허가가 되지 않음 |
| Memory가 의존하는 원문 승인 철회 | 이력 재사용 차단 |
| IR 파일 바이트 변경·Catalog 새 버전·문서 철회 | 기존 outbound 근거 재사용 차단 |
| 비용 예약 직후 승인 철회 | transport 전 재검사 차단. 기존 실패 예약은 환불/초기화하지 않음 |
| 새 경로의 추가 비용 상한 | 기본 0. 누적 원장 재시작·동시 요청에도 초과 transport 차단 |
| 문서의 권한 변경 지시문을 따르는 Stub | 실제 Tool 정책이 internal_mock 호출 차단. 서버 권한 변화 없음 |
| 기존 real + 비합성 자료 | 기존 PayloadPolicy가 계속 거부 |

외부 지시문 검사는 Stub이 금지된 호출을 시도하는 상황에서 **서버 경계가 유지되는지**
확인했다. 실제 모델이 프롬프트 인젝션을 무시하거나 개인화를 잘 수행한다는 실험이 아니다.

## 실행 방법과 기록

기존 PM 테스트 환경의 pypdf/Streamlit을 재사용했다. 공식 runner를 사용했고 자동 재시도는 껐다.
환경 전용 interpreter wrapper는 테스트 scratch 경로를 쓰기 가능한 임시 디렉터리로 지정한다.

```bash
HERMES_PYTHON=/workspace/work/hermes-ir-test-python HERMES_TEST_FILE_RETRIES=0 \
scripts/run_tests.sh -j 4 \
  tests/tech_research_agent tests/persona_prototype tests/tech_research_benchmark \
  tests/agent/test_memory_provider.py tests/agent/test_memory_provider_caller_profile.py \
  tests/agent/test_memory_manager_fork_scope.py tests/tools/test_delegate_toolset_scope.py -q
python scripts/check --staged --base 01c338ac
```

중간 회귀 551개가 통과했고, 이후 시스템 컨텍스트 내부 검사·실제 회사 Catalog의 별도 승인과
OpenDART 통합 사례를 추가했다.

- **30개 파일, 553개 테스트 통과, 실패 0**, 311.9초, 자동 재시도 없음.
- 신규 승인 경로 **38개**, Agent UI **4개** 포함.
- 기존 OpenAlex **36개**, OpenDART **70개**, KIPRIS Plus **58개**, POSCO IR **57개** 통과.
- Persona·Memory·Multi-Agent·Alignment·기존 Real 및 예산·P0/P1 보존·Hermes MemoryProvider와
  사용자/도구 scope·기존 Persona Streamlit UI 회귀 통과.
- 정적 검사 **19개 통과**, code health 차단/권고 0.

초기 통합 검사에서는 Hermes가 Tool Call 인자 JSON을 정렬/재직렬화하는 차이를 발견했다.
원본 Tool Call 감사를 유지하고 JSON 값의 동일성을 대조하도록 수정했다. 응답 형식의 empty
content와 null 차이도 내용 없는 값으로 정규화한다. 원문 텍스트의 차이를 허용하지는 않는다.

## 실제 실행 전 필요한 것과 남은 한계

관리자의 문서별 이용조건/외부 처리 승인, 회사 Catalog/Memory 승인, 서버 opt-in과 별도 비용
상한, 기존 Real 원장 소유권·잔여 한도·미확인 예약 정산, 키·네트워크 정책이 필요하다.
일반 검색 완주는 기존 역할 제한으로 막히므로 별도 예산 승인 없이 R5/A2/V3으로 바꾸지 않는다.

원격 출처 변경은 새 Read 또는 관리자 철회/만료로 확인한 범위만 막는다. 실시간 변경 감시,
여러 worker의 승인·철회 전파와 이미 전송한 데이터의 회수는 구현하지 않았다.
Memory 검색은 기존 lexical/top-k 기반이고 장기 이력의 의미적 관련성·최신성은 보장하지 않는다.
수동 검수의 적절성, SSO/전사 ACL, 승인 파일의 서명·암호화·운영 감사 권한, 실제 문서의
추출 호환성 및 실제 API 응답 모델/snapshot 명칭·필드 호환성은 별도 검증이 필요하다.

현재 Profile/Environment는 개발용 합성 fixture다. 실제 임직원/프로젝트 정보를 PUBLIC으로
간주하지 않았다. 개인정보를 포함한 실제 개인화 입력을 연결하려면 별도의 분류·동의·반출 설계가
필요하다. 실제 모델의 개인화·인젝션 저항성·기술조사 품질은 아직 검증하지 않았다.
