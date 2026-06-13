# LBH / CatGPT Gateway Reliability Report

작성일: 2026-06-13

## 1. 요약

현재 프로젝트의 핵심 문제는 ChatGPT가 생성한 패치가 항상 신뢰 가능하지 않다는 점이다. 최근 검증에서 ChatGPT가 `src/lbh/run_command.py`를 수정하면서 `_run_init`, `_run_index` 정의를 삭제했지만 호출부는 남겨 두는 패치를 만들었고, 기존 검증기는 이를 패치 적용 전 단계에서 잡아내지 못했다. 이 문제는 단순히 모델 성능 저하로만 볼 수 없으며, LLM 기반 패치 생성에는 구조적으로 항상 발생 가능한 실패 유형이다.

따라서 개선 방향은 ChatGPT 응답 품질에 의존하는 것이 아니라, 로컬에서 결정적으로 실행되는 preflight, validator, test selector, smoke check, reviewer loop를 계층화하는 것이다. ChatGPT는 패치 제안자 또는 리뷰어로 사용할 수 있지만, 최종 품질 게이트는 로컬 도구가 맡아야 한다.

## 2. 현재 구조

LBH는 로컬 저장소를 대상으로 컨텍스트를 수집하고, CatGPT Gateway를 통해 ChatGPT 웹 세션에 요청을 전달한 뒤, 응답에서 패치 후보를 추출하고 검증한다. CatGPT Gateway는 Docker 환경에서 구동되며, API는 bearer token 인증을 사용한다.

현재 주요 명령은 다음과 같다.

- `lbh preflight`: 대상 저장소, LBH 체크아웃, Docker daemon, `.lbh`, 인덱스, gateway 인증 및 `/status`를 확인한다.
- `lbh gateway-run`: ChatGPT Gateway에 직접 요청을 보내고 결과를 받아온다.
- `lbh run`: `preflight`와 `gateway-run`을 순차 실행하는 통합 명령이다. 필요하면 `init`, `index`도 결정적으로 수행한다.

관련 구현 위치는 다음과 같다.

- `src/lbh/preflight.py`
- `src/lbh/run_command.py`
- `src/lbh/cli.py`
- `src/lbh/core/config.py`
- `src/lbh/core/request_classification.py`

## 3. 최근 처리된 문제

### 3.1 스킬 문서 장황성

초기 문제는 Codex가 읽는 스킬 문서가 지나치게 장황하여, 매번 절차 해석에 불필요한 토큰을 소비한다는 점이었다. 이에 따라 스킬 문서의 성격을 "절차 설명서"에서 "실행 명령 중심"으로 줄이는 방향을 검토했다.

결론은 다음과 같다.

- 반복적이고 결정적인 절차는 문서가 아니라 스크립트로 이동해야 한다.
- Codex가 해석해야 하는 내용은 최소화해야 한다.
- preflight와 run은 사용자가 직접 기억하거나 조합하는 절차가 아니라 명령 하나로 실행되어야 한다.

### 3.2 CatGPT Gateway 접속 및 인증 문제

초기에는 gateway 연결 실패처럼 보였으나, 실제 핵심은 bearer 인증 및 Docker 포트 게시 상태 확인이었다.

확인된 상태는 다음과 같다.

- Gateway API token은 bearer token 방식으로 설정되어 있었다.
- LBH 쪽에서는 `LBH_GATEWAY_API_KEY=<redacted>` 형태로 동일한 token을 전달해야 정상 인증된다.
- bearer 없이 `/status`를 호출하면 `401`이 발생한다.
- bearer 인증을 적용하면 `/status`는 정상 응답한다.

정상 응답 예시는 다음과 같은 형태다.

```json
{"status":"ok","logged_in":true,"current_thread":""}
```

### 3.3 Docker Desktop 포트 충돌

Docker Desktop 재시작 과정에서 다음 오류가 발생했다.

