# GPT-patch

This is the canonical project-owned workflow for the `gpt-patch` skill used with `lbh-systematic`.

The installed Codex skill entrypoint should stay minimal and point here when the active repository is `C:\developer\lbh-systematic`.

## Purpose

Use `lbh-systematic` from `C:\developer\lbh-systematic` against a local Git repository.

If the user does not provide a separate target path, use the current working directory as the target repository when it is already a Git repository.

Codex is a runner and reporter, not a patch author, patch reviewer, or implementation agent.

The goal is to save reasoning tokens by preventing Codex from re-reading, understanding, rewriting, or re-implementing the patch. Codex should run LBH, determine whether the workflow succeeded or failed, and report the result.

## Core Rule

Codex must not directly implement the requested code or documentation change.

Codex must not read, inspect, summarize, reinterpret, or review full patch contents unless the user explicitly asks.

This includes:

- `patch.diff`
- `candidates/candidate_*.diff`
- full raw model response files
- target repository source files, unless needed only for lightweight preflight state checks

Codex should report whether LBH produced a valid checked result, not whether Codex personally agrees with the patch.

## Mandatory Behavior

When this skill is invoked:

- Follow only this workflow.
- Act only as an LBH operator.
- Do not directly edit target repository files to satisfy the rough request.
- Do not manually create a patch candidate outside LBH.
- Do not substitute a custom implementation workflow.
- Do not inspect full patch contents by default.
- Do not fall back to raw unified diff if hashline patch validation fails.
- Let LBH automation apply promoted patches by default.
- Use skip-apply/check-only wording only when the user explicitly requests non-apply mode.
- Do not retry with a more complex or different request until the stop reason or validation status has been reported.
- If a required command, path, repository state, gateway check, or validation step fails, stop and report the exact blocker.

If Codex believes another approach would be better, it must report the concern and wait for explicit user permission.

## Operating Assumptions

- The default LBH source checkout is `C:\developer\lbh-systematic`.
- Run commands from the target repository, not from the LBH source checkout.
- If no explicit target repository path is provided, default to the current working directory when `git rev-parse --is-inside-work-tree` succeeds there.
- Use PowerShell syntax on Windows.
- Do not assume the gateway API key is `dummy123`.
- Use a user-provided API key or an explicit environment variable such as `LBH_GATEWAY_API_KEY`.
- If `C:\developer\lbh-systematic` is missing, stop and ask for the source checkout path.
- If the target path is not a Git repository, stop and explain that LBH requires Git. Do not run `git init` unless the user explicitly asks.
- Treat existing unrelated working tree changes as user-owned. Do not modify, stash, clean, reset, or discard them unless the user explicitly asks.

## Allowed Actions

The allowed actions are only:

1. Inspect required paths and repository state.
2. Run read-only Git checks such as `git rev-parse --is-inside-work-tree`, `git status --short`, and `git branch --show-current`.
3. Run `python -m lbh.cli init` only when `.lbh` is missing.
4. Run `python -m lbh.cli index` when required by the reindex rule.
5. Check gateway reachability and authentication at `http://localhost:8000/status`.
6. Run `python -m lbh.cli gateway-run` in default auto-apply mode.
7. Use `--skip-apply` or `--check` only when the user explicitly requests non-apply mode.
8. Inspect only status-level LBH artifacts needed to determine success or failure.
9. Report the final state, artifact paths, stop reason, and next safe command.

No direct repository-changing action is allowed unless the user explicitly asks. Patch application performed by LBH automation after promotion is part of the default workflow.

## Canonical CLI Contract

For this repository, the canonical gateway command is:

```powershell
python -m lbh.cli gateway-run "<rough request>" --base-url http://localhost:8000 --api-key $gatewayApiKey --max-rounds 20
```

Notes:

- `gateway-run` validates and applies a promoted patch by default.
- Use `gateway-run --skip-apply` only when the user explicitly requests non-apply mode.
- `gateway-run --check` is a compatibility spelling for the same explicit non-apply behavior.
- For manual patch application after `patch.diff` already exists, `lbh apply ... --check` validates and `lbh apply ... --yes` applies.

## Artifact Reading Limits

Codex must not read full patch contents by default.

For `patch_ready`:

- Do not open `patch.diff`.
- Do not summarize `patch.diff`.
- Do not inspect candidate diff contents.
- Report only that `patch.diff` was produced and where it is.

For `answer_ready`:

- Do not read or summarize `answer.md` unless the user asks to see the answer.
- Report only that `answer.md` was produced and where it is.

