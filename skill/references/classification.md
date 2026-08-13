# Emscripten Issue Classification Heuristics

Use these criteria to evaluate actionability, staleness, certainty, and recommendations for open issues and pull requests.

## 1. Closing Criteria (`recommendation: "close"`)

### Deprecated / Unsupported Technologies
Recommend closing with **High Certainty** if the issue relates exclusively to:
- **Fastcomp**: The legacy LLVM backend (replaced by the Wasm backend around 2019/2020).
- **Asm.js**: Legacy `asm.js` codegen or performance bugs that do not affect WebAssembly.
- **Python 2**: Emscripten toolchain requires Python 3. Any Python 2 issues are obsolete.
- **Unsupported Host/Runtime Environments**: End-of-life Node.js versions, obsolete browser versions, or legacy OS hosts.
- **Deprecated Emscripten Flags / Subsystems**: e.g., `SOCKET_WEBRTC`, `LEGACY_VM_SUPPORT`, `BINARYEN_METHOD`.

### Fixed in `main` (Verified Resolution)
Recommend closing with **High Certainty** if:
1. You successfully reproduce the reported failure using the historical version mentioned in the issue.
2. You verify that the exact same test case compiles and runs cleanly on current `main`.
3. You identify the commit or PR that resolved the issue (via `git log -S "<symbol>"` or `git log --grep="<keyword>"`).

### Documented / Implemented Features
Recommend closing with **High Certainty** if:
- The issue is a feature or documentation request for something that is now documented in `site/source/docs/` or implemented in `src/` / `tools/` on `main`.

### Non-Actionable / Unresponsive Reporter
Recommend closing with **Medium Certainty** if:
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