```text
ports are not available: exposing port TCP 0.0.0.0:6080 -> 127.0.0.1:0
```

원인은 Windows에서 `6080` 포트가 excluded port range에 포함되어 있었기 때문이다. 이 포트는 Docker가 호스트에 bind할 수 없으므로 compose start가 실패했다.

조치 사항은 다음과 같다.

- CatGPT Gateway API 포트 `8000`은 유지했다.
- noVNC 포트만 `6080:6080`에서 `16080:6080`으로 변경했다.
- 변경 대상은 외부 저장소 `C:\developer\CatGPT-Gateway\docker-compose.yml`이었다.

현재 접근 경로는 다음과 같다.

- API: `http://localhost:8000`
- noVNC: `http://localhost:16080`

### 3.4 Preflight 구현

`lbh preflight`는 다음 항목을 확인하도록 구현되었다.

- 대상 경로가 git 저장소인지 확인
- LBH checkout 경로 확인
- Docker daemon 응답 확인
- `.lbh` 존재 여부 확인
- 인덱스 존재 여부 확인
- `LBH_GATEWAY_API_KEY` 환경변수 확인
- Gateway `/status` bearer 인증 확인

현재 preflight는 gateway가 정상 작동하는지 확인하는 단계까지는 실패 원인을 상당히 결정적으로 분류할 수 있다.

### 3.5 Run 통합 명령 구현

`lbh run`은 사용자가 매번 `preflight`, `init`, `index`, `gateway-run`을 수동으로 조합하지 않도록 만든 통합 명령이다.

현재 흐름은 다음과 같다.

1. `preflight` 실행
2. `.lbh`가 없으면 `init` 실행
3. 인덱스가 없거나 갱신 필요하면 `index` 실행
4. `preflight` 재실행
5. `gateway-run` 실행
6. 결과 상태만 요약 반환

중요한 설계 판단은 `preflight`와 `gateway-run`을 합치지 않았다는 점이다. 두 명령은 기술적으로 분리되어 있어야 한다. 대신 `run`이 이 둘을 순차 호출하는 orchestration layer 역할을 맡는다.

### 3.6 Broad 판정 비활성화

기존 broad request 판정은 아직 실험 수준이며, 실제 요청을 과도하게 plan-ready 상태로 보낼 위험이 있었다. 이에 따라 broad 판정 기능은 기본적으로 비활성화했다.

현재 기본 설정은 다음과 같다.

```toml
[experimental]
enable_broad_request_planning = false
```

이 설정에서는 broad로 보일 수 있는 요청도 기본적으로 small request처럼 처리될 가능성이 높다. 나중에 품질이 충분히 확보되면 experimental flag를 통해 다시 활성화할 수 있다.

## 4. 검증 이력

### 4.1 커밋 및 푸시

현재 주요 변경은 다음 커밋으로 반영 및 푸시되었다.

```text
6a3cec3 Add preflight and run orchestration
```

브랜치는 다음과 같다.

```text
codex/temp-refactor-20260611
```

### 4.2 테스트 결과

커밋 전 주요 테스트는 통과했다.

```text
pytest tests/test_request_classification.py tests/test_catgpt_gateway_transport.py tests/test_run_command.py tests/test_preflight.py -q
25 passed
```

ChatGPT가 생성한 잘못된 패치를 되돌린 뒤에도 핵심 테스트는 통과했다.

```text
pytest tests/test_run_command.py tests/test_preflight.py tests/test_catgpt_gateway_transport.py -q
15 passed
```

### 4.3 Run 검증

`--skip-apply`를 사용한 run 검증에서 기존 기준의 `patch_ready` 상태가 확인되었다.

명령의 성격은 다음과 같다.

- `--skip-apply`는 실제 패치를 적용하지 않는다.
- ChatGPT 응답, 패치 추출, 검증, 세션 생성까지 확인한다.
- 적용 전 후보 패치가 준비되는지 검증하는 용도다.

