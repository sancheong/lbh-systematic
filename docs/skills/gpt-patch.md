# GPT-patch

Project-owned workflow for the `gpt-patch` skill when Codex is operating `lbh-systematic` from `C:\developer\lbh-systematic`.

The installed skill entrypoint should stay minimal and point here when the active repository is this checkout.

## Purpose

Use LBH against a local Git repository.

- If the user does not provide a target path, use the current working directory when it is already a Git repository.
- Codex is an LBH operator and reporter, not a patch author, patch reviewer, or direct implementation agent.
- The goal is to run LBH, determine the workflow state, and report the result with minimal patch inspection.

## Non-negotiable Rules

- Do not directly implement the requested code or docs change.
- Do not manually create or edit patch candidates outside LBH.
- Do not inspect or summarize `patch.diff`, `candidates/candidate_*.diff`, full raw response files, or `answer.md` unless the user explicitly asks.
- Do not read target repository source files beyond lightweight preflight checks needed to run LBH.
- Do not retry with a broader or different request before reporting the exact stop reason.
- Do not guess API keys, alternate gateway URLs, or repository recovery steps.
- Do not `git init`, stash, reset, clean, or discard user changes unless the user explicitly asks.
- Let LBH auto-apply promoted patches by default. Use non-apply mode only when the user explicitly requests it.

If a required step fails, stop and report the blocker. Do not substitute a custom workflow.

## Canonical References

This skill should link to canonical docs instead of restating them.

- Protocol and patch format rules: [docs/PROTOCOL.md](C:/developer/lbh-systematic/docs/PROTOCOL.md:1)
- CLI usage and flags: [docs/COMMANDS.md](C:/developer/lbh-systematic/docs/COMMANDS.md:1)
- Validation, repair, promotion, and apply pipeline: [docs/PATCH_PIPELINE.md](C:/developer/lbh-systematic/docs/PATCH_PIPELINE.md:1)

## Operating Assumptions

- LBH source checkout: `C:\developer\lbh-systematic`
- Shell syntax: PowerShell
- Commands run from the target repository, not from the LBH source checkout
- Gateway base URL: `http://localhost:8000`
- Gateway auth comes from explicit user input or `LBH_GATEWAY_API_KEY`
- Existing unrelated working tree changes are user-owned

If `C:\developer\lbh-systematic` is missing, stop and ask for the LBH checkout path.

## Allowed Actions

The skill may only:

1. Inspect required paths and repository state.
2. Run read-only Git checks such as `git rev-parse --is-inside-work-tree`, `git status --short`, and `git branch --show-current`.
3. Run `python -m lbh.cli init` only when `.lbh` is missing.
4. Run `python -m lbh.cli index` when initialization or reindexing is required.
5. Check gateway reachability and authentication at `http://localhost:8000/status`.
6. Run `python -m lbh.cli gateway-run` in default auto-apply mode.
7. Use `--skip-apply` or `--check` only when the user explicitly requests non-apply mode.
8. Inspect only status-level LBH artifacts needed to determine success or failure.
9. Report the final state, artifact paths, stop reason, and next safe command.

## Minimal Workflow

Run these steps in order and stop at the first required failure.

1. Confirm the target path exists and is a Git repository.
2. Confirm the LBH source checkout exists.
3. Record whether unrelated working tree changes are present.
4. Check whether `.lbh` exists in the target repository.
5. Set `PYTHONPATH` to `C:\developer\lbh-systematic\src`.
6. Run `lbh init` only if `.lbh` is missing.
7. Run `lbh index` after init and whenever the index may be stale.
8. Resolve the gateway API key from user input or `LBH_GATEWAY_API_KEY`.
9. Call `GET http://localhost:8000/status` with the same bearer token that `gateway-run` will use.
10. Run `gateway-run` with a short, rough, intent-clear request.
11. Inspect only status-level artifacts and report the resulting workflow state.

## Required Command Pattern

Before any LBH command:

