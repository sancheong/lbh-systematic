# Context Packing

컨텍스트 패킹은 “모델에게 무엇을, 얼마나, 어떤 형식으로 줄 것인가”를 결정하는 계층입니다.

## 관련 코드

```text
src/lbh/context/packer.py
```

주요 클래스:

```text
ContextPacker
```

## initial prompt 구성

`lbh ask`는 다음 요소를 조합해 `initial_prompt.md`를 만듭니다.

```text
1. LBH 모델 행동 규칙
2. 사용자 요청
3. repo header
4. ranked file list
5. repo map
6. evidence snippet
7. lbh-tool / lbh-diff 출력 규칙
```

초기 prompt는 전체 파일 본문을 모두 넣지 않습니다.
그 대신 모델이 방향을 잡을 수 있을 정도의 지도와 근거만 제공합니다.

## Lazy loading과의 관계

초기 prompt는 일부러 부족하게 만듭니다.
모델이 더 필요하면 다음처럼 요청하게 합니다.

```text
[READ: src/payments/checkout.py#1-120]
```

또는:

```lbh-tool
{
  "type": "context_request",
  "requests": [
    {"op": "READ", "path": "src/payments/checkout.py", "ranges": [{"start": 1, "end": 120}], "why": "Need checkout flow"}
  ]
}
```

이 구조가 설계서의 “On-Demand Lazy Loading 프롬프트”입니다.

## 좋은 패킹의 기준

좋은 context packer는 다음 조건을 만족해야 합니다.

- 모델이 다음 READ 요청을 고를 수 있을 만큼 repo map을 제공한다.
- 수정 대상 후보 파일의 핵심 symbol과 snippet을 제공한다.
- 관련 test/config/worker 파일을 완전히 놓치지 않는다.
- 너무 많은 파일 본문을 한 번에 넣지 않는다.
- secret redaction을 적용한다.

## 수정 시 주의

`ContextPacker`를 수정하면 반드시 다음을 확인하세요.

```bash
python -m pytest tests/test_index_search_cli.py
scripts/smoke_test.sh
```