이후 `--skip-apply` 없이 실제 패치를 요청했으나, ChatGPT가 잘못된 패치를 생성했다.

## 5. 실패 사례 분석

### 5.1 발생한 실패

ChatGPT가 `src/lbh/run_command.py`를 리팩터링하면서 다음 문제가 발생했다.

- `_run_init` 정의 삭제
- `_run_index` 정의 삭제
- 그러나 `run_request` 내부 호출은 유지

결과적으로 테스트 실행 시 `NameError`가 발생했다.

### 5.2 기존 validator가 놓친 이유

기존 validator는 주로 다음을 확인한다.

- 패치 형식이 유효한지
- 대상 파일 경로가 안전한지
- patch apply가 가능한지
- 응답이 기대 형식으로 파싱되는지

하지만 이번 문제는 patch apply 관점에서는 유효했다. 파일은 정상적으로 수정되었고, 문법 오류가 즉시 발생하는 형태도 아니었다. 정의 누락은 실제 코드 경로 또는 정적 분석을 통해서만 드러나는 의미적 결함이었다.

따라서 기존 validator만으로는 다음 유형의 오류를 안정적으로 잡기 어렵다.

- 호출되는 함수 정의 삭제
- import 누락
- 공개 API 시그니처 변경
- 테스트 대상 경로의 런타임 NameError
- CLI 엔트리포인트 동작 파괴
- 기존 mock/test contract 파괴

## 6. 핵심 원인

문제의 본질은 "ChatGPT가 나쁜 패치를 만들었다"가 아니라 "나쁜 패치가 로컬 품질 게이트를 통과할 수 있었다"는 점이다.

LLM 패치 생성은 확률적이다. 모델 버전이나 세션 상태에 따라 품질이 흔들릴 수 있고, 같은 요청에서도 다른 결과가 나올 수 있다. 따라서 모델 성능이 회복되더라도 오류 가능성은 0이 되지 않는다.

현 시스템의 취약점은 다음과 같다.

- validator가 기계적 patch 검증에 치우쳐 있다.
- 변경 파일에 대응하는 테스트 자동 선택이 없다.
- CLI smoke check가 patch promotion gate에 충분히 통합되어 있지 않다.
- ChatGPT가 직접 파일 시스템과 테스트 결과를 관찰하지 못한다.
- CatGPT Gateway 방식에서는 Codex용 `.vibe` 문서를 ChatGPT가 직접 읽는 구조가 아니다.

## 7. 목표 구조

개선 방향은 Codex, LBH, ChatGPT, validator의 책임을 명확히 나누는 것이다. Codex는 긴 스킬 문서를 해석하며 판단하지 않고, 얇은 실행자(thin operator)로서 `lbh run`을 호출한다. LBH는 preflight, init/index, context projection, candidate extraction, validation, repair loop를 담당한다. ChatGPT는 patch를 작성하거나 리뷰 피드백을 생성하지만, 최종 승인은 로컬 validator가 맡는다.

권장 실행 흐름은 다음과 같다.

```text
[Codex thin skill]
  |
  |  python -m lbh.cli run "<request>" --target <repo> --max-rounds 20
  v
[LBH Run Orchestrator]
  - preflight
  - init/index if needed
  - gateway status/auth
  - session creation
  |
  v
[Context Projector]
  - rank files
  - repo map
  - read-before-modify snippets
  - architecture capsules
  - command contracts
  - failure cases
  - test hints
  |
  v
[ChatGPT Writer via CatGPT Gateway]
  - lbh-tool READ/GREP/FIND_SYMBOL as needed
  - final hashline patch or diff
  |
  v
[Candidate Extractor]
  - candidate_NNN.diff
  - validation metadata
  |
  v
[Promotion Gate]
  - protocol/format validation
  - path/security validation
  - read-before-modify validation
  - git apply --check
  - materialized sandbox validation
  - static undefined-name/symbol check
  - targeted tests
  - CLI smoke
  |
  v
[patch.diff promote]
  |
  v
[apply or patch_ready]
```

