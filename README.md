# Emscripten Triage Agent

A deterministic master loop and sub-agent orchestration repository for triaging
open issues and pull requests across `emscripten-core/emscripten` and
`emscripten-core/emsdk`.

## Overview

The triage agent is designed to run continuously, starting from the oldest
open issues and pull requests, and spawning specialized sub-agents to:
1. Classify issues (actionability, staleness, feature relevance).
2. Check out historical `emsdk`, `emscripten`, `binaryen`, and `llvm` toolchains
   to attempt exact bug reproductions.
3. Determine whether bugs reported in older versions have been fixed on `main`.
4. Provide structured, evidence-based recommendations on whether issues should
   be closed, along with certainty scores and clear rationales.

**IMPORTANT SAFETY GUARANTEE**: All triage scripts and sub-agents operate in a
**read-only** mode with respect to GitHub (`gh`). Nothing is ever pushed back
upstream, nor are any comments or modifications made to live issues or PRs. All
investigation logs, reproduction artifacts, and state summaries are recorded locally.

## Directory Structure

```
emscripten-triage-agent/
├── README.md               # This documentation
├── triage_loop.py          # Master loop script for fetching items and spawning agents
├── summarize_status.py     # Utility to filter, view, and report on triaged items
├── skill/                  # Instructions and reference material for sub-agents
│   ├── SKILL.md            # Main sub-agent skill guide and reproduction workflow
│   └── references/
│       ├── bisection.md    # Guide for binary/source bisection across toolchains
│       └── classification.md # Heuristics for classifying issues and closing criteria
└── issues/                 # Local data store (generated at runtime)
    ├── status.json         # Top-level structured state of all processed items
    ├── status.md           # Human-readable summary table of all triaged items
    └── <repo>/             # Per-repository data (e.g., emscripten/ or emsdk/)
        └── <item_type>/    # 'issue' or 'pr'
            └── <number>/   # Dedicated folder per issue/PR containing logs & findings
```

## Getting Started

### Prerequisites

Ensure you have the following installed and available in your `PATH`:
- `python3` (>= 3.9)
- `gh` (GitHub CLI, authenticated with read access)
- `agentapi` CLI (for spawning sub-agents)

### Running the Master Loop

To process a single batch of the oldest open issues in `emscripten-core/emscripten`:

```bash
./triage_agent.py --repo emscripten-core/emscripten --type issue --limit 5
```

To run continuously in a loop (e.g., inside a background session or tmux/screen):

```bash
./triage_agent.py --repo emscripten-core/emscripten --loop --sleep-interval 300
```

#### Command-Line Options

- `--repo`, `-r`: Target GitHub repository (default: `emscripten-core/emscripten`).
  Can specify multiple times for multiple repos.
- `--type`: Item type (`issue`, `pr`, or `both`; default: `issue`).
- `--limit`, `-l`: Maximum number of unprocessed items to process per pass (default: `10`).
- `--concurrency`, `-j`: Maximum number of parallel sub-agents to run concurrently (default: `5`).
- `--loop`: Run continuously in an infinite loop until stopped.
- `--sleep-interval`: Seconds to pause between loop iterations (default: `300`).
- `--dry-run`: Simulate sub-agent runs without spawning real agents.
- `--output-dir`, `-o`: Directory to store logs and status files (default: `issues`).
- `--skill-dir`: Directory containing skill instructions (default: `skill`).
- `--retry-failed`: Re-run sub-agents on items that previously failed or timed out.
- `--reinvestigate`, `-i`: Specific issue/PR number(s) to force re-investigation on (archives previous run findings).
- `--force`, `-f`: Force re-processing of items even if previously completed.
- `--no-wait`: Skip waiting for async sub-agents to finish their investigations.
- `--no-archive-closed`: Disable automatic syncing and archiving of closed items.

#### Automatic Archiving of Closed Items

At the start of each iteration, `triage_agent.py` automatically checks whether any previously triaged items currently in `status.json` have been closed upstream (`gh search issues/prs --state closed ...`).
When an issue is detected as closed:
1. Its investigation folder is automatically moved to `issues/archive/<repo>/<type>/<number>/`.
2. Its entry is moved to `archived_items` in `status.json` and automatically removed from the active `status.md` table.
3. This keeps the active list (`status.md`) completely clean and focused only on open issues, while preserving all historical triage data on disk.

### Viewing Recommendations & Summaries

To quickly check which issues are recommended for closing along with their rationale
and certainty:

```bash
# Show all issues recommended to be closed with high or medium certainty
./summarize_status.py --recommendation close --min-certainty medium

# Display a full summary table in the terminal
./summarize_status.py --format table
```

## Sub-Agent Workflow & Output Structure

For every item processed, a directory is created at:
`issues/<repo_short_name>/<type>/<number>/` (e.g., `issues/emscripten/issue/1234/`).

Each folder contains:
1. `metadata.json`: Raw GitHub metadata (title, body, labels, creation date).
2. `investigation.md`: Multi-step narrative log produced by the sub-agent detailing
   environment setup, reproduction attempts, and logs.
3. `result.json`: Structured outcome of the triage investigation conforming to:

```json
{
  "status": "completed",
  "recommendation": "close",
  "certainty": "high",
  "rationale": "Issue reported against 2.0.10; reproduced on 2.0.10 but fixed on main in PR #14321.",
  "actionability": "high",
  "reproduced_on_reported_version": true,
  "reproduced_on_main": false,
  "bisected_commit": null,
  "suggested_close_comment": "We verified that this issue repros on 2.0.10 but is fixed on latest main."
}
```
