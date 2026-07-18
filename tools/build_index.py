#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6"]
# ///
"""Build index.json — the generated one-file catalog of the library.

Deterministic and reproducible: content hashes are computed from artifact
file bytes, and global_signature is a digest over every artifact hash plus
the shared files, so the same tree always yields byte-identical output.

Usage:
    uv run tools/build_index.py            # rewrite index.json
    uv run tools/build_index.py --check    # exit 1 if index.json is stale
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import condition as cond

REPO = Path(__file__).resolve().parent.parent
INDEX = REPO / "index.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dir_hash(d: Path) -> str:
    """Hash of an artifact directory: digest over (relpath, filehash) pairs."""
    h = hashlib.sha256()
    for f in sorted(d.rglob("*")):
        if f.is_file():
            h.update(f.relative_to(d).as_posix().encode())
            h.update(sha256_file(f).encode())
    return h.hexdigest()


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def sample_count(path: Path, key: str) -> int:
    return json.loads(path.read_text(encoding="utf-8")).get(key, 0)


def build() -> dict:
    manifest = load_yaml(REPO / "gavel.yaml")
    categories = load_yaml(REPO / "categories.yaml")["categories"]

    ces = {}
    for d in sorted((REPO / "ces").iterdir()):
        if not d.is_dir():
            continue
        ce = load_yaml(d / "ce.yaml")
        ces[ce["name"]] = {
            "title": ce["title"],
            "role": ce["role"],
            "public_id": ce["public_id"],
            "tags": ce.get("tags", []),
            "definition": ce["definition"].strip(),
            "examples": ce.get("examples", []),
            "published_at": ce["provenance"]["published_at"],
            "by": ce["provenance"]["created_by"],
            "path": f"ces/{ce['name']}",
            "calibration": f"ces/{ce['name']}/calibration.json",
            "excitation": f"ces/{ce['name']}/excitation.json",
            "calibration_samples": sample_count(d / "calibration.json", "sample_count"),
            "excitation_samples": sample_count(d / "excitation.json", "sample_count"),
            "used_by": [],
            "content_hash": dir_hash(d),
        }

    rules = {}
    for d in sorted((REPO / "rules").iterdir()):
        if not d.is_dir():
            continue
        rule = load_yaml(d / "rule.yaml")
        ast = cond.parse(rule["condition"])
        deps = sorted({ce for g in rule["groups"].values() for ce in g})
        name = rule["name"]
        rules[name] = {
            "title": rule["title"],
            "public_id": rule["public_id"],
            "categories": rule["categories"],
            "tags": rule.get("tags", []),
            "definition": rule["definition"].strip(),
            "groups": rule["groups"],
            "condition": rule["condition"],
            "predicate": cond.render_predicate(ast, rule["groups"]),
            "ces": deps,
            "published_at": rule["provenance"]["published_at"],
            "by": rule["provenance"]["created_by"],
            "path": f"rules/{name}",
            "tests": {t: f"rules/{name}/tests/{t}.json"
                      for t in ("positive", "negative", "positive_calibration")},
            "content_hash": dir_hash(d),
        }
        for ce_name in deps:
            if ce_name in ces:
                ces[ce_name]["used_by"].append(name)

    rulesets = {}
    for f in sorted((REPO / "rulesets").glob("*.yaml")):
        rs = load_yaml(f)
        member_cats = sorted({c for r in rs["rules"] if r in rules
                              for c in rules[r]["categories"]})
        rulesets[rs["name"]] = {
            "title": rs["title"],
            "public_id": rs["public_id"],
            "description": rs["description"],
            "rules": rs["rules"],
            "categories": member_cats,
            "published_at": rs["provenance"]["published_at"],
            "by": rs["provenance"]["created_by"],
            "path": f"rulesets/{rs['name']}.yaml",
            "content_hash": sha256_file(f),
        }

    sig = hashlib.sha256()
    for kind, coll in (("ce", ces), ("rule", rules), ("ruleset", rulesets)):
        for name in sorted(coll):
            sig.update(f"{kind}/{name}:{coll[name]['content_hash']}\n".encode())
    for shared in ("categories.yaml", "gavel.yaml"):
        sig.update(f"{shared}:{sha256_file(REPO / shared)}\n".encode())

    return {
        "schema_version": 1,
        "generated_by": "tools/build_index.py",
        "namespace": manifest["namespace"],
        "global_signature": f"v1:{sig.hexdigest()}",
        "counts": {"rules": len(rules), "ces": len(ces), "rulesets": len(rulesets)},
        "categories": categories,
        "rulesets": rulesets,
        "rules": rules,
        "ces": ces,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="verify index.json matches the tree; write nothing")
    args = ap.parse_args()

    rendered = json.dumps(build(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        current = INDEX.read_text(encoding="utf-8") if INDEX.exists() else ""
        if current != rendered:
            print("index.json is stale — run: uv run tools/build_index.py",
                  file=sys.stderr)
            return 1
        print("index.json is up to date")
        return 0
    INDEX.write_text(rendered, encoding="utf-8")
    print(f"wrote index.json ({len(rendered)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
