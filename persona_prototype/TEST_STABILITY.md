# 시스템 프롬프트·Tool Schema 안정화

기준: `0bf82687`, `feat/persona-gpt4o-mini-validation`. 실제 OpenAI 호출 없이
loopback Mock과 회귀 테스트만 사용했다. 과거 204/205 실행의 요청 원본은 없으므로,
그 실행에서 바뀐 바이트까지 확인했다고 주장하지 않는다.

## 검사하는 계약

`test_snapshot_reuse_and_fresh_lookup_keep_stable_prompt_and_tools`는 같은 세션에서
현재 조회 → 과거 Snapshot → 인사 → 사용자 확인 → 현재 재조회 순서로 실행한다.
Environment의 stage를 prototype에서 pilot으로 바꿔도 과거 답은 prototype,
새 조회는 pilot이어야 한다. 인사·사용자 확인·Snapshot에는 도구 호출이 없어야 한다.
모든 모델 요청의 시스템 메시지와 전체 tools 배열은 첫 요청과 정확히 같아야 한다.
배열 순서, 설명, 인자 스키마까지 비교하며, 첫 호출의 Environment 도구 강제 선택도 유지한다.

진단 helper는 전체 시스템 메시지·스키마와 SHA-256 지문을 JSON 파일로 남긴다.
실패하면 요청 번호별 unified diff를 시스템/도구 양쪽 모두 출력한다. 기존 assertion을
없애거나 조건을 완화하지 않았다. 이 기록은 테스트 fixture에만 적용하며 운영 로그가 아니다.

## 확인한 원인

ChatSessions는 한 세션을 유지하지만 ChatApplication은 사용자 턴마다 새 AIAgent를
만든다. 따라서 Hermes의 인스턴스 내부 프롬프트 캐시가 턴 사이에 재사용되지 않는다.
`skip_context_files=True`만으로는 호스트 Git 컨텍스트와 도구체인 탐침이 꺼지지 않는다.

기준 코드에서 두 회귀 테스트를 각각 결정적으로 실패시켰다. 대기 sleep 없이 상태 전환을
제어했으며 두 경우 모두 **시스템 프롬프트만 변경, Tool Schema는 동일**했다.

1. 임시 Git 작업 공간에 사용자 업무와 무관한 파일을 하나 추가했다.

```diff
 Workspace (snapshot at session start — re-check with `git` before acting on it):
 - Root: <temporary workspace>
 - Branch: master
-- Status: 1 untracked
+- Status: 2 untracked
 - Project: pyproject.toml
```

2. 첫 요청에는 비어 있던 호스트 탐침 결과가 다음 요청에 준비되는 상황을 주입했다.

```diff
+Python toolchain: fixture probe completed after the first turn.
+
```

실제 탐침은 비동기 완료와 프로세스 전역 캐시를 사용하므로 완료 시점에 따라 이 경로가
달라질 수 있다. 병렬 부하는 가능성을 높일 수 있지만, 재현에 병렬 실행은 필요하지 않았다.
통제하지 않은 기준 통합 재실행은 205/205였다. 즉 자연 발생 실패를 다시 잡은 것은 아니며,
같은 불변 조건을 깨는 두 경로를 통제 실험으로 확인한 것이다.

## 상태·순서 점검

- 공식 runner는 파일별 별도 프로세스를 쓴다. 파일 간 Python 전역 변수는 공유하지 않는다.
  파일 안의 전역 캐시는 여전히 영향을 줄 수 있다.
- 해당 테스트는 tmp_path별 저장소·사용자 홈을 사용한다. ENVIRONMENTS는 monkeypatch로
  교체하고 fixture 종료 시 복원한다. 새 탐침 재현도 monkeypatch를 사용하며 cwd는 finally에서 복원한다.
- 사용자 소유자와 Hermes home의 ContextVar는 finally에서 reset된다. ChatSessions의
  RLock은 해당 인스턴스의 요청을 직렬화한다. 다중 프로세스 전체에 대한 보장은 아니다.
- 임시 Git 파일 변경만으로 단독 실패했으므로 Mock 데이터 오염이나 실행 순서는 필수 조건이 아니다.
  파일 전체 역순 실행도 별도 확인한다. 진단용 reverse_order_probe는 명시적으로 로드할 때만 동작한다.
- Hermes 날짜 줄은 날짜 단위다. 초·분 경과는 원인이 아니지만, 턴마다 에이전트를 만들기 때문에
  자정·시간대 변경을 넘는 세션의 불변성은 이번 수정으로 보장하지 않는다.

## 수정 범위