이 구조에서 `patch_ready`는 단순히 "git apply 가능한 diff"를 뜻해서는 안 된다. 앞으로 `patch_ready`는 "로컬 semantic gate와 targeted tests를 통과한 patch"를 뜻해야 한다. 이 정의가 바뀌지 않으면 `_run_init`, `_run_index` 삭제 같은 실패가 다시 발생할 수 있다.

세부 상태 전이는 다음처럼 고정하는 것이 적절하다.

```text
response_00N.md
  -> candidate_NNN.diff extracted
  -> protocol_validation
  -> diff_validation
  -> git_apply_check_on_active_tree_or_sandbox_probe
  -> sandbox_prepare
  -> sandbox_apply
  -> static_checks
  -> targeted_tests
  -> cli_smoke
  -> promote_to_patch_diff
  -> patch_ready or applied
```

문서와 코드에 고정해야 할 invariant는 다음과 같다.

```text
Invariant 1:
candidate_NNN.diff is never a ready artifact.

Invariant 2:
patch.diff may be written only by PromotionGate after all configured gates pass.

Invariant 3:
patch_ready may be returned only when patch.diff exists and its manifest contains a passing promotion result.

Invariant 4:
A failed candidate must never overwrite patch.diff.

Invariant 5:
Every repair response is treated as a new full candidate against the original session base, not as an incremental patch on top of a failed candidate.
```

## 8. 해결 방향

### 8.1 Promotion Gate 보강

가장 먼저 보강해야 할 지점은 candidate promotion gate다. 현재처럼 diff 형식과 `git apply --check` 중심으로 OK를 주면 의미적으로 깨진 patch를 막기 어렵다.

권장 validator 계층은 다음과 같다.

- Patch structural validation: diff 형식, 경로, apply 가능 여부 확인
- Path/security validation: 대상 경로와 작업 범위 확인
- Read-before-modify validation: 수정 대상 파일을 충분히 읽었는지 확인
- Materialized sandbox validation: 실제 작업 트리와 분리된 공간에서 patch를 적용해 검증
- Static undefined-name/symbol check: 삭제된 함수, 클래스, import가 계속 참조되는지 확인
- Targeted test validation: 변경 파일에 대응하는 테스트 자동 실행
- CLI smoke validation: 주요 명령의 `--help`, dry-run, preflight 계열 확인

이번 `_run_init`, `_run_index` 삭제 문제는 최소한 static undefined-name/symbol check 또는 targeted test validation에서 잡혔어야 한다. `compileall`은 필요한 기본 방어선이지만, 이번 사례의 주 방어선은 아니다.

실패 상태도 명시적으로 나누어야 한다.

```text
candidate_rejected_protocol
candidate_rejected_diff
candidate_rejected_apply_check
promotion_failed_sandbox_prepare
promotion_failed_sandbox_apply
promotion_failed_static
promotion_failed_tests
promotion_failed_cli_smoke
patch_ready
applied
blocked
max_rounds_exceeded
```

내부 명명도 중요하다. `candidate_ok` 같은 이름은 promote 가능 상태처럼 읽히므로 새 구조에서는 피해야 한다. 후보가 protocol, diff, apply-check 수준만 통과한 상태라면 `candidate_structural_ok`에 가깝고, `patch.diff`가 작성된 뒤에야 `promoted` 상태다.

### 8.2 테스트 자동 선택

테스트 파일 생성 자체를 validator가 임의로 수행하는 것은 위험하다. validator의 기본 역할은 합격/불합격 판정이어야 한다. 다만 테스트 선택과 실행은 validator가 맡을 수 있다.

권장 방식은 다음과 같다.

