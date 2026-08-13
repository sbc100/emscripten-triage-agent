# Emscripten Issue Classification Heuristics

Use these criteria to evaluate actionability, staleness, certainty, and recommendations for open issues and pull requests.

## 1. Closing Criteria (`recommendation: "close"`)

### Deprecated / Unsupported Technologies
Recommend closing with **High Certainty** if the issue relates exclusively to:
- **Fastcomp**: The legacy LLVM backend (replaced by the Wasm backend around 2019/2020).
- **Asm.js**: Legacy `asm.js` codegen or performance bugs that do not affect WebAssembly.
- **Python 2**: Emscripten toolchain requires Python 3. Any Python 2 issues are obsolete.
- **Unsupported Host/Runtime Environments**: End-of-life Node.js versions, obsolete browser versions, or legacy OS hosts.

### Fixed in `main` (Verified Resolution)
Recommend closing with **High Certainty** if:
1. You successfully reproduce the reported failure using the historical version mentioned in the issue.
2. You verify that the exact same test case compiles and runs cleanly on current `main`.
3. (Optional but helpful) You identify the commit or PR that resolved the issue.

### Non-Actionable / Unresponsive Reporter
Recommend closing with **Medium Certainty** if:
- The issue is over 1 year old.
- It contains no reproduction code, sample files, command flags, or stack traces ("It doesn't work").
- A maintainer previously requested reproduction steps or clarification, and the reporter has not responded for several months.

---

## 2. Investigation Criteria (`recommendation: "investigate"`)

Assign `recommendation: "investigate"` when:
- The issue is actionable and reproduces on current `main`.
- It represents a valid, ongoing bug or missing feature that requires engineering attention.
- **Certainty Scoring**:
  - **High Certainty**: You have a confirmed reproduction script that fails on `main` right now.
  - **Medium Certainty**: You verified that the code looks problematic or the stack trace points to a known active component, but couldn't run a complete reproduction due to external dependencies.
  - **Low Certainty**: Ambiguous behavior where user intent is unclear or further triage is required.

---

## 3. Needs Information (`recommendation: "needs_info"`)

Assign `recommendation: "needs_info"` when:
- The issue is relatively recent (< 1 year old).
- The description or logs are incomplete, preventing accurate reproduction.
- A clear follow-up question can be formulated to ask the reporter for exact command flags, self-contained code, or environment details.
