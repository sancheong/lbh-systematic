# Configuration

LBH 설정 파일은 프로젝트별로 생성됩니다.

```text
.lbh/config.toml
```

## 기본 예시

```toml
schema = "lbh.config.v1"

[index]
include = ["**/*"]
exclude = [
  ".git/**",
  ".lbh/**",
  "node_modules/**",
  "dist/**",
  "build/**",
  "coverage/**",
  "*.lock"
]
max_file_bytes = 300000
content_preview_chars = 3000

[ranking]
path_weight = 0.25
symbol_weight = 0.25
import_weight = 0.15
content_weight = 0.25
graph_weight = 0.10

[context]
initial_file_limit = 12
snippet_lines = 80
max_prompt_chars = 60000
max_lazy_read_lines = 500
max_tool_requests_per_round = 12

[security]
redact_secrets = true
require_read_before_modify = true
allow_new_files_without_read = true
```

## include / exclude

- `include`는 인덱싱 대상 glob입니다.
- `exclude`는 제외 glob입니다.
- `.git`, `.lbh`, `node_modules`, build output은 기본 제외합니다.

## max_file_bytes

너무 큰 파일을 인덱싱하지 않기 위한 제한입니다.
대형 generated file, bundle file, snapshot file을 막기 위한 값입니다.

## content_preview_chars

검색용 content preview로 저장할 문자 수입니다.
전체 파일 본문을 DB에 넣지 않고 앞부분만 저장합니다.

## require_read_before_modify

true일 경우, 모델이 diff로 수정하려는 파일은 반드시 해당 세션에서 READ된 파일이어야 합니다.
이 옵션은 hallucinated patch 방지에 매우 중요합니다.

## allow_new_files_without_read

새 파일은 기존 본문이 없으므로 READ 없이 생성할 수 있습니다.
보수적으로 운영하려면 false로 두고, 새 파일 생성도 별도 승인 흐름으로 처리하세요.
