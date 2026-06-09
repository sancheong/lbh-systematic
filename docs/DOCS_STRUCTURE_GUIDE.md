# Documentation Structure Guide

The current `docs/` set is useful, but several files explain adjacent parts of the same LBH workflow. This guide defines clearer ownership so future updates can avoid duplicating protocol, pipeline, automation, and configuration details.

## Current overlap

Several Markdown files currently cover related responsibilities:

- `docs/PROTOCOL.md`: model-facing protocol rules, tool request format, patch formats, and validation expectations.
- `docs/CHATGPT_INSTRUCTIONS.md`: prompt-source material that mirrors many protocol rules.
- `docs/PATCH_PIPELINE.md`: candidate extraction, validation, repair prompts, promotion, and apply behavior.
- `docs/COMMANDS.md`: user-facing CLI entry points, including `lbh automate`, `lbh respond`, and `lbh apply`.
- `docs/AUTOMATION_RUNTIME_GAP.md`: a focused diagnostic note about a runtime/design mismatch.
- `docs/CONFIG.md`: security and context options that enforce read-before-modify and new-file behavior.

When these topics are repeated, one update can easily leave another document stale.

## Proposed ownership

Use each document for one primary job:

| Topic | Canonical document | Other documents should |
| --- | --- | --- |
| Protocol and output formats | `PROTOCOL.md` | Link to it instead of restating full rules. |
| Patch validation and promotion | `PATCH_PIPELINE.md` | Summarize the workflow and link to the pipeline details. |
| Command invocation examples | `COMMANDS.md` | Stay focused on CLI usage and point to deeper references. |
| Configuration knobs | `CONFIG.md` | Explain option behavior and link to affected protocol guarantees. |
| Runtime mismatch analysis | `AUTOMATION_RUNTIME_GAP.md` | Remain explicitly historical or diagnostic. |
| Prompt-source wording | `CHATGPT_INSTRUCTIONS.md` | Mirror canonical rules intentionally and stay concise. |

## Patch pipeline summary

The patch pipeline owns the details for candidate extraction, validation, repair prompts, promotion to `patch.diff`, and apply behavior.

Manual and automated sessions use the same deterministic flow:

1. ChatGPT returns a patch response.
2. `lbh respond` stores it as `candidates/candidate_NNN.diff`.
3. LBH writes the validation, critique, and repair artifacts:
   - `candidate_NNN.validation.json`
   - `candidate_NNN.critique.md`
   - `candidate_NNN.repair_prompt.md`
4. Only a fully valid candidate is promoted to `patch.diff`.
5. Automation runtimes run `lbh apply --check` and then apply the patch by default. An explicit skip-apply flag stops at patch-ready.

If candidate validation fails, automation should not redesign the patch. It should send the generated repair prompt back to the same ChatGPT conversation and attempt a minimal repair round.

## Automation command summary

`lbh automate` starts one ChatGPT conversation per LBH session, sends `initial_prompt.md`, then sends any `context_append_###.md` files. When candidate validation fails, it sends `candidate_###.repair_prompt.md` for a focused repair round.

Validated candidates are promoted to `patch.diff` and applied by default unless `--skip-apply` is set. Runtime state is stored under `manifest.json -> automation`.

## Configuration cross-reference

The security options in `docs/CONFIG.md` support protocol and patch-pipeline guarantees:

- `require_read_before_modify` protects existing files from being patched without session-local body context.
- `allow_new_files_without_read` controls whether the supported new-file patch form is accepted without a prior READ.

These options apply to code, documentation, and Markdown files.

## Refactoring approach

Do not rewrite every document at once. First, move repeated explanations behind short summaries and links to the canonical owner. Then tighten each non-canonical document around its reader task: using a command, understanding a pipeline decision, tuning configuration, or reviewing a diagnostic note.

This keeps the useful detail that already exists while making the documentation easier to maintain as LBH grows.