- `test_map.json`에 변경 파일과 테스트 파일의 대응 관계를 기록한다.
- 변경 파일 목록을 patch에서 추출한다.
- 대응 테스트를 자동 선택한다.
- 선택된 테스트가 없으면 기본 smoke test를 실행한다.
- 실패하면 patch promotion, apply, `patch_ready`를 중단한다.

초기 매핑은 다음 정도로 시작할 수 있다.

```json
{
  "src/lbh/run_command.py": [
    "tests/test_run_command.py",
    "tests/test_preflight.py"
  ],
  "src/lbh/preflight.py": [
    "tests/test_preflight.py",
    "tests/test_run_command.py"
  ],
  "src/lbh/core/request_classification.py": [
    "tests/test_request_classification.py",
    "tests/test_catgpt_gateway_transport.py"
  ]
}
```

CLI smoke는 최소한 다음 명령을 대상으로 삼는 것이 적절하다.

```text
python -m lbh.cli run --help
python -m lbh.cli preflight --help
python -m lbh.cli apply --help
```

`test_map.json`은 절대 진실이 아니라 strong hint로 취급해야 한다. 수동 map은 additive여야 하며, naming fallback이나 import graph fallback에서 발견된 테스트를 버리면 안 된다.

권장 selector 순서는 다음과 같다.

```text
1. manual test_map.json
2. naming fallback
   src/lbh/run_command.py -> tests/test_run_command.py
   src/lbh/foo/bar.py -> tests/test_bar.py, tests/test_foo_bar.py
3. import graph fallback
4. historical failure fallback
5. core smoke fallback
   tests/test_run_command.py
   tests/test_preflight.py
   tests/test_catgpt_gateway_transport.py
```

또한 `lbh index` 또는 `lbh doctor`에서 test map staleness를 warning으로 드러내야 한다. mapped test path가 없거나 mapped source path가 없으면 validation summary에 기록하고, 변경 파일에 선택된 테스트가 하나도 없으면 core smoke fallback을 강제해야 한다.

### 8.3 Sandbox Validation

semantic gate는 실제 작업 트리를 오염시키면 안 된다. 따라서 `git apply`, static check, targeted tests, CLI smoke는 격리된 sandbox에서 실행해야 한다.

권장 sandbox 전략은 두 가지다.

```text
Mode A: clean git repo
  - git worktree add --detach <sandbox> <base_commit>
  - candidate apply
  - checks run

Mode B: dirty working tree or untracked context involved
  - filesystem snapshot of current working tree
  - exclude .git, .lbh/sessions, build/cache/venv artifacts
  - candidate apply in snapshot
  - checks run with same Python interpreter / env
```

Phase 1에서 dirty tree snapshot 구현이 부담스럽다면 fail-closed 정책도 가능하다. 이 경우 dirty tree에서는 auto-apply와 promotion을 막거나, `--allow-dirty-sandbox` 같은 explicit flag를 요구해야 한다. 장기적으로는 사용성을 위해 copy snapshot sandbox가 더 실용적이다.

### 8.4 Context Projection 강화

ChatGPT가 전체 저장소를 직접 읽는 구조가 아니므로, LBH가 필요한 구조 정보를 작게 투사해야 한다. 전체 문서를 prompt에 넣는 방식은 토큰 비용이 크고 중요한 정보를 묻히게 만든다.

projection source는 다음 파일들로 시작하는 것이 적절하다.

- `architecture_capsules.json`: 모듈별 책임과 경계를 짧게 기록한다.
- `command_contracts.json`: 명령별 책임과 변경 금지 계약을 기록한다.
- `failure_cases.md`: 과거 실패 사례와 재발 방지 규칙을 기록한다.
- `test_map.json`: 변경 파일과 실행할 테스트의 대응 관계를 기록한다.

첫 번째 failure case로는 `_run_init`, `_run_index` 삭제 사례를 넣는 것이 좋다. prompt에는 전체 문서가 아니라 변경 후보 파일과 관련된 capsule, contract, failure case만 포함해야 한다.

