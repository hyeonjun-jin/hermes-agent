# 기술조사 벤치마크 P0

모델·네트워크·실제 Agent 연결이 없는 로컬 데이터와 검증기다.
기준 설계는 루트 TECH_RESEARCH_AGENT_PLAN.md / BENCHMARK_DESIGN.md (29b1c92c).

- `data/evaluation/inputs`: 독립 사례 18개. agent_input()은 이 경로만 읽는다.
- `data/evaluation/gold`: 호출 인자·의존관계·필수 span·금지 정책. Agent에 제공하면 안 된다.
- `data/corpus.json`: 24개 필수 합성 문서와 4개 방해 문서. 실제 논문·특허·기업 공시가 아니다.
- `data/development`: 별도 DEV ID·질문·기술 사실이 아닌 문장으로 구조 검사. 평가용 이력과 분리.
- `data/registry.json`, `schemas`: 11개 API의 RP/OP 및 input/gold/corpus JSON Schema.
- `data/definitions.json`: 문서의 Profile/Environment 상속 검증용, Agent input 로더는 접근하지 않는다.
- `data/manifest.json`: SHA-256. 전문가 검수 전 draft이며 최종 동결/승인을 주장하지 않는다.

```bash
python -m tech_research_benchmark.offline
```

Python API: `score(case, gold, predicted_calls, supplied_evidence, corpus, registry)`.
예측 호출은 id/app/api/rp/op/after 구조다. 예측 after 주장을 믿지 않고 배열의 실제 순서로
선행 관계를 확인한다. 증거는 document_id/span_id 목록이며 일치하는 read가 있어야 점수를 준다.
이것은 오프라인 trace 구조 평가로, 실제 도구 실행·원문 이해·답변 entailment를 입증하지 않는다.
Gold 자체는 APP/API/RP/OP/증거 1.0이다. 보안 위반은 business_success=false.
보안 위반이 없어도 사람이 확인해야 하므로 business_success=null이고 structural_success와 구별한다.

## 자동 평가의 범위

RP/OP는 명세값·명시된 sort 대안의 정확 비교다. 같은 API의 반복 호출은 일대일 매칭하며
추가 호출은 비용/불필요 호출로 남는다. ID 순서보다 실제 실행 순서를 검사한다.
자연어 query 동의어, 실제 근거의 적합성·청구항 의미·업무 목적은 자동 판정하지 않는다.
반출 검사는 project ID와 알려진 비공개 span의 직접 전송을 검출하는 최소 검사이며,
패러프레이즈·부분 문자열·은밀한 반출까지 막는 보안 필터가 아니다.
APP는 집합 F1, API/RP/OP는 전체 호출 수를 분모로 한 보수적 일대일 정확도다.
설계의 완성된 nDCG/의미 기반 OP macro F1/실제 비용 평가가 구현된 것은 아니다.

## 전문가 검수 목록 (18개 모두 pending)

| 사례 | 필수 정답·근거 | 검수할 대안/한계 |
|---|---|---|
| H-R-E1, B-R-E1 | A01/P01 조건·청구항·상업 적용 한계 | query 동의어, sort·기간·limit 범위, 원문 read 생략 가능성 |
| H-R-E2, B-R-E2 | A01/P01/N2R 조건·재현성 비교 | N-alt의 동등 실험 조건·ACL·최신성 |
| H-R-E3, B-R-E3 | N3R만, 과거 Snapshot 한계 | 최신 외부 실증 미확인, 외부 호출 금지 |
| H-S-E1, B-S-E1 | D01/IS01 계획·실적·시장 coverage 구분 | D-alt DA01 및 I-alt IA01의 동일 span 요건 |
| H-S-E2, B-S-E2 | D01/IS01/N2S 의사결정 근거 | D/I/N 대안의 의미 동등성·독립성 |
| H-S-E3, B-S-E3 | N3S만, 현재 시장 미검증 | 승인 Snapshot 범위와 한계 |
| H-F-E1, B-F-E1 | F01/IF01, 2025 CFS·단위·100~120 계획 구분 | 계정 동의어와 I-alt IFA01; OFS 불허 |
| H-F-E2, B-F-E2 | F01/IF01/N2F, +10%→+3% 가정 | N-alt·계정 매핑, 기술별 ROI 확정 금지 |
| H-F-E3, B-F-E3 | N3F만, 가정·Snapshot 한계 | 공개 재무 재조회 금지·예측/실적 구분 |

설계에서 DA01/IA01/IFA01/ALT는 '동등 span이 있는 문서를 준비한다'는 조건부 이름만
있고 해당 원문이나 실제 대안 일정은 정의되지 않았다. 임의 원문·숫자·정답을 만들지 않기 위해
pending_alternatives에 기록하고 자동 허용하지 않는다. query 의미 동등성도 같은 방식이다.
현재 수치 없는 실험 문장은 조건 비교의 필요성을 나타내는 합성 골격이지 실험 결과가 아니다.
전문가가 이를 실제적인 평가 근거로 확정해야 하며 공개 기술지식을 입증하는 자료가 아니다.
따라서 P0 구조 데이터는 실행 가능하지만 **전문가가 승인한 최종 평가셋은 아직 아니다**.

## 검증

공식 runner로 신규 scorer/validator 검사와 기존 persona·Memory·위임 회귀를 함께 실행한다.
코어·기존 Mock·사용량 원장·예산 설정은 수정하지 않는다. 실행 결과는 P0_VALIDATION.md에 기록한다.
