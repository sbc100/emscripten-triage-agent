#!/usr/bin/env python3
"""Interactive review tool to inspect triage findings and apply GitHub actions.

Displays issue details, investigation summaries, and suggested comments/close
actions, prompting for user approval before applying changes via `gh`.
"""

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any, Optional

from summarize_status import CERTAINTY_RANKS, load_status_file, normalize_certainty


def get_short_repo_name(repo: str) -> str:
    """Extract short repository name."""
    return repo.split("/")[-1] if "/" in repo else repo


def run_command(
    cmd: list[str], check: bool = True, env: Optional[dict[str, str]] = None
) -> subprocess.CompletedProcess:
    """Execute system command with output capture."""
    return subprocess.run(
        cmd, capture_output=True, text=True, check=check, env=env
    )


def load_item_artifacts(
    output_dir: Path, repo: str, itype: str, number: int
) -> tuple[dict[str, Any], str]:
    """Load the latest result.json payload and investigation.md narrative."""
    repo_short = get_short_repo_name(repo)
    item_dir = output_dir / repo_short / itype / str(number)
    result_payload: dict[str, Any] = {}
    investigation_text = ""

    # Check root result.json, then fallback to latest in history/
    result_file = item_dir / "result.json"
    if not result_file.exists() and (item_dir / "history").exists():
        history_results = sorted((item_dir / "history").glob("run_*/result.json"))
        if history_results:
            result_file = history_results[-1]

    if result_file.exists():
        try:
            with open(result_file, "r", encoding="utf-8") as f:
                result_payload = json.load(f)
        except Exception as exc:
            logging.debug(f"Failed to read {result_file}: {exc}")

    # Check root investigation.md, then fallback to latest in history/
    inv_file = item_dir / "investigation.md"
    if not inv_file.exists() and (item_dir / "history").exists():
        history_invs = sorted((item_dir / "history").glob("run_*/investigation.md"))
        if history_invs:
            inv_file = history_invs[-1]

    if inv_file.exists():
        try:
            investigation_text = inv_file.read_text(encoding="utf-8")
        except Exception as exc:
            logging.debug(f"Failed to read {inv_file}: {exc}")

    return result_payload, investigation_text


def edit_text_in_editor(initial_text: str) -> str:
    """Open initial_text in user's $EDITOR for manual adjustments."""
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"
    if not shutil.which(editor):
        editor = "vim" if shutil.which("vim") else "vi"

    with tempfile.NamedTemporaryFile(suffix=".md", mode="w+", delete=False) as tf:
        tf.write(initial_text)
        tf_path = tf.name

    try:
        subprocess.run([editor, tf_path], check=True)
        with open(tf_path, "r", encoding="utf-8") as f:
            edited = f.read().strip()
        return edited
    except Exception as exc:
        print(f"Error opening editor ({editor}): {exc}")
        return initial_text
    finally:
        if os.path.exists(tf_path):
            os.unlink(tf_path)


def determine_close_reason(recommendation: str) -> str:
    """Determine GitHub close reason ('completed' vs 'not_planned')."""
    rec = recommendation.lower()
    if rec in ("close/fixed", "close/implemented", "close/resolved"):
        return "completed"
    if rec in ("close/invalid", "close/duplicate", "close/obsolete", "close/unreproducible"):
        return "not_planned"
    return "completed"


def generate_default_comment(
    recommendation: str, rationale: str, payload: dict[str, Any]
) -> str:
    """Generate or retrieve the recommended GitHub comment."""
    suggested = payload.get("suggested_close_comment")
    if suggested and suggested.strip():
        return suggested.strip()

    rec = recommendation.lower()
    if rec.startswith("close/fixed"):
        commit = payload.get("bisected_commit")
        ref_msg = f" (commit/PR {commit})" if commit else ""
        return f"This issue appears to be resolved on current `main`{ref_msg}.\n\n{rationale}\n\nClosing as resolved."
    if rec.startswith("close/implemented"):
        return f"The requested feature has been implemented in Emscripten.\n\n{rationale}\n\nClosing as completed."
    if rec.startswith("close/invalid"):
        return f"Closing this issue based on triage review.\n\n{rationale}"
    if rec.startswith("close/duplicate"):
        return f"Closing as duplicate.\n\n{rationale}"
    if rec.startswith("close/obsolete"):
        return f"Closing this issue as it concerns obsolete/deprecated architectures.\n\n{rationale}"
    if rec.startswith("close/unreproducible"):
        return f"Closing as unreproducible due to lack of reproduction details and inactivity.\n\n{rationale}"
    if rec == "reproduced":
        return f"**Triage Update**: Confirmed that this issue reproduces on current `main`.\n\n{rationale}"
    if rec == "needs_info":
        return f"**Triage Request**: Could you please provide a self-contained reproduction case or the full compiler command flags?\n\n{rationale}"

    return rationale or "Triage investigation completed."


