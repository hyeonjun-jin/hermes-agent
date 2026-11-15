# P1: Offline Adapter / Policy Validator

기준 e7793fc9. 5 APP / 11 API의 로컬 실행과 Replay만 추가한다.
Hermes 연결, 실제 LLM·외부 정보원 호출, 내부 자료 사용은 없다. 기존 원장·한도·코어는 수정하지 않는다.
P0 data/의 18 입력·Gold·Corpus·manifest는 수정하지 않았으며 validate_all()로 해시를 재검사한다.

## 실행과 경계

```bash
python -m tech_research_benchmark.demo
python -m tech_research_benchmark.offline
```

`OfflineAdapter(context, corpus, registry).replay(calls)`는 호출 배열의 실제 순서로 실행한다.
Adapter는 Gold 경로를 읽지 않으며, 선택된 APP/API를 다른 도구로 재라우팅하지 않는다.
실행 상태는 ok / empty / denied / unavailable / partial이다. schema 오류도 실행하지 않고
`denied / invalid_schema`로 구분한다. denied 응답에는 status/reason/cost만 들어간다.

ServerContext는 모델 입력이 아니다. 서버가 인증된 user_id, 현재 project_id, allowed_projects,
allowed_sources, classification, cutoff, 남은 budget, document_acl, entity_topics를 구성한다.
P0 Environment의 allowed_apps는 신뢰된 서버 정책에서 allowed_sources로 변환해야 하며
모델이 제출한 Environment·classification을 그대로 신뢰하면 안 된다. 외부/내부 권한의
실제 SSO 연결은 이번 범위가 아니다. Context는 실행기 인스턴스의 서버 내부 객체로 유지한다.

- 각 호출 전 schema, 현재 사용자·프로젝트·분류·정보원·기간·예산을 확인한다.
- read는 이 Context의 실제 검색 결과에 포함된 ID만 허용한다. 매번 ACL/revoked를 다시 확인한다.
- 금융 조회는 search ID 대신 서버의 합성 corp_code→topic allowlist를 확인한다.
- RESTRICTED는 allowed_sources에 외부 APP이 잘못 남아 있어도 외부 호출을 차단한다.
- authorize_llm은 비공개 자료의 외부 전송과 RESTRICTED 외부 추론을 거부하는 사전 정책 함수다.
  전송 클라이언트 자체는 없다. 향후 모든 전송 경로가 이 검사를 거치도록 연결해야 한다.
- 예산 확인·실행·비용 증가는 같은 Context의 RLock 안에서 처리한다. 여러 프로세스의 전역 예산은 아니다.
  budget은 서버가 예약한 남은 Tool Call 수이며 기존 실험/API 사용량 원장과 별개다.

권한 거부는 실행 전 비용 0이다. 허용된 검색·read·재무·페이지·중복·장애는 각각 mock_units=1.
환경 선조회 비용이 필요한 harness는 Context에 이미 사용한 비용을 반영해야 한다.
실제 서비스 요금이나 처리 속도를 추정하는 값이 아니다.

## Corpus 검색·OP 처리

검색은 소량 합성 Corpus의 단어와 공개 topic 색인(H/B)에 대한 lexical match다.
topic 색인은 기술 용어 사전이며 Gold의 APP/API 선택이나 정답 문서 목록을 읽지 않는다.
APP·날짜·유형·IR 종류·내부 evidence_kind와 ACL 필터를 적용한다. 공시는 D01만 대상으로
하며 미정 DA01/IA01/IFA01/ALT를 생성하거나 허용하지 않는다.

publication date 정렬과 안정적인 ID 순서를 사용한다. relevance/citations는 실제 학술
순위가 아니라 fixture 순서다. 의미 검색, 실제 citation ranking 성능을 주장하지 않는다.
페이지 토큰은 서버가 발행하며 사용자·프로젝트·APP/API·검색 인자에 묶인다. 페이지마다
현재 권한을 다시 적용하고 비용을 기록한다. 임의/불일치 토큰은 partial과 명시적 경고다.

지원 metadata가 없는 open_access/applicant/ipc/영문 필터는 무시하지 않고 partial/빈 items로
반환한다. 요청된 페이지/section/초록/청구항이 fixture에서 제공되지 않으면 partial이다.
DEV 재무 payload가 없는 경우에도 partial이며, 연도·CFS/OFS·계정에 맞는 rows만 반환한다.
실제 숫자나 과거 연도 재무 데이터를 새로 만들지 않는다.

## Trace와 Scorer

trace의 plan, executed, execution_args, reason, result를 분리한다.
result에는 source_id/title/출처/게시 시점/조회 시점/분류/locator/합성 span/상태/비용을 기록한다.
trace는 서버 내부 감사 기록이며 원래 입력에 포함된 민감 인자도 있을 수 있어 다른 사용자나
모델에게 그대로 전달하면 안 된다. denied 결과에는 새 비인가 metadata가 노출되지 않는다.

`adapter.scorer_inputs()`는 성공/부분 실행 호출과 실제 read 증거, 거부 감사, 장애·비용을 분리한다.
평가자 전용 `replay_score.score_replay(case, gold, payload, corpus, registry)`가 P0 scorer와
연결한다. Gold는 이 평가자에게만 전달한다. 거부 시도가 executed 목록에서 빠지더라도
policy_audit가 있으면 업무 성공=false, 구조 성공=false로 강제해 위반을 숨기지 않는다.
모델이 근거를 이해했거나 업무 품질을 만족했다는 판정은 계속 수동 검수 대상이다.

## DEV 실행 예시

실제 실행 JSON: [examples/p1_demo.json](examples/p1_demo.json).

| 계획 | 결과 | executed | 비용 | 사유 |
|---|---|---|---|---|
| internal_mock.search_documents, NCM/proj-B, financial | ok, DEV-B-N2F와 합성 span | true | 1 | 정상 |
| 같은 검색의 limit=99 | denied | false | 0 | invalid_schema |
| 검색 후 해당 문서 권한 취소 → read_document | denied | false | 0 | access_denied |
| RESTRICTED → openalex.search_works | denied | false | 0 | access_denied |

## 한계와 다음 검증

반출 탐지는 모든 외부 인자의 프로젝트 문자열, 서버 지정 private_terms, 알려진 비공개
span 직접 포함을 검사하는 기초 방어다. 패러프레이즈·분할·인코딩 반출을 완전히 검출하지
못한다. 실제 반출 승인/DLP·SSO·분산 예산·검색 저장소 ACL과 외부 LLM 전송 경로는 미연결이다.
P0의 기술 근거/대안은 여전히 전문가 승인 대기다. Corpus 골격을 실제 기술 사실로 해석하지 않는다.

## 검증 기록

P1 단독 테스트 26개 통과. 11 API 분기, 5 APP search→read, 재무 행 선택,
Schema/RP/OP 오류, 미래 요청, 사용자/프로젝트/ACL, 미검색 ID·권한 취소,
외부 LLM 전송 정책, 예산·중복 비용, 상태 구분, 페이지·Scorer 연결을 검사했다.
최종 통합 실행: **254 통과 / 0 실패** (187.6초, 3 workers, 자동 재시도 0).
기존 228개+P1 26개이며 Streamlit 4개 포함. 정적 검사 19개 통과.
마지막 코드 변경의 Ruff/health 2개 재검사도 통과했다. P0 manifest 검증도 18개 통과했다.
실제 모델/외부 정보원 요청은 0이며 테스트는 DEV Corpus와 로컬 Mock만 사용한다.
