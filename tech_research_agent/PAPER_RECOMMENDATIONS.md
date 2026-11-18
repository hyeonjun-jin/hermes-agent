# Persona × Environment 맞춤 논문 추천

기존 Research → Analysis → Verification Hermes 3-Agent를 유지하고 논문 추천을 로컬
후처리로 추가했다. 별도 Orchestrator/LLM/임베딩/학습은 없다. 적합도 점수는 논문 품질·
실제 기술 우위·개인화 학습 효과를 입증하지 않는다. 운영 Persona·원장·승인은 바꾸지 않는다.

## 기본 Mock 사용

Streamlit에서 researcher 또는 strategy를 선택하고 **맞춤 논문 추천 요청 (Mock)** 버튼을
누르거나 같은 질문을 입력한다.

> 수소환원제철 관련 논문 추천과 근거를 알려주세요.

기존 실행 명령을 사용한다.

```bash
streamlit run tech_research_agent/ui.py
```

버튼은 정보원 Connector가 없는 기본 Mock에서만 활성화한다. 기존 일반 보고서와 세 역할
결과·근거·피드백 UI는 유지한다. 추천 패널에는 제목·연도·확인된 링크·초록 확인 여부·
분항 점수·Persona/Environment 근거를 표시하며 적합 후보가 부족하면 없는 논문을 채우지 않는다.

## 후보와 권한

- 기본 Mock의 명시적 논문 추천 요청에만 애플리케이션 전용 SYNTHETIC 논문 6건을 사용한다.
  H 프로젝트 4건, B 프로젝트 2건이다. 실제 제목/DOI를 만들어내지 않으며 링크도 없다.
- 기존 SourceAdapter에 같은 서버 Context/Registry를 전달한다. OpenAlex search_works →
  read_work를 실제 도구 흐름으로 실행하며 검색·조회하지 않은 ID는 추천하지 않는다.
- Mock 논문 검색은 현재 요청에 따라 중립적인 프로젝트 query로 고정한다. researcher와
  strategy의 동일 후보 실험에서 검색 pool 자체를 직무별로 바꾸지 않는다.
- H 4건일 때 Research 검색 1회·Read 4회, Verification 재조회 4회로 도구 단위 9를 쓴다.
  모델 요청은 R3/A1/V2 총 6회이며 기존 한도를 확장하지 않는다. 정렬 자체의 추가 호출은 0이다.
- 기존 API 권한·기준일 필터를 적용하고, 추천 직전 현재 접근 권한/프로젝트/토픽/기준일과
  관찰된 item의 제목·날짜·span·synthetic 표기를 다시 대조한다. 취소·변조·미조회 항목은 제외한다.
- 실제 Connector/승인 공개자료 경로에서도 이미 실행된 search/read trace만 후처리한다.
  추천을 위해 몰래 새 API를 호출하지 않는다. 추천할 논문을 조회하지 않았다면 빈 결과다.
- OpenAlex의 공개 논문은 글로벌 자료이므로 내부 프로젝트 ID가 없는 경우 프로젝트 관련
  키워드로 추가 판별한다. 현재 H/B 프로젝트 사전은 작은 heuristic이며 일반 분야 의미 검색이 아니다.

## 분항 점수: deterministic_heuristic_v1

| 분항 | 규칙 |
|---|---|
| 프로젝트 관련성 | 토픽 단어 일치 6점 + 질문 단어 최대 2점 + 목적 개념 최대 4점. 토픽 불일치는 추천에서 제외 |
| Profile 전문성 | expertise/job/criteria와 문서 제목·확인 초록의 개념 교집합당 2점, 최대 10점 |
| 승인 Persona 기준 | 문서가 충족한 승인 criteria당 5점, 최대 15점 + OpenAlex 선호 1점 |
| 최신성 | 환경 as_of/cutoff 이내에서 3년 선형 감쇠, 기본 최대 4점. 마감 3일 이내에는 1.25배 |
| 메타데이터 충실도 | 제목/날짜 2 + 연도 1 + 제공된 DOI 1 + 확인 초록 3. 상세 선호 +0.5, quick/급한 마감 +0.5 가중 |