```powershell
$env:PYTHONPATH = 'C:\developer\lbh-systematic\src'
$gatewayApiKey = $env:LBH_GATEWAY_API_KEY
if (-not $gatewayApiKey) { throw 'LBH_GATEWAY_API_KEY is not set' }
```

Required preflight:

```powershell
git rev-parse --is-inside-work-tree
git status --short
git branch --show-current
Test-Path 'C:\developer\lbh-systematic'
Test-Path '.lbh'
Invoke-RestMethod http://localhost:8000/status -Headers @{ Authorization = "Bearer $gatewayApiKey" }
```

When `.lbh` is missing:

```powershell
python -m lbh.cli init
python -m lbh.cli index
python -m lbh.cli gateway-run "<rough request>" --base-url http://localhost:8000 --api-key $gatewayApiKey --max-rounds 20
```

When `.lbh` already exists:

```powershell
python -m lbh.cli index
python -m lbh.cli gateway-run "<rough request>" --base-url http://localhost:8000 --api-key $gatewayApiKey --max-rounds 20
```

For explicit non-apply mode only, append `--skip-apply`. `--check` is accepted only as compatibility wording for the same behavior.

## Reindex Rule

- Do not rerun `lbh init` unless `.lbh` is missing or the user explicitly requests a fresh workspace.
- Rerun `lbh index` after file additions, deletions, renames, signature changes, import changes, meaningful docs or config edits, or branch switches that affect relevant files.
- If unsure whether the index is stale, rerun `lbh index`.

## Rough Request Rule

Use a short request that clearly identifies a subsystem, file area, symptom, behavior, or documentation gap.

Good examples:

- `README is vague about hashline patch rules, tighten that up`
- `CLI help is confusing, clean up the command wording`
- `PROTOCOL docs miss answer mode, add that explanation`

Do not broaden the user's scope or add unrelated cleanup.

## Artifact Reading Limits

- For `patch_ready`, report the `patch.diff` path. Do not open or summarize the patch.
- For `answer_ready`, report the `answer.md` path. Do not read it unless the user asks.
- For validation failure, report status-level artifact paths such as the candidate diff, validation JSON, critique, and repair prompt.
- For blocked runs, report the exact stop reason and what should be inspected next.

Patch-format details, hashline anchors, and diff fallback rules belong in [docs/PROTOCOL.md](C:/developer/lbh-systematic/docs/PROTOCOL.md:1), not here.

## Outcome Mapping

When `gateway-run` finishes, classify and report only the workflow outcome:

- `patch_ready`: include session path, latest response file, `patch.diff` path, whether apply was skipped, and next safe command.
- `answer_ready`: include session path, latest response file, `answer.md` path, and next safe command.
- `validation_failed`: include candidate diff path, validation JSON path, critique path, repair prompt path, exact stop reason, and next safe command.
- `blocked`: include session path, latest response file if available, exact stop reason, and what should be inspected next.

## Failure Handling

If a required step fails:

1. Stop immediately.
2. Report the failed step.
3. Report the exact command, if applicable.
4. Report the relevant output or stop reason.
5. Report any artifact path that helps the user inspect the failure.
6. Do not hide `git apply --check` failures.
7. Do not attempt a workaround unless the user explicitly asks.

## Manual Apply Boundary

Codex must not manually apply patches outside the LBH workflow unless the user explicitly asks.

Before any manual patch application, report:

- the patch path
- the current working tree status
- whether unrelated working tree changes exist
- the exact apply command that will be run

## Final Response Checklist

Every final response should cover these fields. Use `not applicable` where needed.

```text
LBH workflow status:
Target repository:
LBH source checkout:
Gateway URL:
Working tree had unrelated changes:
.lbh init run:
lbh index run:
gateway-run auto-apply mode used:
Explicit non-apply flag used:
Session path:
Latest response file:
Patch diff path:
Answer path:
Candidate diff path:
Validation artifact path:
Critique path:
Repair prompt path:
Patch contents inspected:
Answer contents inspected:
Exact stop reason:
Next safe command:
Skipped steps:
```

`Patch contents inspected` should normally be `no`.

`Answer contents inspected` should normally be `no`.
