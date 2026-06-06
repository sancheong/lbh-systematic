# Patch Pipeline

이 문서는 모델이 생성한 diff를 안전하게 로컬에 적용하는 과정을 설명합니다.

## 관련 코드

```text
src/lbh/protocol/parser.py  # diff block 추출
src/lbh/patch/diff.py       # diff path/security 검증
src/lbh/patch/apply.py      # git apply --check / git apply
src/lbh/cli.py              # lbh respond, lbh apply 명령 연결
```

## diff 추출 우선순위

`extract_diff()`는 다음 형식을 지원합니다.

1. LBH sentinel block
2. `lbh-diff` fenced block
3. `diff` fenced block

권장 형식:

`````markdown
````text
<<<LBH_DIFF_BEGIN schema="lbh.diff.v1">>>
diff --git a/src/foo.py b/src/foo.py
--- a/src/foo.py
+++ b/src/foo.py
@@ ...
<<<LBH_DIFF_END>>>
````
`````

LBH diff sentinel은 diff boundary를 알려주는 LBH marker입니다.
ChatGPT 같은 Markdown UI를 통해 전달할 때는 sentinel을 raw text로 두지 말고 code fence 안에 담는 것이 더 안전합니다.
4-backtick `text` wrapper는 diff 내부의 `+`, `-`, backtick, 들여쓰기가 Markdown으로 렌더링되는 것을 줄이기 위한 transport convention입니다.
wrapper가 있더라도 sentinel 내부 patch는 여전히 `git apply --check`가 이해할 수 있는 순수 unified diff여야 합니다.

## candidate patch workflow

ChatGPT가 만든 diff는 먼저 final patch가 아니라 candidate patch로 저장됩니다.

```text
.lbh/sessions/<id>/candidates/candidate_001.diff
.lbh/sessions/<id>/candidates/candidate_001.validation.json
.lbh/sessions/<id>/candidates/candidate_001.critique.md
.lbh/sessions/<id>/candidates/candidate_001.repair_prompt.md
```

candidate validation이 완전히 통과할 때만 `patch.diff`로 promote됩니다.
실패하면 `patch.diff`를 만들거나 덮어쓰지 않고, critique와 repair prompt를 남깁니다.
Codex는 이 repair prompt를 사용해 전체 재구현이 아니라 candidate patch의 최소 수리만 수행할 수 있습니다.

## 검증 항목

`validate_diff()`는 다음을 확인합니다.

```text
- diff --git header 존재
- absolute path 금지
- ../ traversal 금지
- repo 밖 path 금지
- binary patch 금지
- ignored/secret file patch 금지
- 세션에서 읽히지 않은 파일 수정 금지
```

## read-before-modify 정책

세션 manifest에는 모델에게 제공된 파일이 기록됩니다.
여기서 `read_files`는 모델이 실제로 받은 파일 본문 범위를 뜻합니다.
repo map에 등장한 파일은 관련 후보일 뿐이고, READ된 파일이 아닙니다.

```json
{
  "read_files": {
    "src/payments/checkout.py": {
      "ranges": [[1, 120]],
      "sha256": "..."
    }
  }
}
```

모델이 읽지 않은 파일을 수정하려고 하면 기본적으로 거절합니다.
문서 파일을 수정하려는 경우에도 해당 문서 파일 본문이 먼저 제공되어야 합니다.
`validate_diff()`는 이런 읽지 않은 파일 수정을 거절합니다.
이 정책이 hallucinated patch를 줄이는 가장 중요한 장치입니다.

Markdown code fence가 들어 있는 문서를 수정할 때는 fenced `lbh-diff`보다 sentinel diff가 더 안전합니다.
응답 안의 fenced block이 중첩되면서 diff가 깨질 가능성을 줄일 수 있기 때문입니다.
다만 sentinel을 쓴다고 해서 hunk 내부에 Markdown bullet, fenced code block, 설명문을 넣어도 되는 것은 아닙니다.
그런 formatting이 섞이면 diff는 여전히 깨집니다.

## 적용 순서

권장 흐름:

```bash
lbh respond final.md --session .lbh/sessions/<id>
lbh apply .lbh/sessions/<id>/patch.diff --check
lbh apply .lbh/sessions/<id>/patch.diff --yes
```

중요한 repo에서는 적용 전 branch/worktree를 따로 만들어 테스트하세요.
