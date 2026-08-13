#!/usr/bin/env python3
"""Utility script to filter, query, and summarize triaged Emscripten issues.

Provides clean command-line reporting and filtering for issues recommended
to be closed, along with their rationale and certainty.
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

CERTAINTY_RANKS = {"high": 3, "medium": 2, "low": 1, "unknown": 0}


def normalize_certainty(cert: Any) -> str:
    """Safely convert any certainty representation (int, float, str) to standard high/medium/low/unknown string."""
    if isinstance(cert, (int, float)):
        return "high" if cert >= 4 else ("medium" if cert >= 2 else "low")
    return str(cert or "unknown").lower()


def sync_results(status_path: Path, data: Dict[str, Any]) -> bool:
    """Scan item directories for result.json files and update data if new findings exist."""
    updated = False
    output_dir = status_path.parent
    items = data.get("items", {})
    for item_key, info in items.items():
        repo = info.get("repo", "")
        repo_short = repo.split("/")[-1] if "/" in repo else repo
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
                        rec = "close"
                    info["recommendation"] = rec
                    cert_val = payload.get("certainty")
                    if cert_val is None:
                        cert_val = "high" if rec != "unknown" else "unknown"
                    info["certainty"] = normalize_certainty(cert_val)
                    info["rationale"] = (
                        payload.get("rationale")
                        or payload.get("summary")
                        or info.get("rationale", "N/A")
                    )
                    info["actionability"] = str(payload.get("actionability", "unknown"))
                    if info.get("status") == "unknown":
                        info["status"] = "completed"
                    updated = True
            except Exception as exc:
                logging.warning(f"Error loading {result_file}: {exc}")
        elif info.get("status") in ("completed", "failed", "timeout") and str(info.get("recommendation", "")).lower() == "unknown":
            info["status"] = "timeout"
            info["recommendation"] = "investigate"
            info["certainty"] = "low"
            info["rationale"] = "Investigation timed out."
            updated = True

    if updated:
        try:
            with open(status_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, sort_keys=True)
        except Exception:
            pass
    return updated


def load_status_file(status_path: Path) -> Dict[str, Any]:
    """Load the top-level status JSON file."""
    if not status_path.exists():
        logging.error(f"Status file not found: {status_path}")
        sys.exit(1)
    try:
        with open(status_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        sync_results(status_path, data)
        return data
    except Exception as exc:
        logging.error(f"Failed to read {status_path}: {exc}")
        sys.exit(1)


def filter_items(
    items: Dict[str, Any],
    recommendation: str,
    min_certainty: str,
    repo: str,
    item_type: str,
    item_status: str = "all",
) -> List[Dict[str, Any]]:
    """Filter triaged items according to CLI criteria."""
    filtered = []
    min_rank = CERTAINTY_RANKS.get(min_certainty.lower(), 0)

    for item in items.values():
        if repo and repo not in str(item.get("repo", "")):
            continue
        if item_type != "both" and str(item.get("type", "")) != item_type:
            continue
        if (
            item_status != "all"
            and str(item.get("status", "")).lower() != item_status.lower()
        ):
            continue
        if (
            recommendation != "all"
            and str(item.get("recommendation", "")).lower() != recommendation.lower()
        ):
            continue

        item_cert = normalize_certainty(item.get("certainty"))
        if CERTAINTY_RANKS.get(item_cert, 0) < min_rank:
            continue

        filtered.append(item)

    # Sort primarily by status, then recommendation, then certainty rank (desc), then number
    filtered.sort(
        key=lambda x: (
            str(x.get("status", "")),
            str(x.get("recommendation", "")),
            -CERTAINTY_RANKS.get(normalize_certainty(x.get("certainty")), 0),
            int(x.get("number", 0)),
        )
    )
    return filtered


def print_table(items: List[Dict[str, Any]]) -> None:
    """Print a clean ASCII table of triaged items."""
    if not items:
        print("No triaged items match the filter criteria.")
        return

    # Column widths
    col_idx = 4
    col_num = 10
    col_type = 6
    col_rec = 14
    col_cert = 10
    col_rat = 50

    header = (
        f"{'#':<{col_idx}} | {'Item':<{col_num}} | {'Type':<{col_type}} | "
        f"{'Recommendation':<{col_rec}} | {'Certainty':<{col_cert}} | "
        f"{'Rationale':<{col_rat}}"
    )
    sep = "-" * len(header)
    print(header)
    print(sep)

    for idx, item in enumerate(items, 1):
        num = f"#{item.get('number', '?')}"
        itype = item.get("type", "unknown")[:col_type]
        rec = item.get("recommendation", "unknown")[:col_rec]
        cert = item.get("certainty", "unknown")[:col_cert]
        status = item.get("status", "")
        rat = (item.get("rationale") or "N/A").replace("\n", " ").strip()
        if status == "timeout" and (rat == "N/A" or not rat):
            rat = "(Investigation timed out)"
        elif (rat == "N/A" or not rat) and rec == "unknown":
            rat = "(Sub-agent investigating...)"
        if len(rat) > col_rat:
            rat = rat[: col_rat - 3] + "..."
        print(
            f"{idx:<{col_idx}} | {num:<{col_num}} | {itype:<{col_type}} | "
            f"{rec:<{col_rec}} | {cert:<{col_cert}} | "
            f"{rat:<{col_rat}}"
        )


def print_summary(items: List[Dict[str, Any]], show_history: bool = False) -> None:
    """Print detailed multi-line summaries for each matching item."""
    if not items:
        print("No triaged items match the filter criteria.")
        return

    for item in items:
        print(f"=== Item #{item.get('number')}: {item.get('title')} ===")
        print(f"Repository:     {item.get('repo')}")
        print(f"Type:           {item.get('type')}")
        print(f"Status:         {item.get('status')}")
        print(f"Recommendation: {item.get('recommendation', '').upper()}")
        print(f"Certainty:      {item.get('certainty', '').upper()}")
        print(f"Actionability:  {item.get('actionability')}")
        print(f"URL:            {item.get('url')}")
        print(f"Processed At:   {item.get('processed_at')}")
        print("\nRationale:")
        print(f"  {item.get('rationale', 'N/A')}")

        history = item.get("history", [])
        if history:
            print(f"\nPrior Run History ({len(history)} past run(s)):")
            for run_idx, past in enumerate(history, 1):
                print(f"  Run #{run_idx} [{past.get('processed_at')}]: Rec={past.get('recommendation')} | Certainty={past.get('certainty')}")
                print(f"    Rationale: {past.get('rationale')}")

        print("\n" + "-" * 72)


def main() -> int:
    """Parse CLI arguments and report on triaged items."""
    parser = argparse.ArgumentParser(
        description="Filter and summarize triaged Emscripten issues and PRs."
    )
    parser.add_argument(
        "--status-file",
        "-s",
        type=Path,
        default=Path("issues/status.json"),
        help="Path to status.json (default: issues/status.json)",
    )
    parser.add_argument(
        "--recommendation",
        "-r",
        default="all",
        choices=["close", "investigate", "reproduced", "needs_info", "unknown", "all"],
        help="Filter by recommendation (default: all)",
    )
    parser.add_argument(
        "--min-certainty",
        "-c",
        default="unknown",
        choices=["high", "medium", "low", "unknown"],
        help="Minimum certainty level to include (default: unknown)",
    )
    parser.add_argument(
        "--status",
        choices=["completed", "failed", "timeout", "archived", "all"],
        default="all",
        help="Filter by execution status (default: all)",
    )
    parser.add_argument(
        "--repo",
        default="",
        help="Filter by repository name substring",
    )
    parser.add_argument(
        "--type",
        choices=["issue", "pr", "both"],
        default="both",
        help="Filter by item type (default: both)",
    )
    parser.add_argument(
        "--format",
        "-f",
        choices=["table", "summary", "json"],
        default="table",
        help="Output format (default: table)",
    )

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    data = load_status_file(args.status_file)
    items_dict = data.get("items", {})
    filtered = filter_items(
        items_dict,
        args.recommendation,
        args.min_certainty,
        args.repo,
        args.type,
        args.status,
    )

    if args.format == "table":
        print_table(filtered)
    elif args.format == "summary":
        print_summary(filtered)
    elif args.format == "json":
        print(json.dumps(filtered, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
