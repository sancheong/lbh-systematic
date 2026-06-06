# CLI Commands

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
patch.diff
```

가 생성됩니다.

## `lbh read`

수동으로 파일을 읽어 모델에게 줄 수 있는 형식으로 출력합니다.

```bash
lbh read src/payments/checkout.ts
lbh read src/payments/checkout.ts --range 1:120
```

## `lbh apply`

diff를 검증하거나 적용합니다.

```bash
lbh apply patch.diff --check
lbh apply patch.diff --session .lbh/sessions/<session-id> --check
lbh apply patch.diff --session .lbh/sessions/<session-id> --yes
```

기본적으로 `--yes` 없이는 실제 적용하지 않습니다.

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
