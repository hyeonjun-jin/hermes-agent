# Alice Persona 통제 비교 실행기

이 문서는 사용자가 완료한 실제 실험과 이후 오프라인 수정·검증을 구분해 기록한다.
실제 실험은 이미 완료됐으며, 이번 수정 작업에서는 OpenAI API를 다시 호출하지 않는다.

## 완료된 실제 실험 — 사용자 제공 결과

아래 값은 사용자가 전달한 GPT-4o mini 실행 결과다. 이 체크아웃에는 실제 실행 JSON과
운영 `usage.json`이 없어 원본 응답이나 원장을 재검산하지 않았다. 원응답 문장을 재구성하거나
Mock 응답으로 실제 결과를 대신하지 않는다. 실행 일시와 조건별 토큰 사용량도 미제공이다.

| 항목 | Persona v1 | Persona v2 |
|---|---|---|
| 형식 / 검색 초점 | bullets / delivery | table / risk |
| 검색 문서 | doc-1, doc-2 | doc-3 |
| 모델 원응답 형식 준수 | 미준수 | 미준수 |
| 로컬 형식 보정 | 적용 | 적용 |
| Profile / Environment 근거 | 일치 | 일치 |

- 실제 API 호출: 두 조건 합계 **8회**.
- 입력 **35,484토큰**, 출력 **469토큰**. 조건별 사용량은 확인하지 않았다.
- 기존 잠정 단가로 계산한 예상 비용: **$0.005604**. 실제 청구액이나 캐시 할인은 검증하지 않았다.
- 검색 초점과 결과 문서가 달라진 것은 관찰했지만, 두 조건 모두 원응답 형식을 지키지 못했다.
  로컬 보정 결과를 모델의 형식 준수 성공으로 집계하면 안 된다.
- Profile/Environment 근거 일치는 보고된 관찰값이다. 모든 자연어 주장과 권고가 정확하다는
  의미는 아니다. 실제 원문을 확보하기 전에는 세부 해석 오류를 확정하지 않는다.
- 한 질문, 한 번의 v1→v2 비교이며 format/focus를 함께 바꿨다. 두 변수의 개별 효과,
  반복 재현성, 사용자 전반의 개인화 개선은 입증하지 못했다.
- 경로는 Main + native Research로 제한됐다. Analysis·Verification 회귀 테스트와
  이 실제 실험을 혼동하지 않는다. 도구 종류와 위임 경로도 통제돼 있어 자율 도구 선택의
  개선을 입증하는 실험은 아니다.


## 8회로 제한한 범위

기존 Main + Research + Analysis + Verification 전체를 전후 두 번 실행하면 최소 16회가
필요하다. 12회 상한을 유지하기 위해 아래 경로만 비교한다.

| 조건별 단계 | 모델 호출 | 수행 주체 |
|---|---:|---|
| 근거 수집 도구 호출 | 1 | Main |
| 검색 도구 호출 | 1 | Hermes native Research Subagent |
| 검색 결과 요약 | 1 | Research |
| Environment 조회 및 원문 대조 | 0 | 권한 있는 Backend와 결정적 코드 |
| 최종 답변 생성 | 1 | Main |
| 조건별 합계 / 두 조건 합계 | **4 / 8** | |

Analysis Agent와 Verification Agent는 이 축소 실험에서 실행하지 않는다. 문서 원문 대조와
Environment 조회가 수행돼도 두 Agent를 실행했다고 보고하지 않는다. Main의 첫 도구 선택은
공통 `comparison_research`로 고정하며 Research 검색 도구도 고정된 허용 범위 안에 있다.
**LLM의 자율 위임/도구 종류 선택 비교가 아니라 Research의 실제 검색 query/tag와 응답 차이의
통제 실험**이다. 검색 인자는 모델이 생성하며 format/focus만 실험 변수다.

## 입력 통제

