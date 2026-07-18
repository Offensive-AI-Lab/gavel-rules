#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6"]
# ///
"""CI check: artifacts added in a PR must credit the PR author.

A newly added artifact (rule.yaml, ce.yaml, or rulesets/*.yaml) must have
`provenance.created_by` equal to the GitHub login of the PR author
(case-insensitive; GitHub logins are). Edits to existing artifacts are
exempt: created_by records the creator, not the last editor.

Usage:
    uv run tools/check_provenance.py --author LOGIN --base origin/main

Exit code 0 = clean, 1 = errors (each printed as `ERROR path: message`).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import yaml

ARTIFACT = re.compile(r"^(rules/[^/]+/rule\.yaml|ces/[^/]+/ce\.yaml|rulesets/[^/]+\.yaml)$")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--author", required=True, help="GitHub login of the PR author")
    ap.add_argument("--base", required=True, help="base ref to diff against, e.g. origin/main")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    added = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=A", f"{args.base}...HEAD"],
        cwd=root, capture_output=True, text=True, check=True,
    ).stdout.split()

    errors = 0
    checked = 0
    for rel in added:
        if not ARTIFACT.match(rel):
            continue
        checked += 1
        doc = yaml.safe_load((root / rel).read_text(encoding="utf-8")) or {}
        created = str((doc.get("provenance") or {}).get("created_by") or "")
        if created.lower() != args.author.lower():
            print(f"ERROR {rel}: provenance.created_by is {created!r}; new artifacts must credit the PR author {args.author!r}")
            errors += 1

    if errors:
        sys.exit(1)
    print(f"provenance ok: {checked} added artifact(s), created_by matches {args.author!r}")


main()
