---
name: emscripten-triage-agent-skill
description: Sub-agent instructions for triaging, reproducing, and bisecting Emscripten and Emscripten SDK issues/PRs in read-only mode.
---

# Emscripten Triage Sub-Agent Skill

You are an automated sub-agent spawned by `triage_loop.py` to investigate an open
Emscripten or Emscripten SDK issue or pull request.

## STRICT SAFETY RULES (READ-ONLY)
1. **NEVER push anything to GitHub** (`git push`, `gh issue comment`, `gh issue close`, `gh pr review`, etc. are STRICTLY FORBIDDEN).
2. **NEVER modify any remote repositories or issues online.**
3. All work, git checkouts, bisection runs, test scripts, and log outputs must remain strictly on the local filesystem.
4. **NEVER modify or write files inside parent checkouts** (e.g. `../emscripten`, `../llvm-project`, `../binaryen`, `../emsdk`). ALL file edits (`replace_file_content`, `write_to_file`, scratch files, build artifacts) MUST take place inside your assigned workspace (`$PWD`) or inside an on-demand worktree (`$PWD/<repo>`).

## Your Goal & Deliverables

For each assigned issue or PR, you must produce two files inside your working directory (`issues/<repo>/<type>/<number>/`):
1. **`investigation.md`**: A chronological narrative log detailing what steps you took, what environment/commits you tested, command outputs, and any bisection details.
2. **`result.json`**: A structured JSON file summarizing your findings and formal recommendation.

### Required `result.json` Schema
```json
{
  "status": "completed",
  "recommendation": "close | investigate | reproduced | needs_info",
  "certainty": "high | medium | low",
  "rationale": "1-3 sentences summarizing why you make this recommendation and why certainty is high/medium/low.",
  "actionability": "high | medium | low",
  "reproduced_on_reported_version": true | false | null,
  "reproduced_on_main": true | false | null,
  "bisected_commit": "commit_hash_or_null",
  "suggested_close_comment": "Draft comment that could be posted later when closing the issue (if applicable)."
}
```

## Triage Workflow

### 1. Initial Classification
Before attempting expensive reproductions, analyze the item based on:
- **Actionability**: Does the issue provide clear steps to reproduce, sample code, or error logs?
- **Staleness / Deprecation**: Does it concern deprecated features (`fastcomp`, `asm.js`, Python 2, old unsupported Node versions)? See `references/classification.md`.
- **Version**: What version of Emscripten/emsdk was reported (e.g., `1.38.30`, `2.0.10`, `3.1.50`)?

If an issue is completely non-actionable (`actionability: "low"`) or purely about deprecated unsupported features, set `"recommendation": "close"`, provide your clear `"rationale"`, and write out `result.json`.

### 2. Reproduction Phase
When an issue has actionable reproduction steps or sample code:
- **Test on `main` First**: Check out or use the latest `main` branch of `emscripten` / `binaryen` / `llvm` to see if the issue reproduces today.
- **Test on Reported Version**: If the issue does NOT reproduce on `main`, or if you need to confirm the regression, use `emsdk` to install and activate the exact historical version reported by the user (e.g., `emsdk install 2.0.10 && emsdk activate 2.0.10`).
- **Creating the Test Case**:
  - Prefer creating a standalone `.c` or `.cpp` reproduction file in a temporary scratch space inside your issue folder or `/tmp`.
  - Compile with `emcc` using the exact flags reported in the issue.
- **Time-Boxing**: Limit reproduction attempts so you do not spin in an infinite loop.

### 3. Bisection Phase (For Confirmed Regressions)
If an issue reproduced on an older release but works on `main` (meaning it was fixed), or if it worked on an older release and fails on `main` (meaning it is a regression):
- See `references/bisection.md` for exact instructions on using `emsdk` and binary releases to bisect across tags in `emscripten-releases-tags.json`.
- Once the release range is narrowed, determine whether the change originated in `emscripten`, `llvm-project`, or `binaryen`.

### 4. Multi-Repository Worktree Guidance (On-Demand Isolation)
If your investigation requires checking out specific commits, bisecting, or editing code in shared repositories located outside the working directory (e.g., the current user's existing checkouts like `emscripten`, `llvm-project`, `binaryen`, `emsdk`):
- **CRITICAL LOCATION RULE**: You are spawned in a fresh dedicated working directory for your item (`issues/<repo>/<type>/<number>/`). **All worktrees MUST be created directly inside your current working directory (`$PWD` or `./`)!**
- **NEVER run `git checkout` or `git bisect` directly inside shared parent checkouts** (`../<repo>`).
- **Construct an on-demand worktree inside `$PWD`**:
  ```bash
  # Format: git -C ../<repo> worktree add --detach $PWD/<repo> HEAD
  git -C ../emscripten worktree add --detach $PWD/emscripten HEAD
  ```
- If a named branch is specifically needed, use `-b triage-<type>-<number>` (e.g., `-b triage-issue-1675`):
  ```bash
  git -C ../emscripten worktree add -b triage-issue-1675 $PWD/emscripten HEAD
  ```
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
