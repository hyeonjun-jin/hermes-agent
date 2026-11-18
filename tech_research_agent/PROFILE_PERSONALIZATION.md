# 사용자 단위 Profile·관심사 개인화

기준 `599c06c518`의 기존 3-Agent, SourceAdapter, Environment 자원 표시, Evidence,
승인 Persona/Memory 기능을 확장한다. ML 학습·embedding 의미 검색·추천 품질 개선을
주장하지 않는다. 실제 OpenAI·외부 정보원 API는 이번 검증에서 호출하지 않았다.

## 입력과 보존 경계

| 입력 | 내용 | 변경·권한 |
|---|---|---|
| Profile | business_unit, department, job, expertise, interests[], criteria; 기존 focus 호환 | 소유자가 명시적으로 편집. 직무·사업부서로 접근 권한을 부여하지 않음 |
| Persona | 사용자·프로젝트별 승인 preferences, revision | 기존 피드백·후보·승인·거절·롤백 절차 유지 |
| Memory | 사용자·프로젝트별 Episodic 조사 이력, Legacy Semantic 선호 | 관심사를 자동 추론하거나 Profile/Persona로 승격하지 않음 |
| Environment | 프로젝트·목적·마감·기준일·분류·allowed_sources·information_resources | 기존 서버 ACL 및 정보원 접근 조건 유지 |
| Evidence | 성공한 Read의 ID·span·확인 범위 | Profile이나 관심사를 사실 근거로 사용하지 않음 |

`ResearchApplication.profile/update_profile/reset_profile`은 기존 OwnerOnly의 사용자별
읽기/쓰기 검사를 거친다. 기본 Profile은 깊은 복사로 보존하며 다른 사용자와 공유하지 않는다.
편집은 앱 프로세스 메모리에만 저장하고 서버 재시작 시 초기화한다. 조사 실행 시에는 기존
조사 이력의 입력 스냅샷에 당시 Profile이 남는다. 운영 Persona/DB 스키마·usage.json·승인
파일을 마이그레이션하거나 초기화하지 않는다. 기본 researcher/strategy/finance는 유지한다.
business_unit이 없는 기존 Profile도 ranking에서는 추가 점수 0으로 처리할 수 있다.

편집된 Profile은 **PRIVATE**이다. `real`, `approved_public`, 외부 Connector가 연결된
Mock 경로는 전송 전에 차단한다. 따라서 관심사를 검색 인자에 넣어 PRIVATE 정보를 외부
정보원에 보내는 일도 차단한다. UI의 적용 버튼은 외부 처리 승인이 아니다. 원래의 기본 합성
Profile로 복원하면 기존 경로의 모든 승인·권한·예산 검사가 그대로 적용된다.

## Research와 Analysis

ResearchProvider는 모든 역할에 동일한 Profile, 승인 Persona, Environment를 제공한다.
정적 지침은 직무·관심사를 검색어/분석 질문의 참고로 사용하고 현재 질문·Environment 및
승인 Persona를 우선하도록 한다. 모델 도구 선택을 가로채거나 관심사별 Connector를 고정하지
않는다. 기존 4종 Connector·APP/API/RP/OP Schema와 SourceAdapter 정책 검사가 실행된다.

Mock만 `interests.py`의 결정론적 검색 힌트를 검색어에 추가한다. 이것은 실제 LLM 판단이
아니다. 논문 추천 fixture는 topic 검색어와 관심사 검색어를 OR로 검색하므로 동일 네 후보를
유지해 검색 인자 변화와 고정 후보 reranking을 분리하여 확인할 수 있다. 실제 OpenAlex의
검색 후보가 같다는 가정은 할 수 없다.