프로토타입이 생성하는 config에 기존 Hermes 옵션 `coding_context: "off"`,
`environment_probe: false`를 적용한다. 사용자 Profile, 업무 Environment 도구 관측,
RAG 근거는 계속 전달한다. Hermes 코어와 도구 스키마는 수정하지 않았다.
API 재시도·복구·위임 한도와 사용량 원장도 변경하지 않았다.
기존 자동 생성 설정과 정확히 일치하는 파일만 업그레이드하며 사용자 수정 설정은
덮어쓰지 않고 오류를 낸다. 마이그레이션·한도 유지·멱등성·사용자 설정 보호를 검사한다.

## 검증 결과

| 실행 | 결과 |
|---|---|
| 수정 전 기존 통합 | 205 통과 / 0 실패 |
| 수정 전 통제 재현 두 건 | 0 통과 / 2 실패 (시스템만 변경) |
| 수정 후 대상 파일 + 신규 회귀 | 16 통과 / 0 실패 |
| 수정 후 기존 통합만, 3 workers | 205 통과 / 0 실패, 180.7초 |
| 필수 정적 검사 | 19개 통과 |
| 수정 후 확장 통합, 3 workers | 210 통과 / 0 실패, 120.0초 |
| 원래 문제 테스트 단독 반복 | 5회 모두 통과, 자동 재시도 없음 |
| 해당 파일 역순 | 11 통과 / 0 실패 |

확장 통합은 기존 205개에 재현·설정 보호 회귀 5개를 추가한 것이다.
Alice/Bob/Carol, Research·Analysis·Verification, Persona/Memory 격리, 근거 정확성,
원장/호출 제한 및 Streamlit AppTest 4개가 포함된다.

재실행 명령 (테스트 인터프리터는 Streamlit 포함):

```bash
export HERMES_TEST_FILE_RETRIES=0
scripts/run_tests.sh -j 3 tests/persona_prototype tests/agent/test_memory_provider.py tests/agent/test_memory_provider_caller_profile.py tests/agent/test_memory_manager_fork_scope.py tests/tools/test_delegate_toolset_scope.py -q
scripts/run_tests.sh -j 1 tests/persona_prototype/test_project_facts.py -k test_snapshot_reuse_and_fresh_lookup_keep_stable_prompt_and_tools -q
scripts/run_tests.sh -j 1 tests/persona_prototype/test_project_facts.py -p tests.persona_prototype.reverse_order_probe -q
```

수정 전 재현은 신규 test_prompt_stability.py의 Git/탐침 두 테스트를 유지하고
app.py를 기준 커밋 상태로 둔 실행이다. 수정 후와 같은 Mock과 assertion을 사용했다.
원래 205개만 실행할 때는 `git ls-tree -r --name-only 0bf82687 tests/persona_prototype`의
기존 test 파일 13개를 명시하고 Hermes 회귀 파일 4개를 함께 넘겼다.

공식 `scripts/run_tests.sh`를 사용하고
파일 자동 재시도는 0으로 설정했다. Streamlit 설치 환경을 사용해 UI 검사가 생략되지 않는다.
환경의 기본 runner 임시 경로가 읽기 전용이어서 외부 래퍼로 쓰기 가능한 임시 경로만 바꿨다.
네트워크 차단과 공식 실행 환경 정리는 유지했다.

## SSO·문서 ACL 구현 전 정리할 위험

1. 세션 수명과 프롬프트 수명을 맞춰야 한다. 자정·시간대·설정 갱신·압축 경계에서의 캐시 계약,
   세션 재시작과 스키마 버전 변경 정책을 먼저 정하고 장기 세션 회귀를 추가해야 한다.
2. 현재 인스턴스 RLock과 로컬 저장소는 여러 worker의 격리·예산 예약을 보장하지 않는다.
   인증 주체에 연결된 세션 저장소, DB 트랜잭션, 전역/사용자별 원장과 동시성 검사가 필요하다.
3. ACL은 최종 답변 필터만으로 부족하다. 검색 후보, 캐시, Memory, 위임된 각 역할과 도구 실행에
   같은 소유자/조직 컨텍스트를 전달하고 권한 취소 후 남은 Snapshot도 무효화해야 한다.
4. Persona는 권한이 아니다. 선호보다 권한·명시 요청·실제 Environment 제약을 우선하는
   서버 측 실행 검증과 쓰기 도구의 승인·멱등성·감사 로그가 필요하다.
5. 현재 Mock/패턴 기반 근거 검사는 실제 문서의 간접 프롬프트 주입이나 복잡한 사실 왜곡을
   보장하지 않는다. 실제 업무별 도구/인자 평가셋과 비밀·개인정보 로그 정책이 필요하다.

이번 통과는 운영 SSO·ACL·다중 사용자 부하 검증 완료를 뜻하지 않는다.