- 사용자 Alice, 모델 gpt-4o-mini, Profile atlas, Environment atlas/prototype은 동일하다.
- 처음 한 번 seed한 fixture Memory SQLite를 두 조건에 복제한다. Episode ID·내용·생성 시각과
  Semantic Memory까지 같은 값으로 시작한다. 한 조건의 새 응답이나 회상 이력은 다른 조건으로
  전달되지 않는다. 초기 Episode에는 delivery 선호가 남아 있다.
- 질문은 두 조건에 동일한 상수를 사용한다:
  `현재 프로젝트 계획에 필요한 문서를 검색하고, 환경 정보에 맞춘 권고와 근거 문서 ID를 한국어로 알려주세요.`
- v1 조건은 bullets/delivery, v2 조건은 table/risk다. v1/v2는 보고서의 실험 라벨이다.
  **모델에 보이는 version 메타데이터는 양쪽 모두 1로 고정**하여 버전 번호를 추가 변수로
  만들지 않는다. 실제 저장된 승인 Persona v2나 버전 이력을 수정하는 것은 아니다.
- 모델 입력 Persona의 project/language/version, 시스템 지침, 도구 스키마와 호출 제약은 동일하다.
  바뀌는 필드는 format/focus뿐이다. Profile/Environment/Memory/질문의 SHA-256 fingerprint를
  두 조건에 기록하고, 일치하지 않으면 다음 조건 실행 전에 중단한다.
- 두 조건은 같은 실행 경로를 재사용한다. 전송 직전에도 역할·라운드별 시스템 메시지에서
  format/focus만 제외하고, 도구 스키마·tool choice·모델·샘플링 설정·출력 상한을 대조한다.
  일치하지 않으면 해당 요청을 OpenAI에 전달하지 않고 중단한다. 프롬프트를 고쳐서 맞추지는 않는다.
  날짜 변경 같은 실행 메타데이터 차이도 중단 사유가 될 수 있다.
- 실험용 임시 DB는 입력 격리용이다. 비용 예산을 새로 만드는 디렉터리가 아니다. 기존 실제
  사용자의 세션·Memory·활성 Persona·버전 이력은 실험에서 갱신하지 않는다.

## 기존 비용 원장 보존

실제 실행은 현재 `--mode real` Backend의 `PersistentBudget`와 기존 `usage.json`을 공유한다.
CLI는 ledger 경로·API 키·Persona 변경값을 받지 않는다. Backend의 세션 잠금 안에서 전체 쌍
실험을 직렬 실행하여 다른 채팅 요청이 중간에 예산을 소비하지 않게 한다.

- 실험 시작 전에 기존 12회 원장에 **8회 이상 남아 있어야** 한다. CLI와 Backend가 모두 검사한다.
- 원장이 중단 상태이거나 기존 사용량이 미확인인 경우에도 실행하지 않는다.
- 기존 사용이 4회면 8회를 추가해 12회가 된다. 기존 사용이 5회 이상이면 실행을 거절한다.
- 호출 전 디스크 예약, 재시작 후 원장 유지, 응답당 최대 512토큰, 자동 외부 재시도 0회를
  기존대로 유지한다. 각 조건의 Main/Research는 각각 최대 2회다.
- 첫 외부 API/전송 오류 또는 첫 조건의 실행 실패 후 다음 조건을 실행하지 않는다.
- 전송 직전 통제 검사에서 실패한 요청은 보수적으로 원장 예약을 유지한다. 실제 전송이 없더라도
  예약을 환불/삭제하지 않으며, 반환되지 않은 usage를 과금 0으로 추정하지 않는다.
  보고서는 `ledger_reservations`와 실제 전송을 시도한 `model_attempts`를 구분한다.
- 임의로 `usage.json`을 삭제하거나 다른 `--state`로 바꾸어 한도를 초기화하지 않는다.
  같은 상태 디렉터리를 사용하는 Backend를 여러 개 실행하지 않는다.
