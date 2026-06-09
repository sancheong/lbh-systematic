# Session Lifecycle

## Automation Metadata

Automated runs add an `automation` section to `manifest.json`. The section records:

- `provider`: currently `chatgpt_web`
- `controller_kind`: currently `shell_command`
- `chrome_profile`
- `apply_mode`: resolved internal mode, `yes` by default and `check` when `--skip-apply` is used
- `state`
- `retry_counts`
- `chat_ref`
- `latest_outbound_artifact`
- `latest_inbound_response`
- `awaiting_human_intervention`
- `debug_artifacts`

Important states:

- `created`
- `sending_initial_prompt`
- `waiting_for_response`
- `running_lbh_respond`
- `sending_context_append`
- `candidate_failed`
- `candidate_repairing`
- `patch_promoted`
- `apply_check`
- `apply_yes`
- `completed`
- `blocked`

The normal automated success path reaches `apply_check`, then `apply_yes`, then `completed`. With `--skip-apply`, it completes after `apply_check` without entering `apply_yes`.
A blocked session can be resumed with:

```bash
lbh automate --session .lbh/sessions/<session-id> --controller-command "python tools/chatgpt_controller.py"
```

세션은 하나의 사용자 요청을 처리하는 작업 단위입니다.

## 관련 코드

```text
src/lbh/session/manager.py
src/lbh/core/models.py
```

## 생성

`lbh ask "요청"`을 실행하면 다음 폴더가 생성됩니다.

```text
.lbh/sessions/<timestamp>-<slug>/
  manifest.json
  request.txt
  initial_prompt.md
```

## manifest 역할

`manifest.json`은 다음 정보를 보관합니다.

```text
- 사용자 요청
- 생성 시각
- ranked files
- context append 목록
- read files
- latest candidate
- candidate artifact 목록
- patch file
- patch validation 결과
```

## respond 단계

모델 응답이 tool request면:

```text
response.md
  -> lbh respond
  -> context_append_001.md
  -> manifest.read_files 업데이트
```

모델 응답이 diff면:

```text
final.md
  -> lbh respond
  -> candidates/candidate_001.diff
  -> candidate_001.validation.json
  -> candidate_001.critique.md
  -> candidate_001.repair_prompt.md
  -> validation 통과 시에만 patch.diff 로 promote
```

candidate 산출물:

```text
.lbh/sessions/<id>/candidates/
  candidate_001.diff
  candidate_001.validation.json
  candidate_001.critique.md
  candidate_001.repair_prompt.md
```

## read_files가 중요한 이유

모델이 실제로 본 파일만 수정할 수 있게 하기 위해서입니다.

이 규칙이 없으면 모델이 repo map에 있는 path만 보고 파일 내용을 상상해서 patch를 만들 수 있습니다.
