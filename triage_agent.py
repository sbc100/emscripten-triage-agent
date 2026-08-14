#!/usr/bin/env python3
"""Deterministic master loop for triaging Emscripten and Emscripten SDK issues/PRs.

This script fetches open issues or PRs from GitHub via `gh`, starting from the
oldest, and spawns sub-agents to investigate, reproduce, and classify them.
All findings are recorded locally; no changes or comments are pushed to GitHub.
"""

import argparse
import datetime
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def run_command(
    cmd: List[str],
    check: bool = True,
    timeout: Optional[int] = None,
    cwd: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess:
    """Execute a system command and return the completed process object."""
    logging.debug(f"Running command: {' '.join(cmd)}")
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check,
            timeout=timeout,
            cwd=cwd,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        logging.warning(f"Command timed out after {timeout} seconds: {cmd}")
        raise exc


def get_short_repo_name(repo: str) -> str:
    """Extract the short name (e.g., 'emscripten') from a full repo path."""
    return repo.split("/")[-1] if "/" in repo else repo


def fetch_items(
    repo: str, item_type: str, limit: int
) -> List[Dict[str, Any]]:
    """Fetch oldest open issues or PRs from GitHub using `gh` search."""
    assert item_type in ("issue", "pr"), f"Invalid item_type: {item_type}"
    subcommand = "issues" if item_type == "issue" else "prs"
    cmd = [
        "gh",
        "search",
        subcommand,
        "--repo",
        repo,
        "--state",
        "open",
        "--sort",
        "created",
        "--order",
        "asc",
        "--json",
        "number,title,body,createdAt,url,labels",
    ]
    if limit > 0:
        cmd.extend(["--limit", str(limit)])

    logging.info(
        f"Fetching oldest open {item_type}s from {repo} "
        f"(limit: {'all' if limit <= 0 else limit})..."
    )
    # Disable GH interactive TTY/spinner, colors, and update check
    clean_env = dict(
        os.environ,
        GH_FORCE_TTY="0",
        GH_NO_UPDATE_NOTIFIER="1",
        NO_COLOR="1",
        CLICOLOR="0",
    )
    res = run_command(cmd, check=False, env=clean_env)
    if res.returncode != 0:
        logging.error(f"Failed to fetch {item_type}s from {repo}: {res.stderr}")
        return []

    # Strip ANSI escape codes (e.g., color sequences emitted by gh)
    raw_output = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", res.stdout).strip()

    # Strip any leading spinner/ANSI garbage before the first '[' or '{'
    idx_list = raw_output.find("[")
    idx_obj = raw_output.find("{")
    if idx_list != -1 and (idx_obj == -1 or idx_list < idx_obj):
        raw_output = raw_output[idx_list:]
    elif idx_obj != -1:
        raw_output = raw_output[idx_obj:]

    try:
        items = json.loads(raw_output)
        logging.info(f"Retrieved {len(items)} {item_type}(s) from {repo}.")
        return items
    except json.JSONDecodeError as exc:
        logging.error(f"Failed to parse json from `gh` output: {exc}")
        return []


def fetch_item(repo: str, item_type: str, number: int) -> Optional[Dict[str, Any]]:
    """Fetch single issue or PR metadata using gh."""
    subcommand = "issue" if item_type == "issue" else "pr"
    cmd = [
        "gh",
        subcommand,
        "view",
        str(number),
        "--repo",
        repo,
        "--json",
        "number,title,body,createdAt,url,labels",
    ]
    res = run_command(cmd, check=False)
    if res.returncode == 0 and res.stdout:
        try:
            return json.loads(res.stdout)
        except json.JSONDecodeError:
            return None
    return None


def sync_results(output_dir: Path, status_data: Dict[str, Any]) -> bool:
    """Scan item directories for result.json files and update status_data if new findings exist."""
    updated = False
    items = status_data.get("items", {})
    for item_key, info in items.items():
        repo_short = get_short_repo_name(info.get("repo", ""))
        itype = info.get("type", "")
        num = info.get("number")
        if not (repo_short and itype and num):
            continue
        result_file = output_dir / repo_short / itype / str(num) / "result.json"
        if result_file.exists():
            try:
                with open(result_file, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                if payload:
                    rec = str(payload.get("recommendation") or payload.get("outcome") or "unknown").lower()
                    if rec in ("resolved", "fixed"):
                        rec = "close/fixed"
                    elif rec == "close":
                        rec = "close/fixed"
                    info["recommendation"] = rec
                    cert_val = payload.get("certainty")
                    if isinstance(cert_val, (int, float)):
                        cert_val = "high" if cert_val >= 4 else ("medium" if cert_val >= 2 else "low")
                    elif not cert_val:
                        cert_val = "high" if rec != "unknown" else "unknown"
                    info["certainty"] = str(cert_val).lower()
                    info["rationale"] = (
                        payload.get("rationale")
                        or payload.get("summary")
                        or info.get("rationale", "N/A")
                    )
                    info["actionability"] = payload.get("actionability", "unknown")
                    if info.get("status") == "unknown":
                        info["status"] = "completed"
                    updated = True
            except Exception as exc:
                logging.warning(f"Error loading {result_file}: {exc}")
        elif info.get("status") in ("completed", "failed", "timeout") and info.get("recommendation") == "unknown":
            info["status"] = "timeout"
            info["recommendation"] = "investigate"
            info["certainty"] = "low"
            info["rationale"] = "Investigation timed out."
            updated = True

    if updated:
        save_status(output_dir, status_data)
    return updated


def load_status(output_dir: Path) -> Dict[str, Any]:
    """Load top-level status tracking JSON if present and sync newly finished result.json files."""
    status_file = output_dir / "status.json"
    if not status_file.exists():
        return {"items": {}, "last_updated": None}
    try:
        with open(status_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        sync_results(output_dir, data)
        return data
    except Exception as exc:
        logging.warning(f"Could not load {status_file}: {exc}. Starting fresh.")
        return {"items": {}, "last_updated": None}


def save_status(output_dir: Path, status_data: Dict[str, Any]) -> None:
    """Atomic save of top-level status JSON and Markdown summary table."""
    output_dir.mkdir(parents=True, exist_ok=True)
    status_data["last_updated"] = datetime.datetime.now().isoformat()
    status_file = output_dir / "status.json"
    temp_file = output_dir / "status.json.tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(status_data, f, indent=2, sort_keys=True)
    temp_file.replace(status_file)
    update_status_markdown(output_dir, status_data)


def update_status_markdown(output_dir: Path, status_data: Dict[str, Any]) -> None:
    """Generate a Markdown summary table of all triaged items."""
    md_file = output_dir / "status.md"
    lines = [
        "# Emscripten Triage Status Summary",
        "",
        f"*Last Updated: {status_data.get('last_updated', 'N/A')}*",
        "",
        "| Repo | Type | Number | Status | Recommendation | Certainty | Rationale |",
        "| :--- | :--- | :----- | :----- | :------------- | :-------- | :-------- |",
    ]

    items = status_data.get("items", {})
    # Sort items by repo, type, and number
    sorted_keys = sorted(
        items.keys(),
        key=lambda k: (
            items[k].get("repo", ""),
            items[k].get("type", ""),
            int(items[k].get("number", 0)),
        ),
    )

    for key in sorted_keys:
        info = items[key]
        repo_short = get_short_repo_name(info.get("repo", ""))
        itype = info.get("type", "")
        num = info.get("number", "")
        url = info.get("url", "")
        num_link = f"[{num}]({url})" if url else str(num)
        status = info.get("status", "unknown")
        rec = info.get("recommendation", "N/A")
        cert = info.get("certainty", "N/A")
        # Clean up rationale for table display (single line, truncate if long)
        rationale = (info.get("rationale") or "N/A").replace("\n", " ").strip()
        if len(rationale) > 100:
            rationale = rationale[:97] + "..."
        lines.append(
            f"| {repo_short} | {itype} | {num_link} | {status} | {rec} | "
            f"{cert} | {rationale} |"
        )

    lines.append("")
    with open(md_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def archive_closed_items(
    output_dir: Path,
    status_data: Dict[str, Any],
    env: Optional[Dict[str, str]] = None,
) -> int:
    """Check active items in status_data and archive any closed upstream."""
    items = status_data.get("items", {})
    if not items:
        return 0

    # Group active item numbers by (repo, type)
    groups: Dict[tuple, List[int]] = {}
    for item_key, info in list(items.items()):
        if info.get("status") == "archived":
            continue
        repo = info.get("repo", "")
        itype = info.get("type", "")
        num = info.get("number")
        if repo and itype and num is not None:
            groups.setdefault((repo, itype), []).append(int(num))

    archived_count = 0
    for (repo, itype), numbers in groups.items():
        subcommand = "issues" if itype == "issue" else "prs"
        # Batch check in chunks of 50
        for i in range(0, len(numbers), 50):
            batch = numbers[i : i + 50]
            cmd = [
                "gh",
                "search",
                subcommand,
                "--repo",
                repo,
                "--state",
                "closed",
            ] + [str(n) for n in batch] + [
                "--limit",
                str(len(batch)),
                "--json",
                "number",
            ]
            res = run_command(cmd, check=False, env=env)
            if res.returncode != 0:
                logging.warning(
                    f"Failed to check closed state for {repo} ({itype}s): "
                    f"{res.stderr}"
                )
                continue

            raw_output = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", res.stdout).strip()
            idx_list = raw_output.find("[")
            if idx_list != -1:
                raw_output = raw_output[idx_list:]

            try:
                closed_records = json.loads(raw_output)
            except json.JSONDecodeError:
                continue

            closed_numbers = {
                int(rec["number"])
                for rec in closed_records
                if "number" in rec
            }
            if not closed_numbers:
                continue

            repo_short = get_short_repo_name(repo)
            archived_dict = status_data.setdefault("archived_items", {})

            for num in closed_numbers:
                item_key = f"{repo_short}:{itype}:{num}"
                if item_key not in items:
                    continue

                info = items.pop(item_key)
                info["status"] = "archived"
                info["upstream_state"] = "CLOSED"
                info["archived_at"] = datetime.datetime.now().isoformat()
                archived_dict[item_key] = info

                src_dir = output_dir / repo_short / itype / str(num)
                dest_dir = (
                    output_dir / "archive" / repo_short / itype / str(num)
                )
                if src_dir.exists():
                    dest_dir.parent.mkdir(parents=True, exist_ok=True)
                    if dest_dir.exists():
                        shutil.rmtree(dest_dir)
                    shutil.move(str(src_dir), str(dest_dir))
                archived_count += 1
                logging.info(f"Archived closed item: {item_key}")

    if archived_count > 0:
        save_status(output_dir, status_data)
    return archived_count


def cleanup_item_worktrees(item_dir: Path) -> None:
    """Clean up any on-demand git worktrees created inside the item directory and delete associated branches."""
    if not item_dir.exists():
        return

    parent_repos: set[Path] = set()
    branches_to_delete: list[str] = []

    matched_dirs = set(item_dir.glob("triage-*")).union(set(item_dir.glob("*worktree*")))
    for child in item_dir.iterdir():
        if child.is_dir() and (child / ".git").exists():
            matched_dirs.add(child)

    for path in matched_dirs:
        if path.is_dir():
            try:
                res = run_command(
                    ["git", "-C", str(path), "branch", "--show-current"], check=False
                )
                branch = res.stdout.strip() if res.returncode == 0 else ""
                if branch and branch not in ("main", "master", "HEAD"):
                    branches_to_delete.append(branch)

                gitdir_file = path / ".git"
                if gitdir_file.is_file():
                    content = gitdir_file.read_text()
                    if "gitdir:" in content:
                        git_target = content.split("gitdir:", 1)[1].strip()
                        repo_dir = Path(git_target).resolve().parent.parent.parent
                        if repo_dir.exists():
                            parent_repos.add(repo_dir)

                run_command(
                    ["git", "worktree", "remove", "--force", str(path)], check=False
                )
                if path.exists():
                    shutil.rmtree(path, ignore_errors=True)
            except Exception as exc:
                logging.warning(f"Error cleaning up worktree at {path}: {exc}")

    # Fallback to standard parent checkout paths if not auto-discovered
    for repo_name in ["emscripten", "llvm-project", "binaryen", "emsdk"]:
        candidate = (item_dir.parent.parent.parent / repo_name).resolve()
        if candidate.exists() and (candidate / ".git").exists():
            parent_repos.add(candidate)

    # Delete branches and prune worktrees in parent repos
    for repo in parent_repos:
        run_command(["git", "-C", str(repo), "worktree", "prune"], check=False)
        for branch in branches_to_delete:
            run_command(["git", "-C", str(repo), "branch", "-D", branch], check=False)

        res = run_command(
            ["git", "-C", str(repo), "branch", "--list", "triage-*", "issue-*", "pr-*"],
            check=False,
        )
        if res.returncode == 0 and res.stdout:
            for b in res.stdout.splitlines():
                b_name = b.strip("* ").strip()
                if b_name and b_name not in ("main", "master"):
                    run_command(
                        ["git", "-C", str(repo), "branch", "-D", b_name], check=False
                    )


def build_subagent_prompt(
    item: Dict[str, Any],
    repo: str,
    item_type: str,
    item_dir: Path,
    skill_dir: Path,
    fast_mode: bool = False,
    timeout: int = 600,
) -> str:
    """Build detailed instructions for the triage sub-agent."""
    number = item.get("number")
    title = item.get("title")
    body = item.get("body") or "No description provided."
    created_at = item.get("createdAt")
    url = item.get("url")

    skill_path = (skill_dir / "SKILL.md").resolve()
    result_path = (item_dir / "result.json").resolve()
    investigation_path = (item_dir / "investigation.md").resolve()
    resolved_item_dir = item_dir.resolve()

    fast_instructions = ""
    if fast_mode:
        fast_instructions = f"""
### FAST TRIAGE MODE ACTIVE
You are running in **FAST TRIAGE MODE** with a strict timeout budget of {format_duration(timeout)}.
- Focus on identifying low-hanging fruit quickly (e.g. non-actionable reports, stale/deprecated features, simple documentation questions).
- Do NOT spend time on long builds or deep bisection runs. If an issue requires a lengthy setup or reproduction, record your initial observations and output `"recommendation": "investigate"`, `"certainty": "low"` (noting that a deeper pass is required).
"""

    prompt = f"""You are a specialized Emscripten triage and reproduction agent.
Your objective is to investigate open {item_type} #{number} ({title}) in `{repo}`.

### Item Metadata
- **Number**: #{number}
- **Title**: {title}
- **URL**: {url}
- **Created At**: {created_at}
- **Time Budget**: {format_duration(timeout)}
- **Description / Body**:
{body}
{fast_instructions}
### DEDICATED ISOLATED WORKSPACE
Your assigned working directory for this item is:
`{resolved_item_dir}`

If you need to checkout or bisect repositories located outside your working directory (e.g., the current user's existing checkouts like `emscripten`, `llvm-project`, `binaryen`, `emsdk`), construct on-demand worktrees directly inside your working directory `{resolved_item_dir}` using `--detach` mode (NEVER use `-b` to create named branches):
`git -C ../<repo> worktree add --detach {resolved_item_dir}/<repo> HEAD`

### CRITICAL SAFETY GUIDELINES (READ-ONLY)
1. **NEVER push anything to GitHub** (`git push`, `gh issue comment`, `gh issue close`, etc., are strictly forbidden).
2. **NEVER modify live repositories on the internet.**
3. All work, reproduction tests, and findings must remain local and isolated.
4. **NEVER modify or write files directly inside parent checkouts** (e.g. `../emscripten`, `../llvm-project`, `../binaryen`, `../emsdk`). ALL file edits (`replace_file_content`, `write_to_file`, scratch files, build artifacts) MUST take place inside your assigned workspace `{resolved_item_dir}` or inside an on-demand worktree (`{resolved_item_dir}/<repo>`).

### Instructions & Guidance
1. Read the triage skill instructions located at `{skill_path}` using file viewing tools.
2. Follow the 5-step triage workflow:
   - **Classification**: Determine actionability, staleness, and feature relevance.
   - **Reproduction**: Try reproducing on `main` and/or the historically reported version using `emsdk`.
   - **Bisection**: If it is a confirmed regression between versions, bisect to identify the root cause or component.
3. Keep a detailed chronological log of your investigation, environment setup, and test runs. Write this narrative log to `{investigation_path}`.
4. When done, you **MUST write a structured JSON file** summarizing your conclusion to `{result_path}`.

The JSON output at `{result_path}` MUST match this exact schema:
{{
  "status": "completed",
  "recommendation": "close/fixed | close/invalid | close/duplicate | close/obsolete | close/unreproducible | close/implemented | reproduced | investigate | needs_info",
  "certainty": "high | medium | low",
  "rationale": "Clear 1-3 sentence summary explaining the recommendation and certainty.",
  "actionability": "high | medium | low",
  "reproduced_on_reported_version": true | false | null,
  "reproduced_on_main": true | false | null,
  "bisected_commit": "commit_hash_or_null",
  "suggested_close_comment": "Draft comment that could be posted later when closing the issue (if applicable)."
}}

Please begin by reading `{skill_path}` and inspecting the item details."""
    return prompt


def find_agentapi() -> str:
    """Find the path to agentapi executable in PATH or fallback to ~/.gemini/jetski/bin/agentapi."""
    path = shutil.which("agentapi")
    if path:
        return path
    default_fallback = Path.home() / ".gemini" / "jetski" / "bin" / "agentapi"
    if default_fallback.exists():
        return str(default_fallback)
    return "agentapi"


def discover_ls_address() -> Optional[str]:
    """Auto-discover active ANTIGRAVITY_LS_ADDRESS and related variables from running processes."""
    if "ANTIGRAVITY_LS_ADDRESS" in os.environ and os.environ["ANTIGRAVITY_LS_ADDRESS"]:
        return os.environ["ANTIGRAVITY_LS_ADDRESS"]
    try:
        res = subprocess.run(
            "grep -l -z 'ANTIGRAVITY_LS_ADDRESS=' /proc/*/environ 2>/dev/null | head -n 1",
            shell=True,
            capture_output=True,
            text=True,
        )
        pid_env_path = res.stdout.strip()
        if pid_env_path and os.path.exists(pid_env_path):
            with open(pid_env_path, "rb") as f:
                raw_bytes = f.read()
            for entry in raw_bytes.split(b"\x00"):
                line = entry.decode("utf-8", errors="ignore")
                if "=" in line:
                    k, v = line.split("=", 1)
                    if k.startswith("ANTIGRAVITY_") and k not in ("ANTIGRAVITY_SOURCE_METADATA", "ANTIGRAVITY_CONVERSATION_ID"):
                        if v:
                            os.environ[k] = v
            if "ANTIGRAVITY_LS_ADDRESS" in os.environ:
                addr = os.environ["ANTIGRAVITY_LS_ADDRESS"]
                if "ANTIGRAVITY_PROJECT_ID" not in os.environ:
                    os.environ["ANTIGRAVITY_PROJECT_ID"] = "default-cli-project"
                logging.info(f"Auto-discovered active Language Server address: {addr}")
                return addr
    except Exception as exc:
        logging.debug(f"Auto-discovery of Language Server failed: {exc}")
    if "ANTIGRAVITY_LS_ADDRESS" in os.environ and "ANTIGRAVITY_PROJECT_ID" not in os.environ:
        os.environ["ANTIGRAVITY_PROJECT_ID"] = "default-cli-project"
    return None


def spawn_subagent(
    prompt: str,
    item_dir: Path,
    timeout: int,
    title: str,
    dry_run: bool = False,
    agent_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Launch the sub-agent runner and return execution status."""
    prefix = f"Agent[{agent_id}] " if agent_id is not None else ""
    result_path = item_dir / "result.json"

    if dry_run:
        logging.info(f"[DRY-RUN] {prefix}Would spawn agent for: {title}")
        return {"status": "dry_run", "error": None}

    if "ANTIGRAVITY_LS_ADDRESS" not in os.environ:
        discover_ls_address()

    if "ANTIGRAVITY_LS_ADDRESS" not in os.environ:
        err_msg = (
            "ANTIGRAVITY_LS_ADDRESS environment variable is not set in this terminal and no active Language Server was found. "
            "Please ensure Jetski/Antigravity is running, export ANTIGRAVITY_LS_ADDRESS, or run with --dry-run."
        )
        logging.error(err_msg)
        return {"status": "failed", "error": err_msg}

    agentapi_path = find_agentapi()
    cmd = [agentapi_path, "new-conversation", f"--title={title}", prompt]

    logging.info(f"{prefix}Spawning agent for {title}...")
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            proc = run_command(cmd, check=False, timeout=timeout, cwd=item_dir)
            if proc.stdout and ("conversationId" in proc.stdout or "newConversation" in proc.stdout):
                return {"status": "completed", "error": None}
            if proc.returncode == 0:
                return {"status": "completed", "error": None}
            err_msg = proc.stderr.strip() or proc.stdout.strip() or "Non-zero exit code"
            if attempt < max_retries:
                logging.warning(
                    f"{prefix}Spawn attempt {attempt}/{max_retries} failed (code {proc.returncode}). Retrying in 2s..."
                )
                time.sleep(2)
            else:
                logging.error(
                    f"{prefix}Runner failed after {max_retries} attempts with code {proc.returncode}: {err_msg}"
                )
                return {
                    "status": "failed",
                    "error": err_msg,
                }
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "error": f"Timed out after {format_duration(timeout)}"}


def format_duration(seconds: int) -> str:
    """Format seconds into human readable duration string (e.g. 30m0s, 1h5m0s)."""
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}h{minutes}m{secs}s"
    return f"{minutes}m{secs}s"


def wait_for_pending_subagents(
    pending_items: Dict[str, Tuple[Path, Optional[int]]],
    timeout: int,
    output_dir: Path,
    status_data: Dict[str, Any],
) -> None:
    """Wait for all spawned async agents to complete their investigations before exiting."""
    if not pending_items:
        return

    logging.info(
        f"Waiting for {len(pending_items)} agent(s) to complete investigations (timeout: {format_duration(timeout)})..."
    )
    start_time = time.time()
    poll_interval = 5
    remaining = dict(pending_items)

    while remaining and (time.time() - start_time < timeout):
        finished_keys = []
        for item_key, (result_file, aid) in remaining.items():
            prefix = f"Agent[{aid}] " if aid is not None else ""
            if result_file.exists():
                logging.info(f"{prefix}Finished investigation for {item_key}.")
                cleanup_item_worktrees(result_file.parent)
                finished_keys.append(item_key)

        for item_key in finished_keys:
            del remaining[item_key]

        if finished_keys and remaining:
            logging.info(f"Waiting for {len(remaining)} remaining agent(s)...")

        if remaining:
            sync_results(output_dir, status_data)
            time.sleep(poll_interval)

    # Final sync of status.json and status.md
    sync_results(output_dir, status_data)

    if remaining:
        logging.warning(
            f"Timed out waiting for {len(remaining)} agent(s): {', '.join(remaining.keys())}"
        )
        for item_key in remaining.keys():
            if item_key in status_data.get("items", {}):
                item_entry = status_data["items"][item_key]
                item_entry["status"] = "timeout"
                item_entry["recommendation"] = "investigate"
                item_entry["certainty"] = "low"
                item_entry["rationale"] = f"Investigation timed out after {format_duration(timeout)}."
                repo_short = get_short_repo_name(item_entry.get("repo", ""))
                itype = item_entry.get("type", "")
                num = item_entry.get("number")
                if repo_short and itype and num:
                    cleanup_item_worktrees(output_dir / repo_short / itype / str(num))
        save_status(output_dir, status_data)
    else:
        logging.info("All agents completed successfully.")


def archive_previous_run(item_dir: Path) -> Optional[Path]:
    """Archive existing result.json and investigation.md into history/ directory."""
    result_file = item_dir / "result.json"
    investigation_file = item_dir / "investigation.md"
    if not (result_file.exists() or investigation_file.exists()):
        return None

    history_dir = item_dir / "history"
    history_dir.mkdir(exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = history_dir / f"run_{timestamp}"
    run_dir.mkdir(exist_ok=True)

    if result_file.exists():
        shutil.move(str(result_file), str(run_dir / "result.json"))
    if investigation_file.exists():
        shutil.move(str(investigation_file), str(run_dir / "investigation.md"))

    logging.info(f"Archived previous investigation artifacts to {run_dir}")
    return run_dir


def process_item(
    item: Dict[str, Any],
    repo: str,
    item_type: str,
    output_dir: Path,
    skill_dir: Path,
    timeout: int,
    status_data: Dict[str, Any],
    dry_run: bool = False,
    retry_failed: bool = False,
    force: bool = False,
    reinvestigate: bool = False,
    fast_mode: bool = False,
    agent_id: Optional[int] = None,
) -> Tuple[bool, Optional[Path]]:
    """Process a single issue or PR. Returns (did_process, pending_result_file)."""
    number = item.get("number")
    title = item.get("title")
    repo_short = get_short_repo_name(repo)
    item_key = f"{repo_short}:{item_type}:{number}"

    # Check existing status
    existing = status_data["items"].get(item_key, {})
    existing_status = existing.get("status")
    should_force = force or reinvestigate
    if not should_force:
        if existing_status == "completed":
            logging.debug(f"Skipping {item_key} (already completed).")
            return False, None
        if existing_status in ("failed", "timeout") and not retry_failed:
            logging.debug(f"Skipping {item_key} (previously {existing_status}; use --retry-failed to re-run).")
            return False, None

    item_dir = output_dir / repo_short / item_type / str(number)
    item_dir.mkdir(parents=True, exist_ok=True)

    # Always archive previous run artifacts before launching a new investigation run
    if not dry_run:
        archive_previous_run(item_dir)

    # Preserve history of previous runs in status.json
    existing_history = list(existing.get("history", []))
    if existing and existing.get("processed_at") and existing.get("recommendation"):
        existing_history.append({
            "processed_at": existing.get("processed_at"),
            "recommendation": existing.get("recommendation"),
            "certainty": existing.get("certainty"),
            "rationale": existing.get("rationale"),
            "actionability": existing.get("actionability"),
        })

    # Write out raw metadata
    with open(item_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(item, f, indent=2)

    prefix = f"Agent[{agent_id}] " if agent_id is not None else ""
    logging.info(f"--- {prefix}Triaging {item_key}: {title} ---")
    prompt = build_subagent_prompt(
        item, repo, item_type, item_dir, skill_dir, fast_mode=fast_mode, timeout=timeout
    )
    exec_info = spawn_subagent(
        prompt, item_dir, timeout, f"Triage {item_key}", dry_run=dry_run, agent_id=agent_id
    )
    if dry_run:
        return True, None

    result_file = item_dir / "result.json"

    # Update top-level status tracker
    status_entry = {
        "repo": repo,
        "type": item_type,
        "number": number,
        "title": title,
        "url": item.get("url"),
        "status": exec_info["status"],
        "processed_at": datetime.datetime.now().isoformat(),
        "recommendation": "unknown",
        "certainty": "unknown",
        "rationale": exec_info["error"] or "Agent investigating...",
        "actionability": "unknown",
        "history": existing_history,
    }
    status_data["items"][item_key] = status_entry
    save_status(output_dir, status_data)

    pending_path = result_file if exec_info["status"] == "completed" else None
    return True, pending_path


def main() -> int:
    """Parse CLI arguments and run the triage orchestration loop."""
    parser = argparse.ArgumentParser(
        description="Emscripten & Emscripten SDK Triage Orchestrator"
    )
    parser.add_argument(
        "--repo",
        "-r",
        action="append",
        dest="repos",
        help="Repository name(s) (default: emscripten-core/emscripten)",
    )
    parser.add_argument(
        "--type",
        choices=["issue", "pr", "both"],
        default="issue",
        help="Item type to triage (default: issue)",
    )
    parser.add_argument(
        "--limit",
        "-l",
        type=int,
        default=10,
        help="Max items to process per repository per iteration (<= 0 for all)",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously in a loop until stopped",
    )
    parser.add_argument(
        "--sleep-interval",
        type=int,
        default=300,
        help="Seconds to sleep between loop iterations (default: 300)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate sub-agent runs without spawning real agents",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=Path("issues"),
        help="Directory to store triage logs and summaries (default: issues)",
    )
    parser.add_argument(
        "--skill-dir",
        type=Path,
        default=Path("skill"),
        help="Directory containing skill instructions (default: skill)",
    )
    parser.add_argument(
        "--concurrency",
        "-j",
        type=int,
        default=5,
        help="Maximum number of parallel sub-agents to run concurrently (default: 5)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Timeout in seconds per sub-agent run (default: 600 / 10m)",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Fast triage mode: sets default timeout to 3m (180s) and prioritizes low-hanging fruit",
    )
    parser.add_argument(
        "--retry-failed",
        "--retry-timeout",
        action="store_true",
        dest="retry_failed",
        help="Re-process items that previously failed or timed out",
    )
    parser.add_argument(
        "--retry-timeout-only",
        "--retry-timed-out",
        action="store_true",
        dest="retry_timeout_only",
        help="Re-process ONLY items that previously timed out (loads directly from status.json without GitHub search)",
    )
    parser.add_argument(
        "--reinvestigate",
        "--re-investigate",
        "-i",
        nargs="+",
        help="Specific issue/PR number(s) or comma-separated numbers to force re-investigate (e.g. -i 4952 5774)",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force re-processing of items even if already completed",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Do not wait for sub-agents to complete their investigations",
    )
    parser.add_argument(
        "--no-archive-closed",
        action="store_true",
        help="Disable automatic archiving of closed issues/PRs",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose debug logging",
    )

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    reinvestigate_nums = set()
    if args.reinvestigate:
        for arg in args.reinvestigate:
            for part in str(arg).split(","):
                part = part.strip("# ").strip()
                if part.isdigit():
                    reinvestigate_nums.add(int(part))

    if args.fast and args.timeout == 600:
        args.timeout = 180

    repos = args.repos or ["emscripten-core/emscripten"]
    item_types = ["issue", "pr"] if args.type == "both" else [args.type]

    logging.info("Starting Emscripten Triage Master Loop.")
    logging.info(f"Target repositories: {', '.join(repos)}")
    logging.info(f"Item types: {', '.join(item_types)}")
    if args.fast:
        logging.info(f"FAST TRIAGE MODE active (timeout: {format_duration(args.timeout)}).")
    else:
        logging.info(f"Timeout per agent: {format_duration(args.timeout)}.")

    while True:
        status_data = load_status(args.output_dir)
        if not args.no_archive_closed:
            clean_env = dict(
                os.environ,
                GH_FORCE_TTY="0",
                GH_NO_UPDATE_NOTIFIER="1",
                NO_COLOR="1",
                CLICOLOR="0",
            )
            archive_closed_items(args.output_dir, status_data, env=clean_env)

        processed_any = False
        pending_subagents: Dict[str, Tuple[Path, int]] = {}
        agent_counter = 0

        for repo in repos:
            for itype in item_types:
                processed_in_type = 0
                skipped_in_type = 0
                repo_short = get_short_repo_name(repo)
                completed_count = sum(
                    1
                    for k, v in status_data.get("items", {}).items()
                    if v.get("repo") == repo
                    and v.get("type") == itype
                    and v.get("status") == "completed"
                )
                if args.retry_timeout_only:
                    timed_out_keys = [
                        k
                        for k, v in status_data.get("items", {}).items()
                        if v.get("repo") == repo
                        and v.get("type") == itype
                        and v.get("status") == "timeout"
                    ]
                    items = []
                    for k in timed_out_keys:
                        item_entry = status_data["items"][k]
                        num = item_entry.get("number")
                        meta_file = (
                            args.output_dir
                            / repo_short
                            / itype
                            / str(num)
                            / "metadata.json"
                        )
                        if meta_file.exists():
                            try:
                                with open(meta_file, "r", encoding="utf-8") as f:
                                    items.append(json.load(f))
                            except Exception:
                                pass
                        if not any(it.get("number") == num for it in items):
                            meta = fetch_item(repo, itype, num)
                            if meta:
                                items.append(meta)
                    logging.info(
                        f"Found {len(items)} timed-out item(s) to retry in {repo}."
                    )
                else:
                    fetch_batch_size = (
                        max(100, completed_count + (args.limit * 2))
                        if args.limit > 0
                        else 0
                    )
                    items = fetch_items(repo, itype, fetch_batch_size)
                for item in items:
                    if args.limit > 0 and processed_in_type >= args.limit:
                        break

                    # Enforce concurrency throttling: wait if active agents >= concurrency limit
                    while (
                        args.concurrency > 0
                        and len(pending_subagents) >= args.concurrency
                    ):
                        finished_keys = []
                        for item_key, (result_file, aid) in pending_subagents.items():
                            if result_file.exists():
                                logging.info(
                                    f"Agent[{aid}] Finished investigation for {item_key}."
                                )
                                cleanup_item_worktrees(result_file.parent)
                                finished_keys.append(item_key)

                        for item_key in finished_keys:
                            del pending_subagents[item_key]

                        if finished_keys and pending_subagents:
                            logging.info(
                                f"Waiting for {len(pending_subagents)} remaining agent(s)..."
                            )

                        if len(pending_subagents) >= args.concurrency:
                            sync_results(args.output_dir, status_data)
                            time.sleep(3)

                    is_reinvestigate = item.get("number") in reinvestigate_nums
                    repo_short = get_short_repo_name(repo)
                    item_key = f"{repo_short}:{itype}:{item.get('number')}"
                    existing = status_data["items"].get(item_key, {})
                    existing_status = existing.get("status")
                    should_force = args.force or is_reinvestigate or args.retry_timeout_only
                    will_process = should_force or (
                        existing_status != "completed"
                        and (
                            existing_status not in ("failed", "timeout")
                            or args.retry_failed
                        )
                    )

                    if will_process and skipped_in_type > 0:
                        logging.info(f"Skipped {skipped_in_type} already completed/investigated issue(s).")
                        skipped_in_type = 0

                    current_agent_id = None
                    if will_process:
                        agent_counter += 1
                        current_agent_id = agent_counter

                    did_process, pending_file = process_item(
                        item=item,
                        repo=repo,
                        item_type=itype,
                        output_dir=args.output_dir,
                        skill_dir=args.skill_dir,
                        timeout=args.timeout,
                        status_data=status_data,
                        dry_run=args.dry_run,
                        retry_failed=args.retry_failed or args.retry_timeout_only,
                        force=args.force,
                        reinvestigate=is_reinvestigate,
                        fast_mode=args.fast,
                        agent_id=current_agent_id,
                    )
                    if did_process:
                        processed_any = True
                        processed_in_type += 1
                    else:
                        skipped_in_type += 1

                    if pending_file and current_agent_id is not None:
                        repo_short = get_short_repo_name(repo)
                        item_key = f"{repo_short}:{itype}:{item.get('number')}"
                        pending_subagents[item_key] = (pending_file, current_agent_id)

                if skipped_in_type > 0:
                    logging.info(f"Skipped {skipped_in_type} already completed/investigated issue(s).")

        if pending_subagents and not args.no_wait:
            wait_for_pending_subagents(
                pending_subagents, args.timeout, args.output_dir, status_data
            )

        if not args.loop:
            logging.info("Batch iteration finished. Exiting.")
            break

        if not processed_any:
            logging.info(
                "No new items to process right now. "
                f"Sleeping for {format_duration(args.sleep_interval)}..."
            )
        else:
            logging.info(
                f"Completed iteration pass. Pausing {format_duration(args.sleep_interval)} "
                "before next check..."
            )
        time.sleep(args.sleep_interval)

    return 0


if __name__ == "__main__":
    sys.exit(main())