- 실험이 끝나도 보고서 저장 전 연결이 끊길 수 있다. 그런 경우에도 자동 재시도하지 말고
  기존 Backend 원장부터 확인한다. 과금된 호출이 보고서 부재로 취소되지는 않는다.

## 실행 방법

현재 브랜치를 pull하고 **기존 상태 경로를 유지한 채** Backend를 재시작해야 새 실험 경로가
등록된다. [Codespaces 실행 안내](CODESPACES.md)의 OpenAI endpoint/model/Secrets와 Private
포트 설정을 그대로 사용한다. 네트워크 정책 검사도 기존 Backend 경로를 사용한다.

먼저 무료 Mock 재생만 실행:

```bash
PERSONA_REPORT_DIR="${TMPDIR:-$(mktemp -d)}"
python -m persona_prototype.persona_comparison --mode mock \
  --output "$PERSONA_REPORT_DIR/persona-pair-mock.json"
```

`$TMPDIR`가 없는 Codespaces 터미널에서는 `mktemp -d`로 만든 임시 디렉터리를 출력 경로로
사용한다. 보고서를 Git에 추가하지 않는다.

향후 별도 승인을 받고 실제로 실행할 때, 활성화된 Hermes 환경의 Codespaces 터미널에서:

```bash
PERSONA_REPORT_DIR="${TMPDIR:-$(mktemp -d)}"
python -m persona_prototype.persona_comparison --mode real --execute \
  --api http://127.0.0.1:8001 \
  --output "$PERSONA_REPORT_DIR/persona-pair-real.json"
```

이 명령은 **기존 Backend 원장의 잔여 예산**을 소비한다. `--mode real`만 지정하고
`--execute`를 생략하면 Backend 요청도 하지 않는다. CLI는 Codespaces 안의 loopback
Backend에만 연결하며 출력에 세션 credential/API 키를 기록하지 않는다.

실제 API를 호출하지 않는 상태 확인:

```bash
curl --fail http://127.0.0.1:8001/health
```

현재 원장에 8회가 남지 않았다면 이번 실행기는 실행할 수 없다. 한도를 우회하지 않고
사용자의 별도 예산 결정이 있을 때까지 중단한다. Mock으로 자동 대체하지 않는다.

## 보고서 평가 기준

| 항목 | 기록/해석 |
|---|---|
| Tool Calling | Main 실제 호출, Research 실제 도구 query/tag/status, 최소 Context |
| 검색 문서 | Research가 실제로 검색한 문서 ID·본문·태그 |
| 원응답 형식 | `raw_format_compliant`로 bullets/table 구조 검사 |
| 표시 답변 | `final_answer`, 최종 구조 검사와 `fallback_applied`를 원응답과 분리 |
| 사실/근거 | Environment 관측값과 fixture 일치, 검색 원문 대조, 인용 ID 집합 일치 |
| 추가 검토 지표 | raw의 atlas/prototype 리터럴 존재, 선호를 단계로 쓴 의심 표현 |
| 비용 | 실험 전후 원장, 조건별 호출/역할, 실험 증가분의 입력·출력 토큰과 예상 비용 |

리터럴 존재는 번역된 올바른 답변을 놓치거나 잘못된 문장을 통과시킬 수 있다. 원문 대조와
인용 ID 일치는 모든 자연어 주장의 의미 정확성을 보증하지 않는다. 보고서는 항상
`semantic_review_required=true`, `personalization_improvement=not_established`로 시작한다.
`status=executed`도 쌍 실행 완료를 뜻하며 성능 개선 판정이 아니다. 실제 원응답을 사람이
문서/Environment와 대조해야 한다. LLM 평가자 호출은 추가하지 않는다.

예상 비용은 기존 잠정 단가인 입력 $0.15/출력 $0.60 per million tokens로 기록하며 캐시 입력을
일반 입력 가격으로 계산한다. 실패로 usage가 없으면 비용은 미확인이다. Mock 토큰은 스텁의
모의 값으로 표시하고 실제 유료 호출/비용은 0으로 보고한다. 실제 실험의 합산 토큰과 잠정 비용은 위 사용자 제공 결과에 기록했다. 운영 원장의 총 누적 사용량은 확인하지 않았다.

