# Documentation Refactoring Note

The current `docs/` set is useful, but there is clear room to refactor the documentation structure before it grows further.

## Observed overlap

Several Markdown files describe adjacent parts of the same LBH workflow:

- `docs/PROTOCOL.md` defines the model-facing protocol, hard rules, tool request format, hashline patch format, diff fallback, and validation expectations.
- `docs/CHATGPT_INSTRUCTIONS.md` restates many of the same model-facing rules as prompt-source material.
- `docs/PATCH_PIPELINE.md` explains candidate patch extraction, validation, repair prompts, read-before-modify policy, and patch promotion.
- `docs/COMMANDS.md` documents CLI entry points, including `lbh automate`, `lbh respond`, and `lbh apply`, which also touch the patch pipeline.
- `docs/AUTOMATION_RUNTIME_GAP.md` captures a specific design/runtime mismatch and overlaps with automation behavior documented elsewhere.
- `docs/CONFIG.md` documents security and context options that directly affect the read-before-modify and new-file behavior described in protocol-oriented docs.

This creates a risk that protocol rules, patch-pipeline behavior, and automation behavior will drift when one document is updated but the others are not.

## Refactoring opportunity

A cleaner structure would separate canonical references from narrative or diagnostic notes:

1. Keep `PROTOCOL.md` as the canonical source for model/LBH exchange rules.
2. Keep `PATCH_PIPELINE.md` as the canonical source for candidate extraction, validation, repair, promotion, and apply behavior.
3. Treat `CHATGPT_INSTRUCTIONS.md` as generated or prompt-source material that intentionally mirrors canonical protocol rules.
4. Keep `COMMANDS.md` focused on user-facing CLI usage and link to the protocol or pipeline docs instead of duplicating operational details.
5. Move long-lived automation design decisions into an automation design document, while keeping gap analyses such as `AUTOMATION_RUNTIME_GAP.md` explicitly historical or diagnostic.
6. Add a short cross-reference section in config documentation for options that enforce protocol guarantees.

## Suggested next step

Do not rewrite everything at once. First, choose canonical ownership for repeated topics:

- protocol and output formats: `PROTOCOL.md`
- patch validation and promotion: `PATCH_PIPELINE.md`
- command invocation examples: `COMMANDS.md`
- configuration knobs: `CONFIG.md`
- historical/runtime mismatch analysis: `AUTOMATION_RUNTIME_GAP.md`

After ownership is clear, each non-canonical document can replace repeated explanations with short summaries and links to the canonical document. That keeps the docs easier to maintain while preserving the current useful detail.