Analysis Mock은 관련 관심사의 검토 관점(반응 메커니즘·반응속도, 공정 조건·최적화,
에너지 효율·생산성, 사업화·시장)을 설명한다. 새로운 성능 수치나 결론은 생성하지 않으며
근거가 없으면 미확인으로 남긴다. Verification의 원문 재조회·숫자/인용 검사 구조는 유지한다.
TechnicalMockReplay는 명시적으로 기록된 Profile을 **임시 재생 앱에만** 복원하여 후보 비교
양쪽의 Profile을 고정한다. 운영 Profile이나 승인 Persona를 과거 이력에서 갱신하지 않는다.

## 설명 가능한 ranking v2

제목·확인한 초록에 한영 키워드 사전을 적용한다. 사용자 ID를 점수 계산에 사용하지 않는다.

| 점수 항목 | 계산 |
|---|---|
| project_relevance | 기존 주제 일치 + 질문 어휘/목적 일치; 명시된 질문/업무 목적 관점이 논문에서 확인되면 32 추가; 적합성 0이면 제외 |
| profile_expertise | 전문성·직무·평가 기준의 기존 개념 일치, 2 × 최대 5개 |
| profile_business_unit | 철강/이차전지소재와 논문 주제 어휘 일치 시 2; 필터나 접근 권한이 아님 |
| profile_job | 직무·부서 텍스트의 기술/사업 개념 일치, 최대 2 |
| personal_interests | 관련 관심 개념 일치당 8, 미등록 키워드 일치당 2, 합계 최대 24 |
| persona_criteria | 기존 명시 승인 기준 일치당 5 × 최대 3개, OpenAlex 선호 1 |
| recency | 기존 기준일 대비 최근성; 긴급 마감 가중치 유지 |
| metadata_completeness | 기존 연도·DOI·초록 및 승인 깊이/마감 가중치 유지 |

프로젝트가 다른 관심사는 억제한다. 질문이나 Environment 목적에서 특정 관심 개념을
명시하면 그와 충돌하는 Profile 관심사에는 점수를 주지 않는다. 인식 범위는 제한된
키워드 규칙이며 모든 자연어 조건·부정·동의어를 이해하는 모델이 아니다. 사업부서가 달라도
관심사가 같으면 그 관심사 일치 점수를 받을 수 있다. 근거에는 일치 개념·어휘, 억제된
관심사, 우선 적용된 질문/업무 목적과 전체 점수 기여도가 표시된다. 직무명이 개념과 직접
일치하지 않으면 직무 점수는 0이다. 사용자별 임의 보너스를 넣지 않는다.

## 재현 가능한 두 통제 실험

```bash
python -m streamlit run tech_research_agent/ui.py
python -m tech_research_agent.profile_experiments
```

UI의 `개발 Profile 수정 · 사용자별 관심사`에서 현재 사용자만 편집/복원한다.
`동일 직무 · 서로 다른 관심사 비교` 버튼은 임시 앱 네 개로 두 실험을 실행한다.
SYNTHETIC 4개 후보, 질문, Environment, 초기 빈 Episodic/Semantic Memory,
Tool Schema가 같고, 관심사 비교의 사업부서·직무·전문성·criteria·Persona 입력도 같다.
각 실행은 Research 3 + Analysis 1 + Verification 2 = **Mock 6회**, 전체 **Mock 24회**다.
실제 모델/외부 정보원 호출은 0회이며 운영 호출 원장을 사용하지 않는다.

실험 1: 연구원은 실험 조건 후보가 1위(32.306), 전략실은 상용화 후보가 1위(33.169)다.
직무 비교는 기존 focus와 criteria도 다른 전체 Profile 비교이며, 직무명 하나의 인과 효과를
분리한 실험은 아니다.

실험 2: 동일한 철강/연구소/박사 연구원/공정·소재 Profile에서 관심사만 바꿨다.
아래 제목은 **가상 SYNTHETIC 문서**이며 실제 논문/DOI가 아니다.