### 8.5 Reviewer 도입

Reviewer는 유용하지만 1차 방어선이 되어서는 안 된다. Reviewer도 LLM이므로 동일한 확률적 실패 가능성을 가진다. 적절한 위치는 deterministic validator 이후 또는 실패 피드백 생성 단계다.

권장 reviewer loop는 다음과 같다.

1. Writer ChatGPT가 patch 후보 생성
2. Local validator 실행
3. 실패 시 실패 로그를 정규화
4. Reviewer ChatGPT가 patch와 실패 로그를 검토
5. Reviewer가 writer에게 수정 지시 생성
6. Writer가 재패치
7. Validator가 다시 판정

Reviewer 출력은 자유문이 아니라 writer에게 전달 가능한 구조화된 feedback이어야 한다.

```json
{
  "verdict": "revise",
  "blocking_issues": [
    {
      "file": "src/lbh/run_command.py",
      "issue": "Function _run_init is referenced but no longer defined.",
      "required_change": "Restore the helper or replace all call sites with equivalent logic."
    }
  ],
  "tests_to_run": [
    "tests/test_run_command.py"
  ]
}
```

repair loop에서는 모든 repaired response를 원래 session base에 대한 완전한 새 candidate로 다루어야 한다. 이전 실패 candidate 위에 incremental patch를 쌓으면 재현성이 깨지고 validator 결과를 신뢰하기 어렵다.

session manifest에는 최소한 다음 필드가 필요하다.

```json
{
  "base_commit": "...",
  "base_dirty": false,
  "candidate_base": "session_original",
  "latest_candidate": "candidates/candidate_003.diff",
  "last_failure_summary": {
    "failed_check": "targeted_tests",
    "exact_stop_reason": "pytest tests/test_run_command.py failed with NameError: _run_init is not defined",
    "failed_artifact": "promotion/candidate_003/tests.log"
  },
  "repair_round": 3,
  "max_rounds": 20
}
```

repair prompt에도 다음 제약을 넣어야 한다.

```text
- Do not produce an incremental patch against the previous failed candidate.
- Produce a complete replacement candidate against the original session repository state.
- Preserve all previously valid hunks unless they directly cause the reported failure.
- Fix only the failed gate.
```

## 9. `.vibe` 구조에 대한 적용 방향

외부에서 제안된 Vibe Kit 구조는 Codex 같은 코딩 에이전트가 직접 읽고 실행할 수 있는 로컬 환경을 전제로 한다. 그러나 이 프로젝트는 CatGPT Gateway를 통해 ChatGPT 웹 세션을 조작한다. 즉, ChatGPT는 로컬 파일을 직접 읽거나 명령을 직접 실행하지 못한다.

따라서 `.vibe`는 ChatGPT가 직접 소비하는 디렉터리가 아니라, LBH가 prompt projection과 validation을 구성하기 위한 로컬 소스여야 한다. 처음부터 큰 구조를 만들 필요는 없다. 우선은 validator와 projection에 직접 쓰이는 파일만 둔다.

권장 초기 구조는 다음과 같다.

```text
.vibe/
  knowledge/
    architecture_capsules.json
    command_contracts.json
    failure_cases.md
    test_map.json
  validation/
    smoke_checks.json
  review/
    reviewer_checklist.md
    feedback_schema.json
```

핵심은 `.vibe`를 문서 보관소로 끝내지 않는 것이다. LBH가 여기서 필요한 정보만 뽑아 ChatGPT에게 짧은 prompt projection으로 전달하고, 로컬 검증기는 `.vibe/knowledge/test_map.json`과 `.vibe/validation/smoke_checks.json`을 사용해 결정적으로 판정해야 한다.

## 10. 구현 우선순위와 결론

