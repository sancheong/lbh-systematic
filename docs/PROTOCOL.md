# LBH Protocol

LBH 프로토콜은 모델이 로컬 파일을 직접 볼 수 없다는 전제에서 동작합니다.
모델은 두 가지 중 하나만 출력해야 합니다.

1. 추가 컨텍스트 요청
2. 최종 unified diff

## 모델에게 주는 핵심 규칙

```text
1. 제공받은 컨텍스트만 사용한다.
2. 더 필요한 파일은 lbh-tool 또는 [READ: path]로 요청한다.
3. 아직 읽지 않은 파일은 수정하지 않는다.
4. 최종 답변은 diff 블록 하나만 출력한다.
5. 모르면 추측하지 말고 컨텍스트를 요청한다.
```

## 권장 tool 요청 형식

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

지원 op:

- `READ`: 특정 파일 범위 읽기
- `GREP`: 정규식/문자열 검색
- `FIND_SYMBOL`: symbol 이름 검색
- `LIST_DIR`: 디렉터리 목록
- `DEP_GRAPH`: import 관계 주변 보기
- `TEST_HINTS`: 관련 test 후보 보기

## Legacy READ 형식

간단한 수동 흐름에서는 아래도 지원합니다.

```text
[READ: src/payments/checkout.ts]
[READ: src/notifications/worker.ts#1-120]
```

## 최종 diff 형식

가장 안정적인 형식은 sentinel입니다.

```text
<<<LBH_DIFF_BEGIN schema="lbh.diff.v1">>>
diff --git a/src/foo.py b/src/foo.py
--- a/src/foo.py
+++ b/src/foo.py
@@ -1,3 +1,3 @@
-old
+new
<<<LBH_DIFF_END>>>
```

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

## LBH의 검증 규칙

- diff는 정확히 하나여야 한다.
- path는 repo 내부 상대 경로여야 한다.
- `../`, 절대 경로, symlink escape는 거부한다.
- `.env`, key, pem, credential 파일은 거부한다.
- 새 파일이 아닌 수정 파일은 세션 중 READ된 적이 있어야 한다.
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