def apply_github_action(
    repo: str,
    itype: str,
    number: int,
    action: str,
    comment: str,
    close_reason: str = "completed",
    dry_run: bool = False,
) -> bool:
    """Execute GitHub action via `gh` CLI."""
    subcmd = "issue" if itype == "issue" else "pr"
    success = True

    if action in ("close_with_comment", "close_only"):
        cmd = ["gh", subcmd, "close", str(number), "--repo", repo]
        if close_reason:
            cmd.extend(["--reason", close_reason])
        if action == "close_with_comment" and comment:
            cmd.extend(["--comment", comment])

        print(f"\n[EXEC] {' '.join(cmd)}")
        if not dry_run:
            res = run_command(cmd, check=False)
            if res.returncode == 0:
                print(f"✓ Successfully closed {repo}#{number} ({close_reason}).")
            else:
                print(f"✗ Failed to close {repo}#{number}: {res.stderr.strip()}")
                success = False
        else:
            print(f"[DRY-RUN] Would close {repo}#{number} with reason '{close_reason}'.")

    elif action == "comment_only":
        if not comment:
            print("No comment provided. Skipping comment action.")
            return True
        cmd = ["gh", subcmd, "comment", str(number), "--repo", repo, "--body", comment]
        print(f"\n[EXEC] {' '.join(cmd)}")
        if not dry_run:
            res = run_command(cmd, check=False)
            if res.returncode == 0:
                print(f"✓ Successfully posted comment to {repo}#{number}.")
            else:
                print(f"✗ Failed to comment on {repo}#{number}: {res.stderr.strip()}")
                success = False
        else:
            print(f"[DRY-RUN] Would comment on {repo}#{number}.")

    return success


def print_banner(text: str, char: str = "=") -> None:
    """Print visually distinct section divider banner."""
    width = min(80, shutil.get_terminal_size().columns)
    print(f"\n{char * width}")
    print(f"  {text}")
    print(f"{char * width}\n")


def review_item(
    item: dict[str, Any], output_dir: Path, dry_run: bool = False
) -> str:
    """Interactively display an item and prompt for action. Returns 'applied', 'skipped', or 'quit'."""
    repo = item.get("repo", "emscripten-core/emscripten")
    itype = item.get("type", "issue")
    number = int(item.get("number", 0))
    title = item.get("title", "No title")
    url = item.get("url") or f"https://github.com/{repo}/{itype}s/{number}"
    recommendation = item.get("recommendation", "unknown")
    certainty = normalize_certainty(item.get("certainty"))
    rationale = item.get("rationale", "N/A")

    payload, investigation_text = load_item_artifacts(output_dir, repo, itype, number)
    if payload:
        recommendation = payload.get("recommendation", recommendation)
        certainty = normalize_certainty(payload.get("certainty", certainty))
        rationale = payload.get("rationale") or rationale

    proposed_comment = generate_default_comment(recommendation, rationale, payload)
    is_close_rec = recommendation.lower() == "close" or recommendation.lower().startswith("close/")
    close_reason = determine_close_reason(recommendation) if is_close_rec else "completed"

    print_banner(f"[{itype.upper()}] #{number}: {title}")
    print(f"• URL:            {url}")
    print(f"• Recommendation: {recommendation.upper()} (Certainty: {certainty.upper()})")
    print(f"• Summary:        {rationale}")

    if is_close_rec:
        print(f"• Proposed Action: CLOSE {itype.upper()} (reason: {close_reason}) with comment")
    else:
        print(f"• Proposed Action: POST TRIAGE COMMENT ({recommendation})")

    print("\n--- Proposed Comment ---")
    wrapped_comment = "\n".join(textwrap.wrap(proposed_comment, width=78)) if proposed_comment else "(None)"
    print(wrapped_comment)
    print("------------------------\n")

    current_comment = proposed_comment

    while True:
        prompt_options = (
            "[y] Apply proposed action\n"
            "[e] Edit comment in editor\n"
            "[c] Post comment only (do not close)\n"
            "[v] View full investigation narrative\n"
            "[s] Skip this item\n"
            "[q] Quit review\n"
            "Select option [y/e/c/v/s/q]: "
        )
        try:
            choice = input(prompt_options).strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            return "quit"

        if choice in ("y", "yes"):
            action = "close_with_comment" if is_close_rec else "comment_only"
            ok = apply_github_action(
                repo=repo,
                itype=itype,
                number=number,
                action=action,
                comment=current_comment,
                close_reason=close_reason,
                dry_run=dry_run,
            )
            return "applied" if ok else "skipped"

        elif choice in ("e", "edit"):
            current_comment = edit_text_in_editor(current_comment)
            print("\n--- Updated Comment ---")
            print(current_comment)
            print("-----------------------\n")

        elif choice in ("c", "comment"):
            ok = apply_github_action(
                repo=repo,
                itype=itype,
                number=number,
                action="comment_only",
                comment=current_comment,
                dry_run=dry_run,
            )
            return "applied" if ok else "skipped"

        elif choice in ("v", "view"):
            print_banner(f"Full Investigation Narrative: #{number}", char="-")
            if investigation_text.strip():
                print(investigation_text.strip())
            else:
                print("No investigation.md narrative recorded for this run.")
            print_banner("End of Investigation Narrative", char="-")

        elif choice in ("s", "skip", "n", "no"):
            print(f"Skipped #{number}.")
            return "skipped"

        elif choice in ("q", "quit", "exit"):
            print("Exiting review tool.")
            return "quit"
        else:
            print("Invalid option. Please enter y, e, c, v, s, or q.")


