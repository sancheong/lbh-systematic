# Indexing Design

이 문서는 설계서의 “코덱스 토큰을 아끼는 로컬 캐싱 및 검색 엔진”을 코드에서 어떻게 구현했는지 설명합니다.

## 핵심 목표

LBH 인덱서는 모델을 호출하지 않고 로컬에서 다음 질문에 답해야 합니다.

```text
사용자 요청과 관련 있는 파일은 무엇인가?
그 파일에는 어떤 함수/클래스/import가 있는가?
어떤 파일을 먼저 모델에게 보여줘야 하는가?
```

즉, 인덱서는 “AI 추론”이 아니라 “로컬 코드 지도 생성기”입니다.

## 관련 코드

```text
src/lbh/indexer/scanner.py      # 대상 파일 목록 수집
src/lbh/indexer/extractors.py   # lightweight symbol/import 추출
src/lbh/indexer/store.py        # SQLite 저장/조회
src/lbh/indexer/builder.py      # 전체 인덱싱 orchestration
src/lbh/core/models.py          # FileRecord, SymbolRecord 등 데이터 모델
```

## 실행 흐름

`lbh index`는 내부적으로 다음 순서로 동작합니다.

```text
1. Config.load(repo)
2. FileScanner.scan()
3. LightweightExtractor.extract(path, text)
4. RepoIndexer가 import resolve 수행
5. IndexStore.reset()
6. files/symbols/imports/edges/chunks 테이블 저장
7. meta.updated_at 기록
```

## 캐시 위치

```text
.lbh/index/files.sqlite
```

SQLite를 쓰는 이유는 다음과 같습니다.

- 별도 서버가 필요 없음
- 파일/심볼/import/edge를 안정적으로 저장 가능
- 대형 repo에서도 단순 JSON보다 검색과 확장이 쉬움
- 나중에 FTS5, 증분 인덱싱, PageRank cache를 붙이기 쉬움

## 현재 추출 방식

현재 버전은 설치 안정성을 위해 Tree-sitter를 필수 의존성으로 넣지 않았습니다.
대신 `LightweightExtractor`가 Python AST와 정규식을 사용합니다.

추출 대상:

- Python `def`, `class`, `import`, `from ... import ...`
- TypeScript/JavaScript `function`, `class`, `const fn =`, `import`, `require`
- Go/Rust의 기본 함수/type/use 패턴
- 파일 layer: test/config/source/generated 추정

## Tree-sitter를 붙이는 방법

향후 Tree-sitter를 붙일 때는 기존 extractor interface를 유지하세요.

권장 구조:

```python
class TreeSitterExtractor:
    def extract(self, rel_path: str, text: str) -> ExtractionResult:
        ...
```

그리고 `RepoIndexer`에서 다음처럼 선택합니다.

```text
parser = auto
  -> tree-sitter 가능하면 TreeSitterExtractor
  -> 실패하면 LightweightExtractor fallback
```

중요한 원칙:

- Tree-sitter 실패가 전체 인덱싱 실패로 이어지면 안 됩니다.
- generated/binary/secret 파일은 파서 이전 단계에서 제외해야 합니다.
- extractor 변경 시 `docs/INDEXING.md`, `tests/`를 같이 업데이트하세요.

## 증분 인덱싱 로드맵

현재는 rebuild 방식입니다. 이후에는 다음 순서로 확장하세요.

```text
1. files.sha256 비교
2. 변경 파일만 재추출
3. 해당 파일의 symbols/imports/edges 삭제 후 재삽입
4. 주변 graph bonus cache 무효화
5. file watcher로 자동 갱신
```
