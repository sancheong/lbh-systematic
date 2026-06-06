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

```text
<<<LBH_DIFF_BEGIN schema="lbh.diff.v1">>>
diff --git a/src/foo.py b/src/foo.py
--- a/src/foo.py
+++ b/src/foo.py
@@ ...
<<<LBH_DIFF_END>>>
```

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
이 정책이 hallucinated patch를 줄이는 가장 중요한 장치입니다.

## 적용 순서

권장 흐름:

```bash
lbh respond final.md --session .lbh/sessions/<id>
lbh apply .lbh/sessions/<id>/patch.diff --check
lbh apply .lbh/sessions/<id>/patch.diff --yes
```

중요한 repo에서는 적용 전 branch/worktree를 따로 만들어 테스트하세요.
