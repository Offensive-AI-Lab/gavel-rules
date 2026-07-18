#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6"]
# ///
"""Validate the gavel-rules library against FORMAT.md.

Checks every artifact's schema, the rule conditions, dataset shapes and
duplicates, discovery metadata, namespace manifest, and cross-references.
Exit code 0 = clean, 1 = errors (each printed as `ERROR path: message`).

Usage:
    uv run tools/validate.py                       # validate the repo
    uv run tools/validate.py --expect-owner ORG    # CI: manifest namespace
                                                   # must match ORG (skipped
                                                   # for the reserved 'gavel')
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import condition as cond

REPO = Path(__file__).resolve().parent.parent

NAME_RE = re.compile(r"[A-Za-z0-9_]+$")
NAMESPACE_RE = re.compile(r"[a-z][a-z0-9_-]*$")
TAG_RE = re.compile(r"[a-z0-9_]+(\.[a-z0-9_]+)*$")
PUBLIC_ID_RE = {
    "ce": re.compile(r"ce_[0-9a-f]{32}$"),
    "rule": re.compile(r"rule_[0-9a-f]{32}$"),
    "ruleset": re.compile(r"ruleset_[0-9a-f]{32}$"),
}
ROLES = {"directive_to_user", "llm_task", "llm_behavior", "topic"}
MESSAGE_ROLES = {"system", "user", "assistant"}
RESERVED_NAMESPACES = {"local", "gavel"}

errors: list[str] = []


def err(path, msg):
    errors.append(f"ERROR {path}: {msg}")


def load_yaml(path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        err(path, f"unparseable YAML: {e}")
        return None


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        err(path, f"unparseable JSON: {e}")
        return None


def check_provenance(doc, path):
    prov = doc.get("provenance")
    if not isinstance(prov, dict) or not prov.get("created_by"):
        err(path, "provenance.created_by is required")
        return
    if not prov.get("published_at"):
        err(path, "provenance.published_at is required")


def check_tags(doc, path):
    tags = doc.get("tags")
    if tags is None:
        return
    if not isinstance(tags, list):
        err(path, "tags must be a list")
        return
    for t in tags:
        if not isinstance(t, str) or not TAG_RE.match(t):
            err(path, f"tag {t!r} violates the grammar (lowercase dot-namespaced)")


def check_title(doc, path):
    title = doc.get("title")
    if not isinstance(title, str) or not title.strip():
        err(path, "title is required (one-line display name)")
    elif "\n" in title:
        err(path, "title must be a single line")


def split_ref(ref):
    """A cross-reference: bare, owner-qualified, or fully qualified."""
    parts = ref.split("/")
    if len(parts) == 1:
        return None, None, parts[0]
    if len(parts) == 2:
        return parts[0], None, parts[1]
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    return None, None, None


def check_ref(ref, kind, known_local, own_ns, path, what):
    ns, ref_kind, name = split_ref(ref)
    if name is None or not NAME_RE.match(name):
        err(path, f"{what}: malformed reference {ref!r}")
        return
    if ref_kind is not None and ref_kind != kind:
        err(path, f"{what}: reference {ref!r} has kind {ref_kind!r}, expected {kind!r}")
        return
    if ns is not None and not NAMESPACE_RE.match(ns):
        err(path, f"{what}: bad namespace in {ref!r}")
        return
    if ns is None or ns == own_ns:
        if name not in known_local:
            err(path, f"{what}: unknown {kind} {name!r}")
    # foreign-namespace refs can't be resolved locally; ingest checks them


def check_dataset(path, doc, kind, expected_name, expected_id, item_key, count_key):
    if doc is None:
        return
    if doc.get("schema_version") != 1:
        err(path, f"schema_version must be 1, got {doc.get('schema_version')!r}")
    for field, expected in (("ce" if kind == "ce" else "rule", expected_name),):
        if doc.get(field) != expected:
            err(path, f"{field!r} is {doc.get(field)!r}, expected {expected!r}")
    id_field = "ce_public_id" if kind == "ce" else "rule_public_id"
    if doc.get(id_field) != expected_id:
        err(path, f"{id_field} does not match the artifact's public_id")
    items = doc.get(item_key)
    if not isinstance(items, list) or not items:
        err(path, f"{item_key} must be a non-empty list")
        return
    if doc.get(count_key) != len(items):
        err(path, f"{count_key} is {doc.get(count_key)}, actual {len(items)}")
    seen = set()
    for i, convo in enumerate(items):
        if not isinstance(convo, list) or not convo:
            err(path, f"{item_key}[{i}] must be a non-empty message list")
            continue
        for m in convo:
            if not isinstance(m, dict) or set(m) != {"role", "content"}:
                err(path, f"{item_key}[{i}] has a malformed message")
                break
            if m["role"] not in MESSAGE_ROLES:
                err(path, f"{item_key}[{i}] has bad role {m['role']!r}")
                break
            if not isinstance(m["content"], str) or not m["content"].strip():
                err(path, f"{item_key}[{i}] has empty content")
                break
        key = json.dumps(convo, sort_keys=True)
        if key in seen:
            err(path, f"{item_key}[{i}] is an exact duplicate of an earlier entry")
        seen.add(key)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--expect-owner", metavar="ORG",
                    help="require manifest namespace to match this GitHub owner "
                         "(reserved namespace 'gavel' is exempt)")
    args = ap.parse_args()

    # --- manifest ---------------------------------------------------------
    own_ns = None
    manifest_path = REPO / "gavel.yaml"
    if not manifest_path.exists():
        err(manifest_path, "repo manifest gavel.yaml is missing")
    else:
        manifest = load_yaml(manifest_path)
        if manifest:
            own_ns = manifest.get("namespace")
            if not own_ns or not NAMESPACE_RE.match(str(own_ns)):
                err(manifest_path, f"bad namespace {own_ns!r}")
            elif own_ns == "local":
                err(manifest_path, "namespace 'local' is reserved and never publishable")
            if manifest.get("schema_version") != 1:
                err(manifest_path, "manifest schema_version must be 1")
            if (args.expect_owner and own_ns
                    and own_ns not in RESERVED_NAMESPACES
                    and own_ns != args.expect_owner.lower()):
                err(manifest_path,
                    f"namespace {own_ns!r} does not match repo owner {args.expect_owner!r}")

    # --- categories -------------------------------------------------------
    cats_doc = load_yaml(REPO / "categories.yaml") or {}
    taxonomy = set()
    for entry in cats_doc.get("categories", []):
        if not isinstance(entry, dict) or not entry.get("name") or not entry.get("description"):
            err("categories.yaml", f"malformed entry {entry!r}")
            continue
        taxonomy.add(entry["name"])

    # --- CEs --------------------------------------------------------------
    seen_public_ids = {}
    ce_names = {p.name for p in (REPO / "ces").iterdir() if p.is_dir()}
    for d in sorted((REPO / "ces").iterdir()):
        if not d.is_dir():
            continue
        path = d / "ce.yaml"
        if not path.exists():
            err(path, "missing")
            continue
        ce = load_yaml(path)
        if not ce:
            continue
        rel = path.relative_to(REPO)
        if ce.get("name") != d.name:
            err(rel, f"name {ce.get('name')!r} != directory {d.name!r}")
        if not NAME_RE.match(d.name):
            err(rel, f"bad artifact name {d.name!r}")
        pid = ce.get("public_id", "")
        if not PUBLIC_ID_RE["ce"].match(str(pid)):
            err(rel, f"bad public_id {pid!r}")
        elif pid in seen_public_ids:
            err(rel, f"public_id also used by {seen_public_ids[pid]}")
        else:
            seen_public_ids[pid] = str(rel)
        if ce.get("schema_version") != 1:
            err(rel, f"ce schema_version must be 1, got {ce.get('schema_version')!r}")
        if ce.get("role") not in ROLES:
            err(rel, f"role {ce.get('role')!r} not in {sorted(ROLES)}")
        for unsupported in ("type", "categories"):
            if unsupported in ce:
                err(rel, f"unsupported field {unsupported!r} present; use role instead")
        check_title(ce, rel)
        check_tags(ce, rel)
        if not str(ce.get("definition", "")).strip():
            err(rel, "definition is required")
        examples = ce.get("examples")
        if not isinstance(examples, list) or not examples:
            err(rel, "examples must be a non-empty list")
        else:
            for ex in examples:
                if (not isinstance(ex, dict) or set(ex) != {"input", "output"}
                        or ex["output"] not in ("YES", "NO")):
                    err(rel, f"malformed example {ex!r} (need input + output YES/NO)")
        check_provenance(ce, rel)
        for kind, count_key in (("excitation", "sample_count"), ("calibration", "sample_count")):
            ds_path = d / f"{kind}.json"
            if not ds_path.exists():
                err(ds_path.relative_to(REPO), "missing")
                continue
            ds = load_json(ds_path)
            if ds and ds.get("type") != kind:
                err(ds_path.relative_to(REPO), f"type must be {kind!r}")
            check_dataset(ds_path.relative_to(REPO), ds, "ce", d.name, pid,
                          "samples", count_key)

    # --- rules ------------------------------------------------------------
    rule_names = {p.name for p in (REPO / "rules").iterdir() if p.is_dir()}
    for d in sorted((REPO / "rules").iterdir()):
        if not d.is_dir():
            continue
        path = d / "rule.yaml"
        if not path.exists():
            err(path, "missing")
            continue
        rule = load_yaml(path)
        if not rule:
            continue
        rel = path.relative_to(REPO)
        if rule.get("name") != d.name:
            err(rel, f"name {rule.get('name')!r} != directory {d.name!r}")
        pid = rule.get("public_id", "")
        if not PUBLIC_ID_RE["rule"].match(str(pid)):
            err(rel, f"bad public_id {pid!r}")
        elif pid in seen_public_ids:
            err(rel, f"public_id also used by {seen_public_ids[pid]}")
        else:
            seen_public_ids[pid] = str(rel)
        if rule.get("schema_version") != 1:
            err(rel, f"rule schema_version must be 1, got {rule.get('schema_version')!r}")
        for unsupported in ("required", "any_of", "support"):
            if unsupported in rule:
                err(rel, f"unsupported field {unsupported!r} present; use groups + condition")
        check_title(rule, rel)
        check_tags(rule, rel)
        if not str(rule.get("definition", "")).strip():
            err(rel, "definition is required")
        rcats = rule.get("categories")
        if not isinstance(rcats, list) or not rcats:
            err(rel, "categories must be a non-empty list")
        else:
            for c in rcats:
                if c not in taxonomy:
                    err(rel, f"unknown category {c!r}")
        check_provenance(rule, rel)

        groups = rule.get("groups")
        condition = rule.get("condition")
        if not isinstance(groups, dict) or not groups:
            err(rel, "groups must be a non-empty mapping")
            groups = {}
        for gname, members in groups.items():
            if not cond.GROUP_NAME_RE.match(str(gname)) or gname in cond.KEYWORDS:
                err(rel, f"bad group name {gname!r}")
            elif cond.LAZY_GROUP_NAME_RE.match(gname):
                err(rel, f"group name {gname!r} is positional, not descriptive")
            if not isinstance(members, list) or not members:
                err(rel, f"group {gname!r} must be a non-empty CE list")
                continue
            if len(members) != len(set(members)):
                err(rel, f"group {gname!r} lists a CE twice")
            for ce_ref in members:
                check_ref(str(ce_ref), "ce", ce_names, own_ns, rel, f"group {gname!r}")
        if not isinstance(condition, str) or not condition.strip():
            err(rel, "condition is required")
        else:
            try:
                ast = cond.parse(condition)
            except cond.ConditionError as e:
                err(rel, f"condition does not parse: {e}")
            else:
                if cond.contains_not(ast):
                    err(rel, "condition uses 'not' — rejected until negation "
                             "calibration semantics ship (see FORMAT.md)")
                referenced = cond.referenced_groups(ast)
                for g in sorted(referenced - set(groups)):
                    err(rel, f"condition references undefined group {g!r}")
                for g in sorted(set(groups) - referenced):
                    err(rel, f"group {g!r} is defined but never referenced (dead group)")
                for _, quant, gname in cond.selectors(ast):
                    if gname not in groups:
                        continue
                    size = len(groups[gname])
                    if quant == "all":
                        continue
                    if quant < 1 or quant > size:
                        err(rel, f"'{quant} of {gname}' out of bounds (group has {size})")
                    elif quant == size and size > 1:
                        err(rel, f"'{quant} of {gname}' equals the group size — write 'all of {gname}'")

        tests_dir = d / "tests"
        for tname in ("positive", "negative", "positive_calibration"):
            t_path = tests_dir / f"{tname}.json"
            if not t_path.exists():
                err(t_path.relative_to(REPO), "missing")
                continue
            t = load_json(t_path)
            t_rel = t_path.relative_to(REPO)
            if t:
                if t.get("type") != tname:
                    err(t_rel, f"type must be {tname!r}")
                cfg = t.get("config")
                if not isinstance(cfg, dict) or set(cfg) != {"scenario_instructions"}:
                    err(t_rel, "config must be exactly {scenario_instructions}")
            check_dataset(t_rel, t, "rule", d.name, pid,
                          "conversations", "conversation_count")

    # --- rulesets ---------------------------------------------------------
    for path in sorted((REPO / "rulesets").glob("*.yaml")):
        rs = load_yaml(path)
        if not rs:
            continue
        rel = path.relative_to(REPO)
        if rs.get("name") != path.stem:
            err(rel, f"name {rs.get('name')!r} != filename {path.stem!r}")
        pid = rs.get("public_id", "")
        if not PUBLIC_ID_RE["ruleset"].match(str(pid)):
            err(rel, f"bad public_id {pid!r}")
        elif pid in seen_public_ids:
            err(rel, f"public_id also used by {seen_public_ids[pid]}")
        else:
            seen_public_ids[pid] = str(rel)
        if rs.get("schema_version") != 1:
            err(rel, f"ruleset schema_version must be 1")
        check_title(rs, rel)
        if not str(rs.get("description", "")).strip():
            err(rel, "description must state the inclusion criterion")
        members = rs.get("rules")
        if not isinstance(members, list) or not members:
            err(rel, "rules must be a non-empty list")
        else:
            if len(members) != len(set(members)):
                err(rel, "duplicate member rules")
            for r in members:
                check_ref(str(r), "rule", rule_names, own_ns, rel, "member")
        check_provenance(rs, rel)

    for e in errors:
        print(e, file=sys.stderr)
    n_ce, n_rule = len(ce_names), len(rule_names)
    print(f"validated {n_rule} rules, {n_ce} CEs, "
          f"{len(list((REPO / 'rulesets').glob('*.yaml')))} rulesets: "
          f"{len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
