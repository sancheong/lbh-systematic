# CLI Commands

## `lbh automate`

Runs the thin Chrome/ChatGPT automation runtime on top of the existing LBH session workflow.

```bash
lbh automate "fix the notification bug" --controller-command "python tools/chatgpt_controller.py"
lbh automate "fix the notification bug" --skip-apply --controller-command "python tools/chatgpt_controller.py"
lbh automate --session .lbh/sessions/<session-id> --controller-command "python tools/chatgpt_controller.py"
```

Key options:

- `--chrome-profile`: Chrome profile name. Default: `Profile 4`
- `--controller-command`: external browser controller command
- `--skip-apply`: stop after patch promotion and `git apply --check` instead of applying the patch
- `--max-retries`: browser-step retry count before blocking the session
- `--poll-seconds`, `--timeout-seconds`: response wait tuning

Automation behavior:

- starts one ChatGPT conversation per LBH session
- sends `initial_prompt.md`, then any `context_append_###.md`
- if a candidate patch fails validation, sends the generated `candidate_###.repair_prompt.md`
- promotes only validated candidates to `patch.diff`, then applies them by default
- persists runtime state under `manifest.json -> automation`

## `lbh init`

현재 프로젝트에 `.lbh/config.toml`을 생성합니다.

```bash
lbh init
lbh init --force
```

생성되는 주요 파일:

```text
.lbh/config.toml
.lbh/index/
.lbh/sessions/
```

## `lbh index`

현재 프로젝트의 파일을 스캔하고 SQLite index를 생성합니다.

```bash
lbh index
lbh index --json
```

저장 위치:

```text
.lbh/index/files.sqlite
.lbh/index/meta.json
```

## `lbh search`

사용자 요청과 관련 있는 파일 후보를 출력합니다.

```bash
lbh search "결제 후 알림이 안 가요"
lbh search "payment notification" --limit 20
```

## `lbh ask`

새 세션을 만들고 모델에게 붙여넣을 initial prompt를 생성합니다.

```bash
lbh ask "결제 후 알림이 안 가는 문제 고쳐줘"
lbh ask "로그인 후 대시보드가 비어 있음" --limit 12
```

출력:

```text
.lbh/sessions/<session-id>/initial_prompt.md
```

## `lbh respond`

모델 응답을 처리합니다.

```bash
lbh respond response.md --session .lbh/sessions/<session-id>
```

응답에 tool request가 있으면:

```text
context_append_001.md
```

응답에 diff가 있으면:

```text
candidates/candidate_001.diff
candidates/candidate_001.validation.json
candidates/candidate_001.critique.md
candidates/candidate_001.repair_prompt.md
```

가 생성됩니다.
candidate validation이 통과한 경우에만 `.lbh/sessions/<session-id>/patch.diff`로 승격됩니다.
실패하면 critique와 repair prompt 위치를 출력하고 `patch.diff`는 승격되지 않습니다.

수동 적용 단계에서는 session context를 유지해야 합니다. `--session`은 manifest의 read-before-modify 정보를 다시 사용하므로, `lbh respond`가 출력한 같은 session 경로를 넘깁니다.

```bash
lbh apply .lbh/sessions/<session-id>/patch.diff --session .lbh/sessions/<session-id> --check
lbh apply .lbh/sessions/<session-id>/patch.diff --session .lbh/sessions/<session-id> --yes
```

## `lbh read`

수동으로 파일을 읽어 모델에게 줄 수 있는 형식으로 출력합니다.

```bash
lbh read src/payments/checkout.ts
lbh read src/payments/checkout.ts --range 1:120
```

## `lbh apply`

diff를 검증하거나 적용합니다. session-backed patch는 session context와 함께 검증해야 합니다.

```bash
lbh apply .lbh/sessions/<session-id>/patch.diff --session .lbh/sessions/<session-id> --check
lbh apply .lbh/sessions/<session-id>/patch.diff --session .lbh/sessions/<session-id> --yes
```

`.lbh/sessions/<session-id>/patch.diff` 또는 `.lbh/sessions/<session-id>/candidates/candidate_001.diff`처럼 session 안에 있는 patch 경로를 넘기면 `lbh apply`가 `--session`을 자동 추론하고 `Using session context: ...`를 출력합니다. 그래도 문서와 수동 절차에서는 실수를 줄이기 위해 `--session`을 명시합니다.

기본적으로 `--yes` 없이는 실제 적용하지 않습니다. `--yes`를 `--session` 없이 사용하면 read-before-modify context가 적용되지 않는다는 경고를 출력합니다.

## `lbh status`

세션 상태를 출력합니다.

```bash
lbh status --session .lbh/sessions/<session-id>
```

## `lbh doctor`

현재 프로젝트의 LBH 상태를 점검합니다.

```bash
lbh doctor
```

확인 항목:

- repo root 탐지
- `.lbh/config.toml` 존재
- index DB 존재
- git 사용 가능 여부
- SQLite 상태

## `lbh gateway-run`

`CatGPT-Gateway` thread API를 사용해 수동 prompt/response 교환을 자동화합니다.

```bash
lbh gateway-run "결제 실패 시 알림이 누락되는 문제를 수정"
lbh gateway-run "payment notification bug" --base-url http://localhost:8000 --api-key dummy123 --skip-apply
```

Gateway status preflight must match the actual gateway authentication policy. If your deployment requires bearer auth on `GET /status`, call it with `Authorization: Bearer dummy123` or the token passed with `--api-key`; only omit auth when the gateway really exposes `/status` unauthenticated.

동작:

- `lbh ask`와 같은 방식으로 session과 `initial_prompt.md`를 생성합니다.
- `POST /thread/new`로 첫 prompt를 전송합니다.
- 응답을 `response_001.md`로 저장한 뒤 `lbh respond`와 같은 파이프라인으로 처리합니다.
- `context_append_###.md` 또는 repair prompt가 생기면 같은 `thread_id`로 다시 보냅니다.
- `patch.diff`가 준비되면 기본적으로 `git apply --check` 후 patch를 적용합니다.
- `--skip-apply`를 주면 적용하지 않고 patch-ready 상태에서 중단합니다.