영문/한글 소수 개념 사전을 사용한다. 같은 점수는 발행일 내림차순·ID로 고정 정렬한다.
사용자 ID별 순위 분기나 학습 가중치는 없다. Persona는 명시 승인된 현재 research_persona
선호만 적용하고 과거 이력에서 암묵적 선호를 새로 만들지 않는다. 정보원 선호는 권한이 아니다.
현재 후보가 전부 OpenAlex라면 그 정보원 선호는 동일한 상수점이며 개별 논문 차이를 만들지 않는다.

예시: 같은 H 후보 4건, 같은 질문·Environment, 별도 Persona 기준 없음.

| 순위 | researcher | strategy |
|---|---|---|
| 1 | H-PAPER-EXP 실험 조건·재현성 / 30.306점 | H-PAPER-BIZ 상용화·시장 전환 / 30.169점 |
| 2 | H-PAPER-PILOT 파일럿 공정 비교 / 26.027점 | 동일 / 26.027점 |
| 3 | H-PAPER-BIZ / 22.169점 | H-PAPER-EXP / 20.306점 |

researcher의 EXP 전문성 교집합은 10점, strategy의 BIZ 교집합은 8점이다. 그 차이로 순서가
바뀐다. 승인된 financial_risk/commercialization Persona를 적용하면 같은 researcher의
순위도 바뀌는 테스트가 있다. 이 값은 합성 문서의 기능 예시이지 실제 논문 성능 결과가 아니다.

## 출처·개인정보

제목·날짜·DOI는 조회 item 또는 명시된 SYNTHETIC payload만 사용한다. DOI는 Source가
제공한 유효한 doi.org URL만 표시하고 제목/연도로 DOI를 추정하지 않는다. 주소 응답/실제
등록을 독립 조회 검증한 것은 아니다. 자격 증명·query·fragment URL, 잘못된 scheme은 표시하지 않는다.
초록 없는 partial metadata는 초록 미확인으로 표시한다. PDF 원문은 다운로드/열람하지 않는다.
원문 위치 링크를 표시하는 것도 본문을 읽었다는 뜻이 아니다. TOP 3가 종합 기술 검증은 아니다.

승인된 PRIVATE Persona는 사용자 권한 안에서 로컬 점수에만 쓴다. 추천 계산은 모든 모델
교환이 끝난 뒤 실행하고 새 추천/근거 필드를 모델 Context에 넣지 않는다. 기존 report.answer와
그 Memory 문자열도 재작성하지 않는다. 추천 결과는 해당 사용자의 UI/로컬 turn 기록에만 남는다.
approved_public의 최소 공개 표현·Memory 승인 경계와 일반 UI의 유료 호출 한도는 그대로다.
개발용 사용자 선택은 실제 서비스 인증이 아니며 운영 서비스에는 별도 인증/ACL 연동이 필요하다.

## 실제 GPT-4o mini 검증 전 남은 조건

이번에는 실제 LLM·외부 정보원 호출을 하지 않았다. 실제 데이터 추천 검증에는 서비스
권한/키, 실제 OpenAlex 검색·Read 결과, 현재 원장/고정 plan·실행/비용 승인, 문서·Persona
최소 표현·Memory 반출 승인, 정확한 응답 모델 식별자와 생성 옵션 검수가 필요하다.
기존 [Live 비교 실행 지침](LIVE_PAIRED_COMPARISON.md)을 유지한다. 로컬 ranking은 추가
유료 호출이 없지만 실제 후보 취득/3-Agent 실행은 승인된 기존 예산 안에서 수행해야 한다.
실제 추천 적합도와 개념 사전의 오탐/누락, 가중치의 타당성은 사용자·전문가 검토가 필요하다.

```bash
HERMES_TEST_FILE_RETRIES=0 scripts/run_tests.sh \
  tests/tech_research_agent/test_paper_recommendations.py -q
```

## 이번 검증

공식 runner로 기술조사·기존 Persona·MemoryProvider/위임 범위 **35개 파일, 652개 통과,
실패 0개**를 확인했다. 신규 추천 테스트는 21개이며 같은 후보의 Profile/Persona별 순위,
권한·프로젝트·기준일·검색/Read 관찰 여부, metadata-only, URL, 사용자 격리, PRIVATE
로컬 후처리의 wire 비노출, Streamlit 사용자 전환과 기존 보고서 표시를 검사한다.
정적 검사 19개도 통과했다. 실제 OpenAI·외부 정보원 API 호출은 0회다.