| 관심사 | 1위 | 2위 | 3위 |
|---|---|---|---|
| 수소환원 반응 메커니즘 | 실험 조건과 재현성 40.306 | 파일럿 공정 비교 28.027 | 상용화와 시장 전환 24.169 |
| 수소환원 공정 최적화 | 파일럿 공정 비교 36.027 | 실험 조건과 재현성 32.306 | 상용화와 시장 전환 24.169 |

메커니즘 1위: 프로젝트 7 + 전문성 10 + 사업부서 2 + 직무 0 + 관심사 8 +
승인 Persona 0 + 최신성 4.306 + 메타데이터 9 = **40.306**.
초록의 `reaction mechanism`/`환원 원리`가 관심사와 일치한다.

최적화 1위: 프로젝트 9 + 전문성 4 + 사업부서 2 + 직무 0 + 관심사 8 +
승인 Persona 0 + 최신성 4.027 + 메타데이터 9 = **36.027**.
초록의 `process optimization`/`공정 최적화`가 관심사와 일치한다.
두 조건 모두 같은 Evidence 원문과 권한 해시를 기록한다. Persona의 created_at/reason은
모델에 전송되지 않으므로 입력 통제 해시에서는 제외하고 revision/preferences/data_policy를
비교한다. 초기 승인 기준은 비어 있으므로 이 실험의 Persona 점수는 0이다. 기존 승인
Persona가 ranking을 바꾸는 별도 회귀 테스트도 유지한다.

## 실제 LLM 실험 3: 준비 항목과 NO-GO

`profile_experiments.live_preparation(app, actor, question)`은 **이미 실행 중인 앱**의
사용자·프로젝트를 검증한 뒤 SQLite를 `mode=ro`로 읽는다. Persona/Memory가 없어도 생성하지
않으며 입력별 해시, 승인 Persona 존재 여부, 필요한 관리자 확인 사항만 반환한다.
PRIVATE Profile·Memory 원문을 보고서에 내보내지 않는다. 이는 승인서나 실제 실행기가 아니다.

실제 실험에는 다음이 필요하다.

1. 최소 Profile/관심사 공개 표현에 대한 별도 관리자 검토와 정확한 전송 경계.
   현재 편집 Profile 반출 승인은 **미구현**이며 `approved_public` 문서/Persona 승인으로
   대체할 수 없다. 실제 사용자 Profile을 기본 합성 Profile로 위장하지 않는다.
2. 두 독립 실행의 Profile에서 interests 외 필드, Environment, 질문, Persona 선호·버전,
   초기 Memory, Tool Schema, 실제 정보원 권한·모델 생성 옵션의 동일성 확인.
3. 정보원 이용권한·문서별 외부 처리 승인과 사용 시 Persona/Memory 반출 승인.
4. canonical 원장·호출/비용 계획과 별도의 유료 실행 승인. 검색→Read→최종 응답의
   Research 3회가 필요한 경우 기존 일반 역할당 2회 경로는 완주하지 못할 수 있다.
   승인 없는 예산 확대나 기존 원장 초기화를 하지 않는다.
5. 모델 응답 식별자(관측값 `gpt-4o-mini-2024-07-18`)의 정확한 관리자 검토 및 allowlist,
   현재 입력/옵션 해시에 묶인 실행 승인. 관측값만으로 승인 완료로 간주하지 않는다.
6. 최종 전송 Payload의 Profile 이외 차이와 첫 Tool 결과 이후 파생 차이를 구분하고,
   APP/API/RP/OP·조회 문서·원응답·최종 추천·호출/토큰/비용을 기존 audit/observer로 기록.

기존 PairedPublicComparison은 **Persona만 다른 비교**이므로 Profile이 다른 두 조건을
그대로 넣으면 고정 입력 불일치로 차단한다. 이 경계를 완화하지 않았다. 실제 Profile 비교
실행과 반출 승인 연결은 후속 작업이다. 이번에는 Mock 비교와 입력 준비까지만 확인했고,
실제 LLM의 검색 판단·개인화 품질이 개선됐다고 결론 내리지 않는다.
