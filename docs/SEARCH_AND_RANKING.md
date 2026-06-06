# Search and Ranking Design

이 문서는 설계서의 “모호한 사용자 요청에서 관련 파일을 순식간에 추려내는 로컬 메커니즘”을 설명합니다.

## 관련 코드

```text
src/lbh/search/query.py    # 한국어/영어 query expansion
src/lbh/search/ranker.py   # path/symbol/import/content/graph scoring
src/lbh/indexer/store.py   # 검색 대상 데이터 조회
```

## Query expansion

사용자의 자연어 요청은 코드 용어와 다릅니다.
예를 들어 “결제 후 알림 안 감”은 코드에서는 다음 단어로 나타날 수 있습니다.

```text
결제 -> payment, billing, checkout, order, invoice, paid
알림 -> notification, notify, email, push, receipt, message
안 감 -> failed, missing, skipped, not_sent, queue, worker, retry
```

`expand_query()`는 이 변환을 로컬에서 수행합니다.
이 단계에서 모델을 호출하지 않기 때문에 Codex/LLM 사용량을 쓰지 않습니다.

## Ranking signals

`SearchRanker`는 다음 신호를 합산합니다.

```text
path score       파일 경로에 query term이 있는가
symbol score     함수/클래스 이름에 query term이 있는가
import score     import 대상에 query term이 있는가
content score    content preview/chunk에 query term이 있는가
graph score      상위 파일의 import/test edge 근처에 있는가
layer bonus      test/config/worker/provider 같은 계층 다양성
```

## 왜 graph bonus가 필요한가

버그는 보통 한 파일에만 있지 않습니다.

예:

```text
src/payments/checkout.py
  -> src/notifications/bus.py
  -> src/notifications/email_provider.py
  -> tests/test_checkout.py
```

`checkout.py`가 강하게 검색되면, import graph로 연결된 notification 계층에도 점수를 줍니다.
이 방식이 설계서의 Aider repo map/PageRank 아이디어를 간단한 형태로 반영한 부분입니다.

## 다음 개선 지점

- Personalized PageRank 도입
- test adjacency 강화
- route/service/repository/worker layer classifier 추가
- 최근 변경 파일 git prior 반영
- optional embedding/reranker adapter 추가

단, MVP/기반 버전에서는 deterministic ranking을 유지하는 것이 우선입니다.