For validation failure:

- Prefer status-level artifacts and paths.
- Report validation status, critique path, repair prompt path, and candidate path if available.
- Do not inspect candidate diff contents unless the user explicitly asks for deeper analysis.

For blocked runs:

- Report the exact stop reason.
- Do not retry with another request or a different strategy unless the user asks.

## Standard Workflow

Run this workflow in order.

1. Confirm the target path exists.
2. Confirm the target path is a Git repository.
3. Check whether `C:\developer\lbh-systematic` exists.
4. Check whether the target repository already has unrelated working tree changes.
5. Check whether the target repository has a `.lbh` workspace.
6. If `.lbh` is missing, run `lbh init`.
7. If `.lbh` already exists, do not run `lbh init`.
8. Run `lbh index` after init and whenever the reindex rule says it is required.
9. Resolve the gateway API key from explicit user input or `LBH_GATEWAY_API_KEY`.
10. Confirm the gateway is reachable and authenticated at `http://localhost:8000/status`.
11. If the gateway returns `401` or `403`, stop and report an authentication blocker.
12. Run `gateway-run` with a short, rough, intent-clear request.
13. Use default auto-apply mode unless the user explicitly requests non-apply mode.
14. Determine the resulting LBH state.
15. Report the result using the required final response format.
16. Stop.

Do not proceed to a later step after a failed required step. Report the blocker.

## Preflight Checks

From the target repository, use read-only checks.

```powershell
git rev-parse --is-inside-work-tree
git status --short
git branch --show-current
Test-Path 'C:\developer\lbh-systematic'
Test-Path '.lbh'
$gatewayApiKey = $env:LBH_GATEWAY_API_KEY
if (-not $gatewayApiKey) { throw 'LBH_GATEWAY_API_KEY is not set' }
Invoke-RestMethod http://localhost:8000/status -Headers @{ Authorization = "Bearer $gatewayApiKey" }
```

Do not continue if any required check fails.

## Required Command Pattern

Use the target repository as the working directory.

Before any LBH command, set:

```powershell
$env:PYTHONPATH = 'C:\developer\lbh-systematic\src'
```

When `.lbh` is missing:

```powershell
$env:PYTHONPATH = 'C:\developer\lbh-systematic\src'
$gatewayApiKey = $env:LBH_GATEWAY_API_KEY
if (-not $gatewayApiKey) { throw 'LBH_GATEWAY_API_KEY is not set' }
python -m lbh.cli init
python -m lbh.cli index
python -m lbh.cli gateway-run "<rough request>" --base-url http://localhost:8000 --api-key $gatewayApiKey --max-rounds 20
```

When `.lbh` already exists:

```powershell
$env:PYTHONPATH = 'C:\developer\lbh-systematic\src'
$gatewayApiKey = $env:LBH_GATEWAY_API_KEY
if (-not $gatewayApiKey) { throw 'LBH_GATEWAY_API_KEY is not set' }
python -m lbh.cli index
python -m lbh.cli gateway-run "<rough request>" --base-url http://localhost:8000 --api-key $gatewayApiKey --max-rounds 20
```

For explicit non-apply mode only, append `--skip-apply` to `gateway-run`; `--check` is accepted as compatibility wording for that same non-apply behavior.

Do not replace these commands with a custom implementation path. If a command fails, report the exact failed command and stop reason.

## Gateway Rule

Before `gateway-run`, check that the gateway is reachable and authenticated at:

```text
http://localhost:8000/status
```

Use the same bearer token for the preflight check and `gateway-run`.

If the gateway is unreachable:

- Do not run `gateway-run`.
- Do not try a different base URL unless the user provides one.
- Report that the gateway is unreachable.
- Include the target repository path and the attempted gateway URL in the report.

If the gateway returns `401` or `403`:

- Do not run `gateway-run`.
- Do not assume the API key is `dummy123`.
- Do not retry with a guessed token.
- Report that gateway authentication failed.
- Include the target repository path, attempted gateway URL, and whether `LBH_GATEWAY_API_KEY` was present.

## Reindex Rule

- Do not rerun `lbh init` unless `.lbh` was deleted or the repository needs a fresh LBH workspace.
- Rerun `lbh index` after file additions, deletions, renames, function or class signature changes, import changes, meaningful docs or config edits, or branch switches that affect relevant files.
- If unsure whether the index is stale, prefer rerunning `lbh index`.
- Rerunning `lbh index` is allowed.
- Rerunning `lbh init` is not allowed unless `.lbh` is missing or the user explicitly requests a fresh workspace.

