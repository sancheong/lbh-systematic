# Coding Guide

이 문서는 이후 LBH 코드를 이어서 작성할 때 지켜야 할 지시사항입니다.

## 가장 중요한 원칙

```text
CLI는 얇게 유지한다.
index/search/context/protocol/patch/session 책임을 섞지 않는다.
```

## 모듈별 수정 규칙

### core

- 경로 검증은 `core/paths.py`에서 처리합니다.
- 파일 읽기, secret redaction, line formatting은 `core/fs.py`를 사용합니다.
- 새 데이터 구조는 `core/models.py`에 dataclass로 추가합니다.

### indexer

- 파일 스캔 정책은 `scanner.py`에 둡니다.
- symbol/import 추출은 `extractors.py`에 둡니다.
- SQLite schema 변경은 `store.py`와 docs를 같이 수정합니다.
- 인덱싱 orchestration은 `builder.py`에 둡니다.

### search

- query expansion은 `query.py`에서만 합니다.
- ranking score 변경은 `ranker.py`에 두고 테스트를 추가합니다.

### context

- 모델 prompt 형식은 `context/packer.py`에 둡니다.
- 모델에게 주는 hard rule을 바꾸면 `docs/CHATGPT_INSTRUCTIONS.md`도 수정합니다.

### protocol

- tool request parsing은 `parser.py`에만 둡니다.
- READ/GREP/FIND_SYMBOL 실행은 `tools.py`에 둡니다.
- 새 tool op를 추가하면 `docs/PROTOCOL.md`와 test를 같이 업데이트합니다.

### patch

- diff 추출/검증은 `patch/diff.py`에서만 합니다.
- git 명령 실행은 `patch/apply.py`에 둡니다.
- 보안 검증을 약화하는 변경은 기본값으로 넣지 마세요.

### transport

- transport는 메시지 송수신만 담당합니다.
- index/search/patch 로직을 transport에 넣지 마세요.

## 새 기능 추가 체크리스트

1. 어떤 계층의 책임인지 먼저 정한다.
2. 기존 dataclass/model을 재사용한다.
3. docs를 업데이트한다.
4. 테스트를 추가한다.
5. `scripts/smoke_test.sh`를 실행한다.
6. zip 패키징 전 `__pycache__`, `.pytest_cache`, `.lbh`를 제거한다.
