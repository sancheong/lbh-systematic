# Automation Runtime Gap

This document records the concrete mismatch between the committed automation runtime in `3bd3e33` (`Add ChatGPT automation runtime`) and the intended operating model for ChatGPT automation around LBH.

## Intended operating model

The intended model is:

1. Use a thin primary executor for a fixed procedure.
2. Break the procedure into explicit steps such as:
   - open Chrome Profile 4
   - open a new ChatGPT chat
   - paste an artifact
   - submit
   - wait for a response
   - copy the response
3. Execute those steps with the fastest reliable mechanism first:
   - hotkey
   - Playwright or CDP
   - GUI fallback only when needed
4. Do not invoke LBH CLI or LBH V2 at startup.
5. Invoke LBH-style runtimes only after the primary path actually fails and Codex needs a supervised recovery path.
6. After recovery, return to the primary automated procedure.

In short:

- primary path: fast step executor
- fallback path: Codex-supervised LBH runtime

## What `3bd3e33` actually implements

The committed runtime in `3bd3e33` is centered on LBH session orchestration rather than a thin step executor.

### 1. The automation loop starts from LBH workflow state, not from browser procedure steps

`src/lbh/automation/runner.py` in `3bd3e33` starts by creating an LBH session with `ask_request()`, then immediately enters a state machine that assumes a browser controller capable of:

- `start_chat`
- `send_message`
- `wait_for_response`
- `resume_chat`

This means the runtime begins from:

- LBH session creation
- LBH artifact dispatch
- LBH response ingestion

rather than from a browser-first procedure executor.

### 2. The controller contract is conversation-level, not step-level

`src/lbh/automation/base.py` in `3bd3e33` defines a `BrowserController` protocol with:

- `start_chat`
- `resume_chat`
- `send_message`
- `wait_for_response`
- `capture_debug`

That is a chat transport interface, not a step executor interface.

It does not model first-class procedure steps like:

- launch Chrome by hotkey
- activate Profile 4
- navigate via address bar
- focus composer
- paste prompt
- click send
- copy response

It also does not express backend selection or ordering such as:

- hotkey first
- Playwright second
- GUI third

### 3. The shell controller is an RPC bridge for whole chat actions

`src/lbh/automation/shell.py` in `3bd3e33` forwards JSON actions such as:

- `start_chat`
- `send_message`
- `wait_for_response`
- `resume_chat`
- `capture_debug`

This is useful for a transport bridge, but it assumes that the external controller already knows how to perform the whole conversation-level action.

That is not the same as having a thin runtime that deterministically executes a reviewed sequence of explicit browser steps.

### 4. The committed runtime makes LBH the main execution spine

The committed `lbh automate` flow is effectively:

1. `lbh ask`
2. start browser chat
3. send `initial_prompt.md`
4. wait
5. save response
6. run `lbh respond`
7. branch to `context_append`, `repair_prompt`, or `patch.diff`
8. run `lbh apply --check`
9. optionally `lbh apply --yes`

This makes LBH:

- the main orchestrator
- the first runtime invoked
- the central execution path

That is the opposite of the intended architecture, where LBH should remain a fallback and validation runtime, not the primary execution engine.

## Why this is a problem

### Problem 1: fallback was turned into startup path

The intended role of LBH CLI and LBH V2 in this automation design is recovery, not startup.

However, `3bd3e33` assumes LBH from the beginning:

- it creates LBH sessions first
- it structures the browser interaction around LBH artifacts
- it expects the controller to service LBH's conversation loop directly

This collapses primary execution and fallback into the same layer.

### Problem 2: the runtime is too coarse for fast deterministic execution

The intended executor should optimize a fixed known path through explicit steps.

`3bd3e33` does not express:

- which steps can use hotkeys
- which steps should use Playwright
- which steps require GUI
- how to degrade from one backend to another per step

Instead it delegates the entire action to opaque conversation-level controller calls.

That makes the runtime less inspectable and less aligned with the goal of fast repeated execution of a known procedure.

### Problem 3: failure handling stops at blocking rather than recovery handoff

The committed runtime can block and resume, but it does not define a real recovery handoff into a supervised LBH path.

The intended behavior is:

- primary executor fails
- Codex switches to recovery runtime
- recovery is performed intentionally
- automation returns to the primary procedure

The committed version does not model that boundary cleanly.

## Concrete consequences during testing

When this mismatch is ignored, the operator is pushed toward the wrong testing behavior:

1. launch LBH-style runtime first
2. try to use LBH V2 or LBH CLI to begin the browser flow
3. treat the fallback runtime as the primary controller

That is precisely what the intended sketch was trying to avoid.

## Required correction

The correct direction is:

1. Introduce a real primary procedure executor.
2. Represent explicit steps such as:
   - open_profile4_chatgpt
   - ensure_new_chat
   - focus_composer
   - paste_artifact
   - submit_message
   - wait_for_assistant_response
   - copy_assistant_response
3. For each step, encode backend policy such as:
   - hotkey
   - Playwright
   - GUI fallback
4. Treat LBH CLI and LBH V2 as fallback-only runtimes.
5. Only invoke them after an actual failure in the primary path.
6. Resume the primary procedure after recovery.

## Operational conclusion

`3bd3e33` is not useless. It contains:

- resumable automation state
- ChatGPT conversation orchestration
- integration with candidate patch validation
- apply-check/apply handoff

But it is not the intended thin runtime for the primary browser path.

It should therefore be understood as:

- an LBH-centered orchestration runtime

and not as:

- the final step-based primary executor described in the intended sketch

Until that distinction is implemented, the committed runtime should not be treated as a faithful implementation of the intended automation architecture.
