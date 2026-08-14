---
name: emscripten-triage
description: Triage, classify, reproduce, and bisect Emscripten and Emscripten SDK issues and pull requests locally in read-only mode. Use when asked to triage an issue or PR (e.g. "triage issue #1234") or when spawned by triage_agent.py.
---

# Emscripten Triage Agent Skill

Instructions for triaging, reproducing, and bisecting Emscripten and Emscripten
SDK issues and pull requests in read-only mode.

## Interactive Triage Mode (Pair Programming)

When asked to triage an issue or PR interactively (e.g., *"please triage issue #1234"*):
1. **Fetch metadata** using the GitHub CLI or run the triage orchestrator for that specific item:
   ```bash
   # Run the single-item orchestrator in the background/foreground:
   ./triage_agent.py -i <NUMBER> --force
   ```
   Or fetch metadata directly:
   ```bash
   gh issue view <NUMBER> --repo emscripten-core/emscripten --json number,title,body,createdAt,url,labels
   ```
2. Follow the **5-Step Triage Workflow** below (Search $\to$ Repro on `main` $\to$ Historical `emsdk` $\to$ Worktree isolation $\to$ Synthesis).
3. Present your findings clearly to the user:
   - **Recommendation**: `close` | `reproduced` | `investigate` | `needs_info`
   - **Certainty**: `high` | `medium` | `low`
   - **Rationale**: 1-3 concise sentences explaining the outcome.
   - **Suggested Action / Comment**: Actionable close comment or next steps.

---

## STRICT SAFETY RULES (READ-ONLY)
1. **NEVER push anything to GitHub** (`git push`, `gh issue comment`, `gh issue close`, `gh pr review`, etc. are STRICTLY FORBIDDEN).
2. **NEVER modify any remote repositories or issues online.**
3. All work, git checkouts, bisection runs, test scripts, and log outputs must remain strictly on the local filesystem.
4. **NEVER modify or write files inside parent checkouts** (e.g. `../emscripten`, `../llvm-project`, `../binaryen`, `../emsdk`). ALL file edits (`replace_file_content`, `write_to_file`, scratch files, build artifacts) MUST take place inside your assigned workspace (`$PWD`) or inside an on-demand worktree (`$PWD/<repo>`).
5. **NEVER RECOMMEND CLOSING BASED ON LOCAL FIXES**: Your job is to evaluate the upstream state of `main`. Never recommend `close/fixed` or `close/implemented` because you authored a local fix or document during your triage run. If a bug or documentation gap still exists on upstream `main`, classify it as `reproduced` or `investigate` with `actionability: high`.

## Your Goal & Deliverables

For each assigned issue or PR, produce two files inside the issue directory (`issues/<repo>/<type>/<number>/`):
1. **`investigation.md`**: Chronological narrative log detailing steps taken, environments tested, commands executed, and bisection details.
2. **`result.json`**: Structured JSON summarizing findings and formal recommendation.

### Required `result.json` Schema
```json
{
  "status": "completed",
  "recommendation": "close/fixed | close/invalid | close/duplicate | close/obsolete | close/unreproducible | close/implemented | reproduced | investigate | needs_info",
  "certainty": "high | medium | low",
  "rationale": "1-3 sentences summarizing why you make this recommendation and why certainty is high/medium/low.",
  "actionability": "high | medium | low",
  "resolved_pr": "PR_number_or_null (e.g. '#14321' or '14321')",
  "resolved_commit": "commit_hash_or_null",
  "reproduced_on_reported_version": true | false | null,
  "reproduced_on_main": true | false | null,
  "bisected_commit": "commit_hash_or_null",
  "suggested_close_comment": "Draft comment explicitly citing the resolving PR/commit (e.g. 'Fixed in PR #NNN (commit <hash>)')."
}
```

### Granular Recommendation Guide:
- **`close/fixed`**: Verified resolved/fixed on current `main`. Search git history (`git log --grep="#<number>"`, `git log -S...`) to identify the resolving PR or commit whenever possible, citing the GitHub PR number in `resolved_pr`, `rationale`, and `suggested_close_comment`.
- **`close/implemented`**: Feature request that has already been implemented in Emscripten. Search git history to find the PR or commit that added the feature, citing the GitHub PR number in `resolved_pr`, `rationale`, and `suggested_close_comment` if found.
- **`close/invalid`**: Working as intended, user configuration error, or answered usage question.
- **`close/duplicate`**: Duplicate of another issue or pull request (cite duplicate `#NNN`).
- **`close/obsolete`**: Relates to deprecated/removed architectures (`fastcomp`, `asm.js`, Python 2, obsolete runtimes).
- **`close/unreproducible`**: Non-actionable report with missing info, no repro steps, and unresponsive reporter.
- **`reproduced`**: Confirmed ongoing bug that still reproduces on current `main`.
- **`investigate`**: Valid bug or feature requiring maintainer research (cannot easily reproduce standalone).
- **`needs_info`**: Needs additional reproduction code or flags from reporter.

## Recommended Time-Boxing Strategy

