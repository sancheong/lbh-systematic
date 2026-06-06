# Security Model

LBH는 로컬 코드를 외부 모델에게 전달할 수 있는 도구이므로 안전장치가 필요합니다.

## 1. Path sandbox

모든 path는 다음 조건을 만족해야 합니다.

- repo root 기준 상대 경로
- 절대 경로 금지
- `../` traversal 금지
- symlink resolve 후 repo root 내부
- `.lbh/config.toml`의 exclude 패턴 미해당

관련 코드:

```text
src/lbh/core/paths.py
```

## 2. Secret redaction

파일을 모델에게 전달하기 전 기본 secret pattern을 마스킹합니다.

예:

- `OPENAI_API_KEY=...`
- `AWS_SECRET_ACCESS_KEY=...`
- `DATABASE_URL=...`
- `BEGIN RSA PRIVATE KEY`
- `ghp_...`
- `sk-...`

관련 코드:

```text
src/lbh/core/fs.py
```

## 3. 전송 금지 파일

기본 제외:

```text
.env
.env.*
*.pem
*.key
*.p12
*.crt
id_rsa
id_ed25519
secrets.*
credentials.*
node_modules/**
dist/**
build/**
coverage/**
.git/**
.lbh/**
```

## 4. diff validation

모델 diff는 바로 적용하지 않습니다.

검증 항목:

- `diff --git` header 존재
- 수정 path가 repo 내부인지
- ignored/secret 파일 수정 여부
- 세션 중 READ된 파일인지
- binary patch 여부
- `git apply --check` 통과 여부

관련 코드:

```text
src/lbh/patch/diff.py
src/lbh/patch/apply.py
```

## 5. 기본 적용 모드

`lbh apply`는 기본적으로 실제 적용하지 않습니다.

```bash
lbh apply patch.diff --check
```

실제 적용은 명시적으로 해야 합니다.

```bash
lbh apply patch.diff --yes
```

## 6. 권장 운영

- 중요한 repo에서는 clean working tree에서 실행하세요.
- patch 적용 전 `--check`를 먼저 실행하세요.
- 테스트 자동 실행 기능은 추후 붙이되, 현재는 별도 CI/test command를 직접 실행하세요.
- `.lbh/config.toml`의 exclude를 프로젝트에 맞게 강화하세요.