def main() -> int:
    """Parse CLI arguments and run interactive triage review."""
    parser = argparse.ArgumentParser(
        description="Interactively review Emscripten triage results and apply actions via GitHub CLI."
    )
    parser.add_argument(
        "--status-file",
        "-s",
        type=Path,
        default=Path("issues/status.json"),
        help="Path to status.json file (default: issues/status.json)",
    )
    parser.add_argument(
        "--recommendation",
        "-r",
        default="close",
        help="Filter by recommendation (e.g. close, close/fixed, close/invalid, reproduced, all; default: close)",
    )
    parser.add_argument(
        "--min-certainty",
        "-c",
        default="high",
        choices=["high", "medium", "low", "unknown"],
        help="Minimum certainty level to include (default: high)",
    )
    parser.add_argument(
        "--numbers",
        "-n",
        nargs="+",
        help="Specific issue or PR number(s) to review (e.g. -n 4952 7024)",
    )
    parser.add_argument(
        "--repo",
        default="",
        help="Filter by repository name substring",
    )
    parser.add_argument(
        "--type",
        choices=["issue", "pr", "both"],
        default="issue",
        help="Filter by item type (default: issue)",
    )
    parser.add_argument(
        "--limit",
        "-l",
        type=int,
        default=0,
        help="Maximum number of items to review (default: all matching)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate actions and print `gh` command lines without executing",
    )

    args = parser.parse_args()
    status_path = args.status_file
    output_dir = status_path.parent

    status_data = load_status_file(status_path)
    items = status_data.get("items", {})
    if not items:
        print("No items found in status file.")
        return 0

    target_numbers = set()
    if args.numbers:
        for arg in args.numbers:
            for part in str(arg).split(","):
                part = part.strip("# ").strip()
                if part.isdigit():
                    target_numbers.add(int(part))

    # Filter items
    candidates = []
    min_rank = CERTAINTY_RANKS.get(args.min_certainty.lower(), 0)

    for item in items.values():
        num = int(item.get("number", 0))
        if target_numbers and num not in target_numbers:
            continue
        if args.repo and args.repo not in str(item.get("repo", "")):
            continue
        if args.type != "both" and str(item.get("type", "")) != args.type:
            continue

        item_cert = normalize_certainty(item.get("certainty"))
        if CERTAINTY_RANKS.get(item_cert, 0) < min_rank:
            continue

        if args.recommendation != "all":
            rec_query = args.recommendation.lower()
            item_rec = str(item.get("recommendation", "")).lower()
            if rec_query == "close":
                if not (item_rec == "close" or item_rec.startswith(("close/", "close:"))):
                    continue
            elif item_rec != rec_query:
                continue

        candidates.append(item)

    # Sort primarily by recommendation, then certainty (desc), then number (asc)
    candidates.sort(
        key=lambda x: (
            str(x.get("recommendation", "")),
            -CERTAINTY_RANKS.get(normalize_certainty(x.get("certainty")), 0),
            int(x.get("number", 0)),
        )
    )

    if args.limit > 0:
        candidates = candidates[: args.limit]

    if not candidates:
        print(
            f"No triaged items match the filter criteria (recommendation: {args.recommendation}, "
            f"min-certainty: {args.min_certainty})."
        )
        return 0

    print_banner(f"Triage Interactive Review: {len(candidates)} item(s) to review")
    if args.dry_run:
        print(">>> DRY-RUN MODE ACTIVE: No actual changes will be sent to GitHub <<<\n")

    applied_count = 0
    skipped_count = 0

    for idx, item in enumerate(candidates, 1):
        print(f"\n[{idx}/{len(candidates)}] Processing Item...")
        res = review_item(item, output_dir, dry_run=args.dry_run)
        if res == "quit":
            break
        elif res == "applied":
            applied_count += 1
        else:
            skipped_count += 1

    print_banner(
        f"Review Session Finished: {applied_count} action(s) applied, "
        f"{skipped_count} skipped, {len(candidates) - (applied_count + skipped_count)} remaining."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