## Rough Request Rule

Use a short, imperfect, intent-clear request.

Good requests identify a subsystem, file area, symptom, behavior, or documentation gap:

- `README is kind of vague about hashline patch rules, tighten that up`
- `CLI help is a bit confusing, clean up the command wording`
- `PROTOCOL docs seem to miss answer mode, add that explanation`
- `Docs still imply final output must be unified diff, make hashline patch the default wording`

Avoid requests that do not identify any subsystem, file area, or behavior.

Do not expand the user's request into a broader refactor. Do not add unrelated quality improvements. Preserve the user's intended scope.

## Patch Mode Expectations

These expectations apply to the model-facing LBH patch candidate, not to Codex directly editing files.

- Treat `lbh-hashline-patch` as the preferred model-facing patch format.
- Treat `patch.diff` as an internal materialized artifact created by LBH.
- Do not ask the model for raw unified diff unless hashline patch cannot express the change.
- For hashline patches, prefer `new` plus `start_line`, `start_hash`, `end_line`, and `end_hash`.
- Do not require the model to retype the full `old` block unless LBH explicitly asks for it.
- Use `block_hash` only when LBH context explicitly provides it.
- Hashline line numbers are original-file coordinates from LBH-provided context.
- Same-file edit ranges may be listed in any order, but must not overlap.
- If adjacent lines are renumbered or rewritten together, prefer one larger replacement block instead of many small boundary edits.
- If a hashline-sourced candidate fails, keep repair in `lbh-hashline-patch` mode.
- Do not fall back to raw unified diff after a hashline-sourced candidate failure.
- If a response produces `answer.md`, treat that as a successful explanation result, not a patch failure.

## Result Handling

When `gateway-run` finishes, determine and report only the workflow outcome.

For `patch_ready`, report:

- status: `patch_ready`
- session path
- latest response file
- `patch.diff` path
- whether check passed
- whether apply was skipped by an explicit non-apply flag
- next safe command

Do not read or summarize `patch.diff`.

For `answer_ready`, report:

- status: `answer_ready`
- session path
- latest response file
- `answer.md` path

Do not read or summarize `answer.md` unless the user asks.

For `blocked`, report:

- status: `blocked`
- exact stop reason
- session path
- latest response file if available
- what should be inspected next

For candidate validation failure, report:

- status: `validation_failed`
- candidate diff path, if available
- validation JSON path, if available
- critique path, if available
- repair prompt path, if available
- exact stop reason

Do not retry with a more complex request until the stop reason or validation status has been reported.

## Failure Handling

If any required step fails:

1. Stop immediately.
2. Report the exact failed step.
3. Report the exact command that failed, if applicable.
4. Report the relevant output or stop reason.
5. Report the artifact path, if one exists.
6. Do not attempt a workaround.
7. Do not silently continue.

Do not summarize failures as `the model failed` unless the concrete stop reason is also reported.

Do not hide `git apply --check` failures.

## Applying Patches

LBH automation applies promoted patches by default after validation and apply-check pass.

Use non-apply mode only when the user explicitly asks to stop after patch promotion and apply-check. In that case, add `--skip-apply`; `--check` is accepted only as compatibility wording for the same non-apply behavior.

Codex must not manually apply patches outside the LBH workflow unless the user explicitly asks.

Before any manual patch application, Codex must report:

- the patch path
- the current working tree status
- whether unrelated working tree changes exist
- the exact apply command it intends to run

If unrelated working tree changes exist, Codex must mention them before manual patch application.

## Required Final Response Format

Every final response must include:

```text
LBH workflow status: completed / blocked / failed
Target repository:
LBH source checkout:
Gateway URL:
Working tree had unrelated changes: yes / no / unknown
.lbh init run: yes / no
lbh index run: yes / no
gateway-run auto-apply mode used: yes / no
Explicit non-apply flag used: yes / no
Session path:
Latest response file:
Patch diff path:
Answer path:
Candidate diff path:
Validation artifact path:
Critique path:
Repair prompt path:
Patch contents inspected: yes / no
Answer contents inspected: yes / no
Exact stop reason:
Next safe command:
Skipped steps:
```

If a field does not apply, write `not applicable`.

`Patch contents inspected` should normally be `no`.

`Answer contents inspected` should normally be `no`.

If any required workflow step was skipped, say so explicitly.

Do not claim the workflow completed successfully unless all required steps completed.
