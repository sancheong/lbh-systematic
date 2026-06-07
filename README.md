# LBH: Local-Browser-Hybrid Context Broker

## Automation Runtime

LBH now includes a thin automation runtime for Chrome/ChatGPT orchestration.

- `lbh automate "<request>"` starts a fresh LBH session, opens or resumes one ChatGPT conversation through an external browser controller, and loops through `initial_prompt.md`, `context_append_###.md`, candidate critique / repair prompts, and final apply.
- `lbh automate --session <session-root>` resumes a stopped session from the persisted automation state in `manifest.json`.
- The runtime does not bypass LBH validation. ChatGPT output still flows through `lbh respond`, candidate patch validation, `patch.diff` promotion, and `lbh apply --check` / `--yes`.
- Browser automation is intentionally kept outside LBH core semantics. The runtime expects an external controller command via `--controller-command` or `LBH_BROWSER_CONTROLLER_COMMAND`.

LBH는 로컬 프로젝트와 강력한 추론 모델 사이를 연결하는 **로컬 컨텍스트 브로커**입니다.
이 패키지는 설계서의 핵심 요소인 **로컬 인덱싱**, **관련 파일 검색**, **Lazy Loading 프로토콜**, **diff-only 출력 검증**, **git apply 안전 적용**을 실행 가능한 형태로 반영합니다.

> 핵심 아이디어: 모델에게 저장소 전체를 던지지 말고, LBH가 로컬에서 코드 지도를 만든 뒤 필요한 파일만 단계적으로 제공한다.

## 현재 버전의 범위

포함됨:

- 프로젝트별 `.lbh/config.toml` 생성
- SQLite 기반 `.lbh/index/files.sqlite` 인덱스 생성
- 파일명, 심볼, import, content preview 기반 검색
- 한국어/영어 도메인 용어 확장
- 관련 파일 후보 ranking
- ChatGPT에 붙여넣을 `initial_prompt.md` 생성
- `[READ: path]`와 `lbh-tool` JSON 요청 처리
- `READ`, `GREP`, `FIND_SYMBOL`, `LIST_DIR`, `DEP_GRAPH`, `TEST_HINTS` 도구 실행
- `lbh-diff`, `diff`, sentinel diff 블록 추출
- ChatGPT diff를 candidate patch로 저장하고 검증 report/critique/repair prompt 생성
- diff 경로 검증, 읽지 않은 파일 수정 차단
- `git apply --check`와 실제 적용
- 세션별 manifest/transcript 기록
- 수동 transport 대신 `CatGPT-Gateway` thread API를 붙일 수 있는 transport adapter 경계

포함하지 않음:

- 브라우저 UI 자동화 또는 웹 UI 스크레이핑
- OpenAI/Codex 한도 우회 구현
- 실제 Tree-sitter 의존성 강제 설치

대신 `transport/` 계층과 `indexer/extractors.py`를 분리해 두었기 때문에, 이후 허용된 API나 Tree-sitter 어댑터를 붙이기 쉽도록 설계했습니다.

## 설치

```bash
cd lbh-systematic
python -m pip install -e .
```

개발 테스트까지 실행하려면:

```bash
python -m pip install -e '.[dev]'
python -m pytest
```

## 기본 사용 흐름

작업하려는 프로젝트로 이동합니다.

```bash
cd ~/projects/my-app
```

초기화합니다.

```bash
lbh init
```

인덱스를 만듭니다.

```bash
lbh index
```

모호한 버그 요청을 던집니다.

```bash
lbh ask "결제 후 알림이 안 가는 문제를 확인하고 패치해줘"
```

그러면 이런 파일이 생성됩니다.

```text
.lbh/sessions/<session-id>/initial_prompt.md
```

이 파일 내용을 모델에게 붙여넣습니다.
모델이 추가 파일을 요청하면 응답을 `response.md`로 저장한 뒤 실행합니다.

```bash
lbh respond response.md --session .lbh/sessions/<session-id>
```

LBH가 요청된 파일들을 읽어 다음 파일을 만듭니다.

```text
.lbh/sessions/<session-id>/context_append_001.md
```

이 내용을 다시 모델에게 붙여넣습니다.
모델이 최종 diff를 주면 `final.md`로 저장하고 다시 처리합니다.

```bash
lbh respond final.md --session .lbh/sessions/<session-id>
```

