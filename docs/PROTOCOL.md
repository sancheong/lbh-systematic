# LBH Protocol

## Candidate Validation Under Automation

The model output format does not change under `lbh automate`:

- tool requests still use exactly one fenced `lbh-tool` block
- final patches still use a valid LBH diff form

What changes is the operating flow:

- the automation runtime forwards ChatGPT output into `lbh respond`
- any diff is first stored as a candidate patch
- validation must pass before `patch.diff` exists
- failed candidates generate critique and repair prompt artifacts for the next ChatGPT round

LBH 프로토콜은 모델이 로컬 파일을 직접 볼 수 없다는 전제에서 동작합니다.
모델은 두 가지 중 하나만 출력해야 합니다.

1. 추가 컨텍스트 요청
2. 최종 unified diff

운영상 모델이 낸 최종 diff는 바로 적용되지 않습니다.
LBH는 먼저 이를 candidate patch로 저장하고 deterministic validation을 수행한 뒤, 통과한 경우에만 `patch.diff`로 promote합니다.

## 모델에게 주는 핵심 규칙

```text
1. 제공받은 컨텍스트만 사용한다.
2. 더 필요한 파일은 fenced `lbh-tool` block 또는 [READ: path]로 요청한다.
3. raw JSON만 출력하거나 `json` fenced block을 쓰지 않는다.
4. schema에 없는 필드를 만들지 않는다.
5. 아직 읽지 않은 파일은 수정하지 않는다.
6. 최종 답변은 diff 블록 하나만 출력한다.
7. 모르면 추측하지 말고 컨텍스트를 요청한다.
```

## 권장 tool 요청 형식

추가 컨텍스트 요청은 반드시 정확히 하나의 fenced `lbh-tool` block이어야 합니다.
다음은 올바른 예시입니다.

```lbh-tool
{
  "type": "context_request",
  "requests": [
    {
      "op": "READ",
      "path": "src/payments/checkout.ts",
      "ranges": [{"start": 1, "end": 160}],
      "why": "Need to inspect checkout flow."
    }
  ]
}
```

다음은 올바르지 않습니다.

```text
{ ...raw json only... }
```

````markdown
```json
{ ... }
```
````

## 지원 op와 request shape

실제 구현 기준 허용 필드:

- `READ`: `op`, `path`, `ranges`, `why`
- `GREP`: `op`, `pattern` 권장, `query` 허용, `globs`, `max_results`, `why`
- `FIND_SYMBOL`: `op`, `query` 권장, `pattern` 허용, `max_results`, `why`
- `LIST_DIR`: `op`, `path`, `why`
- `DEP_GRAPH`: `op`, `path`, `why`
- `TEST_HINTS`: `op`, `path`, `why`

모델은 위 schema에 없는 필드를 만들면 안 됩니다.
특히 `FIND_SYMBOL`에서 `symbol` 같은 필드를 만들어서는 안 됩니다.

## READ path 규칙

- READ path는 Repository Map, Relevant Directory Tree, Evidence Snippets, 또는 이전 LBH tool result에 정확히 등장한 경로만 사용해야 합니다.
- import 문, module name, documentation mention, comment, 관례적 패키지 구조만으로 경로를 만들어 READ하면 안 됩니다.
- 경로가 추론만 가능한 경우에는 먼저 `GREP`, `FIND_SYMBOL`, `LIST_DIR`, `DEP_GRAPH`로 정확한 경로를 확인하세요.
- `GREP`, `FIND_SYMBOL`, `LIST_DIR`, `DEP_GRAPH`, `TEST_HINTS`는 경로 발견과 주변 탐색용이지, 최종 수정 대상 파일의 본문 READ를 대체하지 않습니다.

## Legacy READ 형식

간단한 수동 흐름에서는 아래도 지원합니다.

```text
[READ: src/payments/checkout.ts]
[READ: src/notifications/worker.ts#1-120]
```

## 최종 diff 형식

가장 권장하는 형식은 4-backtick 이상의 `text` fenced block 안에 들어 있는 LBH sentinel diff입니다.
raw sentinel 본문도 parser는 처리할 수 있지만, ChatGPT UI에서 `+`, `-`, 들여쓰기, backtick이 Markdown으로 다시 해석될 수 있어 권장하지 않습니다.

Markdown fenced code block을 수정하는 패치에서는 이 형식이 특히 중요합니다.
outer code fence는 transport wrapper이고, sentinel 내부는 여전히 순수 git unified diff여야 합니다.

`````markdown
````text
<<<LBH_DIFF_BEGIN schema="lbh.diff.v1">>>
diff --git a/src/foo.py b/src/foo.py
--- a/src/foo.py
+++ b/src/foo.py
@@ -1,3 +1,3 @@
-old
+new
<<<LBH_DIFF_END>>>
````
`````

또는 fenced block도 허용합니다.

````markdown
```lbh-diff
diff --git a/src/foo.py b/src/foo.py
--- a/src/foo.py
+++ b/src/foo.py
@@ -1,3 +1,3 @@
-old
+new
```
````

sentinel diff를 쓰더라도 내부는 순수 git unified diff여야 합니다.
- diff 내부에 Markdown bullet, fenced code block, 설명문, numbered list를 넣으면 안 됩니다.
- `diff --git` header는 반드시 column 1에서 시작해야 합니다.
- hunk 내부 줄은 공백, `+`, `-` 중 하나로 시작해야 합니다.
- outer code fence는 transport wrapper일 뿐이며, sentinel과 내부 diff 문법을 느슨하게 만들지 않습니다.
- Markdown fence edits에서는 raw sentinel보다 4-backtick wrapped sentinel을 우선 권장합니다.

## LBH의 검증 규칙

- diff는 정확히 하나여야 한다.
- path는 repo 내부 상대 경로여야 한다.
- `../`, 절대 경로, symlink escape는 거부한다.
- `.env`, key, pem, credential 파일은 거부한다.
- 새 파일이 아닌 수정 파일은 세션 중 READ 또는 snippet으로 실제 본문이 제공된 적이 있어야 한다.
- repo map, directory tree, grep 결과, symbol 검색 결과는 read-before-modify를 만족하지 않는다.
- 문서 파일도 코드 파일과 동일하게 먼저 본문이 제공되어야 한다.
- `git apply --check`를 통과해야 한다.

## context append 형식

LBH가 파일을 읽어줄 때는 아래 형태로 생성합니다.

```markdown
# LBH CONTEXT APPEND

session: 20260606-...
round: 1

<file path="src/foo.py" sha256="..." lines="1-80">
1 | def foo():
2 |     pass
</file>
```

이 형식은 모델이 line number와 파일 hash를 함께 볼 수 있도록 만든 것입니다.
이 `<file ...>` block이나 initial prompt의 `<snippet ...>` block만이 “파일 본문을 실제로 봤다”는 근거로 취급됩니다.