Phase 1은 promotion gate 보강이다. 코드 구조상으로는 먼저 candidate와 `patch.diff`의 경계를 고정해야 한다. 그래야 targeted tests나 CLI smoke가 실패했을 때 `patch.diff`가 생성되지 않는다.

Phase 1의 구현 순서는 다음과 같이 잡는 것이 안전하다.

```text
Phase 1A: Promotion boundary
  - candidate와 patch.diff 경계 고정
  - patch_ready 의미 재정의
  - run JSON 필드 확장

Phase 1B: Targeted test selector
  - test_map.json
  - naming fallback
  - core smoke fallback
  - run_command/preflight mapping 우선

Phase 1C: Sandbox gate
  - clean snapshot 또는 worktree
  - candidate apply
  - targeted tests
  - CLI smoke

Phase 1D: Static checks
  - compileall
  - ruff F821 또는 pyflakes
  - 결과를 normalized failure로 변환
```

이 단계가 끝나야 `patch_ready`를 "semantic gate를 통과한 patch"로 부를 수 있다.

`lbh run` JSON 출력은 Codex가 artifact를 열지 않아도 판단할 수 있을 정도로 충분히 구조화되어야 한다. 최소 필드는 다음과 같다.

```json
{
  "ok": false,
  "phase": "promotion_gate",
  "status": "promotion_failed_tests",
  "exact_stop_reason": "targeted test failed: tests/test_run_command.py::test_run_auto_inits_and_indexes_before_gateway",
  "failed_check": "targeted_tests",
  "target_repo": "C:/developer/example",
  "session_path": "C:/developer/example/.lbh/sessions/20260613-...",
  "response_file": "response_003.md",
  "candidate_path": "candidates/candidate_003.diff",
  "promoted_patch_path": null,
  "patch_path": null,
  "base_commit": "abc1234",
  "working_tree_dirty": false,
  "validation_summary": {
    "protocol": "passed",
    "diff": "passed",
    "sandbox_apply": "passed",
    "static": "passed",
    "targeted_tests": "failed",
    "cli_smoke": "not_run"
  },
  "checks": [
    {
      "name": "pytest",
      "kind": "targeted_tests",
      "status": "failed",
      "command": "python -m pytest -q tests/test_run_command.py tests/test_preflight.py",
      "artifact": "promotion/candidate_003/targeted_tests.log"
    }
  ],
  "next_safe_command": "Inspect promotion/candidate_003/targeted_tests.log or rerun lbh run after repair."
}
```

Phase 2는 ChatGPT의 구조 이해를 강화하는 것이다. `architecture_capsules.json`, `command_contracts.json`, `failure_cases.md`를 추가하고, 변경 후보 파일과 관련된 정보만 prompt에 투사한다.

Phase 3은 Codex token 추가 절감이다. installed skill entrypoint를 더 줄이고, `docs/skills/gpt-patch.md`는 human docs로 남기며, routine run에서는 Codex가 긴 문서를 읽지 않게 한다. `lbh run` JSON 출력에는 `exact_stop_reason`, `artifact_paths`, `next_safe_command`, `validation_summary`를 포함해 Codex가 세션 artifact를 열지 않아도 다음 행동을 알 수 있게 한다.

Phase 4는 broad work scaffolding이다. broad flag는 계속 기본 off로 두고, planner output schema만 먼저 설계한다. broad request는 patch 생성이 아니라 subtask graph 생성까지만 허용하며, 각 subtask는 기존 small request pipeline을 그대로 타게 한다.

현재 가장 위험한 빈틈은 candidate promotion gate가 의미 검증을 충분히 포함하지 않는다는 점이다. 따라서 다음 작업의 우선순위는 reviewer 도입이 아니라 semantic gate, targeted tests, CLI smoke를 patch promotion 전에 넣는 것이다. 그 이후에 reviewer loop를 추가해야 재시도 품질을 올리면서도 잘못된 patch promotion을 막을 수 있다.
