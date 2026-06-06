# Roadmap

## 현재 구현됨

- SQLite local index
- lightweight symbol/import extraction
- deterministic search/ranking
- session manifest
- lazy READ/GREP/FIND_SYMBOL/LIST_DIR/DEP_GRAPH/TEST_HINTS
- diff extraction and validation
- git apply check/apply
- manual transport workflow

## 다음 단계

### 1. Tree-sitter adapter

현재 regex/Python AST extractor를 Tree-sitter 기반 extractor로 확장합니다.
목표:

- 더 정확한 class/function/method 추출
- line range 정확도 향상
- call reference 추출

### 2. Personalized PageRank

현재 import graph bonus를 더 정교하게 바꿉니다.

- seed files: query hit 상위 파일
- graph: import/test adjacency
- output: score blending

### 3. Test runner

patch 적용 후 관련 test 자동 실행.

- package manager 감지
- modified file to test file 매핑
- 실패 로그 압축
- 모델 repair round prompt 생성

### 4. Temp worktree apply

현재는 current worktree 적용입니다.
향후:

- `git worktree add .lbh/worktrees/<session>`
- patch dry-run
- test run
- 성공 시 current branch로 cherry-pick 또는 patch apply

### 5. Transport adapters

현재는 manual paste만 제공합니다.
향후 허용된 방식으로:

- official API adapter
- local model adapter
- stdin/stdout adapter
- internal gateway adapter

## 하지 않을 것

- 사용량 제한 우회 자동화
- 허용되지 않은 웹 UI 스크레이핑
- 비밀 파일 무차별 전송