이 실험은 한 질문·한 번의 고정 순서(v1→v2) 비교다. 무작위 순서, 반복 실험, 일반화·통계적
유의성 검증, 전체 세 역할 비교와 Alignment 후보 자동 평가는 범위 밖이다.

## 이전 커밋의 오프라인 검증 기록

Mock·선택된 Hermes 회귀 테스트 **167개**, 필수 검사 **19개**가 통과했다. 전체 Hermes
테스트를 모두 실행한 것은 아니다. 새 실행기 테스트 13개에는 기존 원장 보존, 8회 잔여 예산
검사, 미확인 usage 차단, 첫 오류 후 중단, Alice 전용 접근, 실제 전송 스텁, 프롬프트 통제 검사와
기존 활성 Persona 미변경 검증이 포함된다.

Mock 쌍 재생은 8회 모의 모델 요청으로 완료됐다. v1은 doc-1/doc-2, v2는 doc-3을 조회했고,
atlas/prototype 및 초기 Memory는 동일했다. 원응답 형식은 두 조건 모두 미준수였고 로컬 보정 후
형식을 준수했다. 이 결과는 결정적 Mock의 결과이며 실제 GPT-4o mini 결과가 아니다.
이번 작업의 실제 유료 API 호출은 0회다.

## 이번 수정의 기록 방식

- `raw_answer`: 모델이 반환한 원문. 로컬에서 덮어쓰지 않는다.
- `presentation_input`: 역할 완료 문구와 근거 정정을 반영한 형식 변환 직전 텍스트.
- `final_answer` / 채팅의 `answer`: 화면에 표시할 로컬 처리 결과.
- `format_validation.raw_valid`: 모델 원문 형식 검사.
- `format_validation.presentation_input_valid`: 변환 직전 텍스트의 형식 검사.
- `format_validation.fallback_applied`: 로컬 형식 보정 여부.
- `evidence_validation`: 출처, 원문 오류 신호, 로컬 근거 정정 여부.

현재 턴에서 실제 조회한 Environment와 RAG 검색을 별도 출처로 보관한다. 알려진 단계·제약의
누락, 미확인 표현, 명시적인 단계 충돌, 검색 범위를 넘는 부재 주장을 검출한다. 근거 정정은
조회된 값만 덧붙이며 모델 초안을 보존한다. 임의의 날짜·숫자·상태를 생성하지 않는다.
표는 항목/내용 또는 순서/내용으로 구성하고 기존 여러 열은 유지한다. HTML 줄바꿈 대신
행으로 나누며 숫자·날짜·문서 ID·불확실성 표현을 그대로 전달한다.

이 검사는 제한된 필드와 한영 표현 패턴에 대한 것으로 전체 의미 검증이 아니다. 원문은
검토 대상으로 남고, 경고가 없다는 사실도 모든 주장의 정확성을 보증하지 않는다. 실제 모델이
수정된 프롬프트를 따르는지는 API 재호출 없이 검증할 수 없다.

이번 오프라인 검사 결과와 사내 확장 과제는 [VALIDATION_FOLLOWUP.md](VALIDATION_FOLLOWUP.md)에 기록한다.

## 후속 오프라인 검증 결과

이번 수정에서는 실제 API 호출 없이 프로토타입과 선택한 Hermes 회귀를 실행했다.
통합 재실행은 205개 중 204 통과, 기존 시스템 프롬프트 동일성 검사 1개 실패였다.
해당 테스트 단독 1개와 파일 전체 11개는 재실행에서 통과했지만 간헐 실패가 해결됐다는
뜻은 아니다. Alice/Bob/Carol, 세 역할 실행, 격리, 근거 검출, 표 보존, Streamlit AppTest,
기존 비용 제한 관련 결과와 남은 문제는 후속 검증 문서에 구분해 기록했다.
