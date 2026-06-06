# Development Guide for Future Coders

## Automation Checklist

- [ ] If you change `lbh automate`, update both runner tests and CLI-level tests.
- [ ] Keep browser transport logic out of repo search, tool execution, and patch validation code.
- [ ] Resume behavior must preserve the one-session / one-chat mapping.
- [ ] Candidate validation and promotion rules must stay identical between manual `lbh respond` and automated runs.

이 문서는 이후 LBH 코드를 확장할 개발자를 위한 지시사항입니다.

## 개발 원칙

1. CLI에 비즈니스 로직을 넣지 마세요.
2. 파일 시스템 접근은 `core/paths.py`, `core/fs.py`를 거치세요.
3. 모델 응답 파싱은 `protocol/parser.py`에만 두세요.
4. diff 적용은 반드시 `patch/diff.py` 검증을 통과하게 하세요.
5. transport는 교체 가능해야 하므로 index/search/patch 로직을 넣지 마세요.
6. 새 기능을 추가하면 docs와 tests를 같이 업데이트하세요.

## 모듈별 책임

### `core/config.py`

- config 생성/로드
- 기본값 정의
- TOML 호환 파서/라이터

새 config 값을 추가하면 다음도 업데이트하세요.

- `DEFAULT_CONFIG_TEXT`
- `docs/CONFIG.md`
- 관련 테스트

### `indexer/extractors.py`

현재는 실행 가능성을 위해 Python AST와 regex extractor를 사용합니다.
Tree-sitter를 붙일 경우 이 파일에 `TreeSitterExtractor`를 추가하고, 기존 fallback을 유지하세요.

권장 interface:

```python
class Extractor:
    def extract(self, path: str, text: str) -> ExtractionResult: ...
```

### `indexer/store.py`

SQLite schema를 관리합니다.
schema 변경 시 `SCHEMA_VERSION`을 올리고 migration을 추가하세요.

### `search/ranker.py`

검색 점수는 deterministic해야 합니다.
추후 BM25, PageRank, embedding reranker를 추가할 수 있지만, 기본 fallback은 모델 없이 동작해야 합니다.

### `context/packer.py`

모델에게 전달되는 prompt를 만듭니다.
여기서 중요한 것은 “많이 넣기”가 아니라 “추적 가능한 근거를 넣기”입니다.
프로토콜이나 출력 형식 관련 변경에서는 `context/packer.py`를 반드시 함께 확인하세요.

반드시 포함할 것:

- user request
- hard rules
- allowed tools
- relevant files
- repo map
- snippets

### `protocol/parser.py`

모델 출력은 항상 불안정할 수 있습니다.
parser는 최대한 관대하게 읽되, patch 적용 단계에서는 엄격해야 합니다.
하지만 parser만 보고 끝내지 마세요. protocol 변경이면 prompt, CLI, docs, tests도 같이 확인해야 합니다.

지원해야 하는 형식:

- `lbh-tool` fenced JSON block
- legacy `[READ: path]`
- sentinel diff
- `lbh-diff` fenced block
- `diff` fenced block

### `protocol/tools.py`

tool 실행 전 모든 path를 검증하세요.
READ는 session manifest에 `read_files`를 기록해야 합니다.

### `patch/diff.py`

모델이 본 적 없는 파일을 수정하지 못하게 하는 핵심 안전장치입니다.
여기 테스트를 가장 두껍게 유지하세요.

## 테스트 실행

```bash
python -m pip install -e '.[dev]'
python -m pytest
```

## smoke test

```bash
python scripts/create_demo_repo.py /tmp/lbh-demo
cd /tmp/lbh-demo
lbh init
lbh index
lbh search "결제 후 알림이 안 가요"
lbh ask "결제 후 알림이 안 가요"
```

## 패키징

```bash
scripts/package.sh
```

생성물:

```text
dist/lbh-systematic.zip
```

## 새 기능 추가 체크리스트

- [ ] CLI 옵션 추가 시 `docs/COMMANDS.md` 업데이트
- [ ] config 추가 시 `docs/CONFIG.md` 업데이트
- [ ] 보안 관련 변경 시 `docs/SECURITY.md` 업데이트
- [ ] protocol 변경 시 `docs/PROTOCOL.md` 업데이트
- [ ] protocol/output-format 변경 시 `src/lbh/context/packer.py`, parser, CLI, tests, docs를 함께 확인
- [ ] protocol/output-format 변경 시 “경로 추측 READ 금지”와 “순수 unified diff 출력” 규칙을 prompt/tests/docs에 반영
- [ ] Markdown fence 충돌을 피하려고 sentinel을 써도, sentinel 내부 diff syntax는 순수 unified diff로 유지
- [ ] final diff transport 규칙 변경 시 parser extraction test와 prompt regression test를 함께 추가
- [ ] Markdown UI를 통한 diff 전달에서는 code-fenced transport wrapper를 반드시 고려
- [ ] session/manifest 변경 시 `src/lbh/session/manager.py` 확인
- [ ] unit test 추가
- [ ] demo repo smoke test 통과
