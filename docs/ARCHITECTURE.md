# LBH Architecture

## 10. Automation Runtime

The thin automation runtime sits above the existing LBH layers:

```text
User / Codex
  -> Automation Runner
     -> Browser Controller (Chrome / ChatGPT)
     -> LBH Session Workflow (`ask`, `respond`, candidate validation, `apply`)
```

Responsibilities:

- `automation/runner.py`: orchestration state machine
- `automation/shell.py`: shell-command bridge to an external Chrome controller
- `workflow.py`: reusable ask/respond/apply helpers shared by CLI and automation

Important boundary:

- the browser controller sends and receives messages only
- it must not parse repo semantics, validate patches, or bypass LBH candidate promotion

LBH는 “로컬 프로젝트를 볼 수 없는 모델”에게 필요한 코드 맥락만 안전하게 전달하는 프로그램입니다.
설계서에서 말한 역할은 다음 5개 계층으로 나뉩니다.

```text
사용자 요청
  ↓
CLI / Session Manager
  ↓
Local Context Engine
  - scanner
  - parser/extractor
  - sqlite index
  - ranker
  ↓
Context Broker
  - repo map
  - evidence snippets
  - lazy loading prompt
  ↓
Model Transport
  - manual paste
  - future permitted API adapter
  ↓
Patch Engine
  - diff extraction
  - validation
  - git apply
```

## 1. CLI 계층

파일:

```text
src/lbh/cli.py
```

역할:

- 사용자의 명령을 받는다.
- 현재 repo root를 찾는다.
- config와 session을 로드한다.
- index/search/context/protocol/patch 계층을 호출한다.

CLI는 최대한 얇게 유지해야 합니다. 비즈니스 로직은 각 모듈에 있어야 합니다.

## 2. Core 계층

파일:

```text
src/lbh/core/config.py
src/lbh/core/paths.py
src/lbh/core/fs.py
src/lbh/core/models.py
```

역할:

- `.lbh/config.toml` 생성/로드
- repo root 탐지
- 경로 sandbox 검증
- 텍스트 파일 안전 읽기
- secret redaction
- 공용 dataclass 정의

## 3. Indexer 계층

파일:

```text
src/lbh/indexer/scanner.py
src/lbh/indexer/extractors.py
src/lbh/indexer/store.py
src/lbh/indexer/builder.py
```

역할:

- `git ls-files` 또는 파일 시스템 walk로 대상 파일 찾기
- Python AST 및 범용 regex 기반 symbol/import 추출
- SQLite에 files/symbols/imports/edges 저장
- FTS5가 가능한 환경에서는 FTS index 구성

설계서에서는 Tree-sitter를 권장했습니다. 이 구현은 실행 가능성을 위해 Tree-sitter를 강제하지 않고, `extractors.py`에 adapter boundary를 둡니다. 추후 Tree-sitter를 붙일 때 이 파일을 확장하면 됩니다.

## 4. Search 계층

파일:

```text
src/lbh/search/query.py
src/lbh/search/ranker.py
```

역할:

- 한국어/영어 요청을 검색 토큰으로 확장
- path/symbol/import/content preview 기반 점수 계산
- import graph 주변 파일에 보너스 부여
- layer diversity를 반영해 결제/알림/테스트/설정 같은 여러 계층을 섞어 후보화

현재 구현은 BM25 완전 구현이 아니라 deterministic scoring입니다. 하지만 구조상 BM25, PageRank, embedding reranker를 추가하기 쉽습니다.

## 5. Context 계층

파일:

```text
src/lbh/context/packer.py
```

역할:

- 검색 결과를 모델용 prompt로 포장
- repo header, relevant tree, repo map, snippets, protocol rules 포함
- token budget 대신 character budget을 사용해 실행 가능성을 높임

## 6. Protocol 계층

파일:

```text
src/lbh/protocol/parser.py
src/lbh/protocol/tools.py
```

역할:

- 모델 응답에서 `lbh-tool` JSON 블록, legacy `[READ: path]`, diff 블록 추출
- 모델이 요청한 READ/GREP/FIND_SYMBOL/LIST_DIR/DEP_GRAPH/TEST_HINTS 실행
- 읽힌 파일과 sha256을 session manifest에 기록

## 7. Patch 계층

파일:

```text
src/lbh/patch/diff.py
src/lbh/patch/apply.py
```

역할:

- diff 블록만 추출
- diff path 검증
- 읽지 않은 파일 수정 차단
- `git apply --check`
- `git apply --whitespace=fix`

## 8. Session 계층

파일:

```text
src/lbh/session/manager.py
```

역할:

- `.lbh/sessions/<session-id>` 생성
- request, initial_prompt, context append, patch, manifest 저장
- 읽힌 파일, tool call, patch 상태 기록

## 9. Transport 계층

파일:

```text
src/lbh/transport/base.py
src/lbh/transport/manual.py
```

역할:

- 모델과 통신하는 방식을 교체 가능하게 분리
- 현재는 manual paste workflow만 제공
- 추후 허용된 API, 사내 gateway, 로컬 모델 등을 연결 가능

중요: transport에는 index/search/patch 로직을 넣지 않습니다.

## 데이터 흐름

```text
lbh ask "결제 후 알림 안 감"
  → SearchRanker가 관련 파일 후보 생성
  → ContextPacker가 initial_prompt.md 생성
  → 사용자가 모델에 붙여넣음
  → 모델이 [READ: path] 또는 lbh-tool 요청
  → lbh respond가 context_append_N.md 생성
  → 모델이 lbh-diff 출력
  → lbh respond가 patch.diff 저장
  → lbh apply가 검증 후 적용
```

## 향후 확장 포인트

- `extractors.py`: Tree-sitter parser provider 추가
- `ranker.py`: Personalized PageRank 추가
- `transport/`: 허용된 API adapter 추가
- `patch/apply.py`: temp worktree apply mode 추가
- `session/manager.py`: multi-round transcript viewer 추가