Be mindful of your assigned **Time Budget** passed in your prompt:
- **Phase 1 (Search & Classification)**: 1 minute.
- **Phase 2 (Reproduction on `main`)**: 2 minutes.
- **Phase 3 (Historical Version via `emsdk`)**: 2–3 minutes.
- **Phase 4 (Final Synthesis)**: 1 minute.

---

## Triage Workflow

### 1. Fast-Path Code, Doc & Commit Search (0–60 Seconds)
Before attempting expensive builds or reproductions, search the existing codebase and commit history to see if the issue is already answered, documented, or resolved:
- **Documentation Search**: Check `../emscripten/site/source/docs/` or user manual:
  ```bash
  git -C ../emscripten grep -i "<symbol_or_keyword>" site/source/
  ```
- **Codebase Search**: Check whether a setting, function, or flag exists:
  ```bash
  git -C ../emscripten grep "<setting_or_function>" src/ tools/
  ```
- **Commit History Search**: Check if a fix was committed recently:
  ```bash
  git -C ../emscripten log --grep="<keyword_or_issue_number>" --oneline -n 20
  git -C ../emscripten log -S "<symbol>" --oneline -n 20
  ```

#### Early-Exit Triggers:
- **Deprecated / Obsolete Features**: If the issue concerns `fastcomp`, `asm.js`, Python 2, or legacy Node versions, exit immediately with `"recommendation": "close"`, `"certainty": "high"`.
- **Usage / Documentation Questions**: If the user is asking how to do something and the docs or tests demonstrate it, cite the docs/test and recommend `"close"`.
- **Non-Actionable Ancient Reports**: If an issue is $> 2$ years old with no reproduction code, sample files, or logs, mark `"recommendation": "close"`, `"actionability": "low"`, `"certainty": "medium"`.

### 2. Reproduction Phase (Test on `main` First)
When an issue has actionable reproduction steps or sample code:
- **Direct Compilation on `main`**: Use the active system `emcc` in your PATH directly. Create a scratch test file (`repro.c` / `repro.cpp`) in `$PWD` and compile.
  - *Tip: Do NOT create a git worktree just to test compilation on `main`.*
- **If It Reproduces on `main`**:
  - The bug is confirmed on current `main`. Mark `"recommendation": "reproduced"`, `"certainty": "high"`, `"reproduced_on_main": true`.
  - Record findings in `investigation.md` and conclude. (Do not spend extra time bisecting unless specifically required).

### 3. Historical Reproduction & Bisection via `emsdk`
If the issue does NOT reproduce on `main` (suggesting it was fixed), or if you need to confirm that an older release was broken:
- **Use Pre-Built Binaries (`emsdk`)**:
  ```bash
  emsdk install <reported_version>
  emsdk activate <reported_version>
  source ./emsdk_env.sh
  emcc repro.c -o repro.js [FLAGS]
  ```
- **CRITICAL SOURCE BUILD RULE**:
  - **If your timeout budget is less than 30 minutes, NEVER attempt full source builds of LLVM, Binaryen, or Emscripten (`cmake`, `ninja`, etc.)**.
  - Always use pre-compiled binary packages via `emsdk install <version_or_hash>`.
- **Pinpoint Resolving Commit / PR (Recommended for `close/fixed` and `close/implemented`)**:
  - If verified broken on `<reported_version>` but working on `main` (or if feature was added), search commit log and PRs for the resolution:
    ```bash
    git -C ../emscripten log --grep="#<issue_number>" --oneline
    git -C ../emscripten log -S "<symbol_or_feature>" --oneline -n 20
    git -C ../emscripten log -L :<function_name>:src/path/to/file.js
    ```
  - **Always prefer the GitHub PR number** if found (e.g. `PR #14321` or `PR #14321 (commit abc1234)`).
  - Include this in `resolved_pr`, `resolved_commit`, `rationale`, and `suggested_close_comment`. If the exact commit/PR cannot be identified within 1-2 minutes, proceed with the recommendation and note that it is verified working on `main`.

### 4. Multi-Repository Worktree Guidance (On-Demand Isolation)
Only construct a git worktree if you need to check out a specific older Git commit or make a local test patch:
- **CRITICAL LOCATION RULE**: You are spawned in a fresh dedicated working directory for your item (`issues/<repo>/<type>/<number>/`). **All worktrees MUST be created directly inside your current working directory (`$PWD` or `./`)!**
- **NEVER run `git checkout` or `git bisect` directly inside shared parent checkouts** (`../<repo>`).
- **MANDATORY DETACHED WORKTREES**: Always use `--detach` so no named branches are ever created in `git branch`:
  ```bash
  # Format: git -C ../<repo> worktree add --detach $PWD/<repo> HEAD
  git -C ../emscripten worktree add --detach $PWD/emscripten HEAD
  ```
- **DO NOT create named branches** (do NOT use `-b`). Worktrees must always remain in a detached HEAD state.
- Perform all testing, bisection, or building inside `$PWD/<repo>`.
- Clean up your worktree when finished:
  ```bash
  git -C ../emscripten worktree remove --force $PWD/emscripten
  ```

### 5. Writing Final Results
Once your investigation finishes:
1. Save your full notes into `investigation.md`.
2. Write the JSON payload matching the exact schema above into `result.json`.
3. Conclude your turn clearly.
