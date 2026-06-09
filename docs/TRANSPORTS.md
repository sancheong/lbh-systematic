# Transport Layer

## Browser Controller Contract

`lbh automate` does not hardcode a Chrome automation library inside LBH core. Instead, it talks to an external browser controller command.

The command receives one JSON payload on stdin and must return one JSON object on stdout.

Supported actions:

- `start_chat`
- `resume_chat`
- `send_message`
- `wait_for_response`
- `capture_debug`

This keeps browser transport swappable while preserving the main LBH rule: repo indexing, tool execution, candidate validation, and patch promotion remain inside LBH.

transport는 LBH와 모델 사이에서 메시지를 주고받는 계층입니다.

## 관련 코드

```text
src/lbh/transport/base.py
src/lbh/transport/manual.py
src/lbh/transport/catgpt_gateway.py
```

현재 구현은 수동 transport입니다.

```text
1. LBH가 prompt 파일 생성
2. 사용자가 prompt를 모델에 붙여넣음
3. 사용자가 모델 응답을 response.md로 저장
4. lbh respond가 응답을 파싱
```

`CatGPT-Gateway`를 쓰는 경우에는 같은 경계를 유지한 채 수동 copy/paste만 HTTP adapter로 바꿉니다.

Gateway health/readiness preflight is deployment-specific. If a caller checks `GET /status`, it must use the same authentication policy as the real gateway deployment. In deployments that protect status endpoints, `/status` may require `Authorization: Bearer dummy123` or the configured bearer token; do not assume status is unauthenticated unless that matches the gateway policy.

```text
1. LBH가 initial_prompt.md 생성
2. gateway가 /thread/new 로 첫 메시지를 전송
3. gateway가 assistant 응답을 response_001.md로 저장
4. lbh respond가 응답을 파싱
5. context append 또는 repair prompt를 같은 thread_id로 다시 전송
```

## 왜 수동 transport부터 시작하는가

LBH의 핵심 가치는 transport가 아니라 다음에 있습니다.

- repo index
- search/ranking
- context packing
- lazy loading protocol
- diff validation
- git apply

transport를 먼저 자동화하면 디버깅이 어려워집니다.
따라서 처음에는 수동 transport로 프로토콜과 patch pipeline을 안정화하는 편이 좋습니다.

## 향후 adapter 지침

새 transport를 만들 때는 다음 interface를 지키세요.

```python
class ModelTransport(Protocol):
    def start_session(self, initial_prompt: str) -> StartedSession: ...
    def send(self, session_id: str, message: str) -> ModelResponse: ...
```

금지 사항:

- transport 내부에서 파일 검색/패치 적용을 하지 마세요.
- transport 내부에서 prompt 규칙을 임의로 바꾸지 마세요.
- transport 내부에서 response parsing을 중복 구현하지 마세요.

허용되는 책임:

- 메시지 전송
- 응답 수신
- retry/backoff
- session id 매핑
- provider별 metadata 저장

공식 API, 사내 gateway, local LLM 등 허용된 경로를 붙일 때 이 계층을 확장하면 됩니다.
