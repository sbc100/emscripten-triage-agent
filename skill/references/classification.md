# Emscripten Issue Classification Heuristics

Use these criteria to evaluate actionability, staleness, certainty, and recommendations for open issues and pull requests.

## 1. Closing Criteria (`recommendation: "close/*"`)

### `close/fixed` (Verified Resolution on `main`)
Recommend `close/fixed` with **High Certainty** if:
1. You successfully reproduce the reported failure using the historical version mentioned in the issue (or verify the bug from the description/logs).
2. You verify that the exact same test case compiles and runs cleanly on current `main`.
3. You identify the commit or PR that resolved the issue (via `git log -S "<symbol>"` or `git log --grep="<keyword>"`).

### `close/implemented` (Feature Added)
Recommend `close/implemented` with **High Certainty** if:
- The issue is a feature or API request that has since been implemented in Emscripten (in `src/` or `tools/`).

### `close/invalid` (Working as Intended / User Error / Documented)
Recommend `close/invalid` with **High Certainty** if:
- The reported behavior is expected / according to WebAssembly or Emscripten specification.
- The issue was due to user misconfiguration or misunderstanding, and the documentation in `site/source/docs/` explains the correct usage.

### `close/duplicate` (Duplicate Issue / PR)
Recommend `close/duplicate` with **High Certainty** if:
- The issue is a duplicate of another existing or resolved issue/PR (cite `#NNN`).

### `close/obsolete` (Deprecated / Removed Architecture)
Recommend `close/obsolete` with **High Certainty** if the issue relates exclusively to:
- **Fastcomp**: The legacy LLVM backend (replaced by Wasm backend).
- **Asm.js**: Legacy `asm.js` codegen or performance bugs.
- **Python 2**: Emscripten toolchain requires Python 3.
- **Unsupported Host/Runtime Environments**: End-of-life Node.js versions, obsolete browser versions, or legacy OS hosts.
- **Deprecated Emscripten Flags / Subsystems**: e.g., `SOCKET_WEBRTC`, `LEGACY_VM_SUPPORT`, `BINARYEN_METHOD`.

### `close/unreproducible` (Non-Actionable / Unresponsive Reporter)
Recommend `close/unreproducible` with **Medium Certainty** if:
- The issue is over 1-2 years old.
- It contains no reproduction code, sample files, command flags, or stack traces ("It doesn't work").
- A maintainer previously requested reproduction steps or clarification, and the reporter has not responded for several months.

---

## 2. Reproduced Criteria (`recommendation: "reproduced"`)

Assign `recommendation: "reproduced"` with **High Certainty** when:
- You constructed a self-contained reproduction script or compiled sample code using `emcc` on current `main`.
- The compilation or execution failed with the exact bug or error described in the issue.
- Conclude immediately and record the reproduction command line and output.

---

## 3. Investigation Criteria (`recommendation: "investigate"`)

Assign `recommendation: "investigate"` when:
- The issue describes a valid bug or feature that cannot easily be reproduced standalone due to external complex dependencies (e.g. complex WebGL engines, large third-party C++ libraries).
- Or when your investigation hits your time budget before a full reproduction can be completed.
- **Certainty Scoring**:
  - **High Certainty**: Verified that the code looks problematic or the stack trace points directly to an active component on `main`.
  - **Medium Certainty**: Verified that the issue is valid, but full verification requires complex environment setup.
  - **Low Certainty**: Ambiguous behavior where user intent is unclear or further triage is required.

---

## 4. Needs Information (`recommendation: "needs_info"`)

Assign `recommendation: "needs_info"` when:
- The issue is relatively recent (< 1 year old).
- The description or logs are incomplete, preventing accurate reproduction.
- A clear follow-up question can be formulated to ask the reporter for exact command flags, self-contained code, or environment details.