LBH는 먼저 candidate diff와 validation 결과를 세션 아래 `candidates/`에 저장합니다.
검증이 통과한 경우에만 최종 diff가 여기에 저장됩니다.

```text
.lbh/sessions/<session-id>/patch.diff
```

먼저 dry-run 검사를 합니다.

```bash
lbh apply .lbh/sessions/<session-id>/patch.diff --session .lbh/sessions/<session-id> --check
```

통과하면 적용합니다.

```bash
lbh apply .lbh/sessions/<session-id>/patch.diff --session .lbh/sessions/<session-id> --yes
```

## 빠른 데모

샘플 저장소를 만들어 smoke test를 해볼 수 있습니다.

```bash
python scripts/create_demo_repo.py /tmp/lbh-demo
cd /tmp/lbh-demo
lbh init
lbh index
lbh ask "결제 후 알림이 안 가요"
```

## 주요 명령어

```bash
lbh init                         # 현재 프로젝트에 .lbh/config.toml 생성
lbh index                        # 로컬 코드 인덱스 생성
lbh search "payment notification" # 관련 파일 검색
lbh ask "요청"                    # initial prompt와 세션 생성
lbh respond response.md --session .lbh/sessions/<id>
lbh read src/foo.py --range 1:80
lbh apply patch.diff --check
lbh status --session .lbh/sessions/<id>
```

자세한 명령어 설명은 [docs/COMMANDS.md](docs/COMMANDS.md)를 보세요.

## 문서 지도

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): 전체 구조와 모듈 책임
- [docs/PROTOCOL.md](docs/PROTOCOL.md): 모델에게 전달되는 LBH 프로토콜
- [docs/COMMANDS.md](docs/COMMANDS.md): CLI 사용법
- [docs/CONFIG.md](docs/CONFIG.md): `.lbh/config.toml` 설명
- [docs/INDEXING.md](docs/INDEXING.md): 인덱싱 흐름과 Tree-sitter 확장 지점
- [docs/SEARCH_AND_RANKING.md](docs/SEARCH_AND_RANKING.md): query expansion, ranking, graph bonus
- [docs/CONTEXT_PACKING.md](docs/CONTEXT_PACKING.md): prompt packing과 lazy loading 설계
- [docs/PATCH_PIPELINE.md](docs/PATCH_PIPELINE.md): diff 추출/검증/적용 흐름
- [docs/SESSION_LIFECYCLE.md](docs/SESSION_LIFECYCLE.md): 세션 폴더와 manifest 관리
- [docs/SECURITY.md](docs/SECURITY.md): 경로, 비밀값, diff 안전 검증
- [docs/TRANSPORTS.md](docs/TRANSPORTS.md): transport adapter 작성 지침
- [docs/CODING_GUIDE.md](docs/CODING_GUIDE.md): 이후 코드 작성자를 위한 모듈별 지시사항
- [docs/SCRIPTS.md](docs/SCRIPTS.md): 보조 스크립트 설명
- [docs/CHATGPT_INSTRUCTIONS.md](docs/CHATGPT_INSTRUCTIONS.md): 모델에게 붙여넣는 핵심 지시사항
- [docs/ROADMAP.md](docs/ROADMAP.md): 확장 계획

## 설계상 중요한 원칙

1. LBH는 파운데이션 모델이 아니다. 로컬 컨텍스트 브로커다.
2. 모델은 로컬 파일을 직접 볼 수 없다고 가정한다.
3. 모델은 본 적 없는 파일을 수정하면 안 된다.
4. LBH는 수정 대상 파일이 세션 중 읽혔는지 확인한다.
5. 최종 출력은 설명문이 아니라 git apply 가능한 unified diff여야 한다.
6. transport 계층은 비즈니스 로직과 분리한다.

## 실제 개발 시 권장 순서

1. `lbh init`, `lbh index`를 실제 repo에서 돌린다.
2. `lbh search`가 적절한 파일을 찾는지 확인한다.
3. `lbh ask`로 생성된 prompt를 모델에 붙여넣는다.
4. 모델의 `[READ: ...]` 요청을 `lbh respond`로 처리한다.
5. 최종 diff를 `lbh apply --check`로 검증한다.
6. 통과하면 `lbh apply --yes`로 적용한다.

이 패키지는 완성형 상용 제품이 아니라, 설계서를 코드로 옮긴 **실행 가능한 기반 프로젝트**입니다. 하지만 인덱싱부터 diff 적용까지 끝까지 돌아가도록 작성되어 있습니다.
