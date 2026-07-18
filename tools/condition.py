"""The rule condition grammar (see FORMAT.md): parser, group extraction,
evaluation, and the derived readable-predicate renderer.

Shared by tools/validate.py and tools/build_index.py. Deliberately
dependency-free.

    condition   ::= disjunction
    disjunction ::= conjunction ( "or" conjunction )*
    conjunction ::= negation ( "and" negation )*
    negation    ::= "not" negation | atom
    atom        ::= selector | "(" condition ")"
    selector    ::= ( "all" | INTEGER ) "of" GROUP_NAME
"""

from __future__ import annotations

import re

KEYWORDS = {"all", "of", "and", "or", "not"}
GROUP_NAME_RE = re.compile(r"[a-z][a-z0-9_]*$")
# Positional / non-descriptive group names the lint rejects.
LAZY_GROUP_NAME_RE = re.compile(r"(g|grp|group|sel|selection)_?\d*$")


class ConditionError(ValueError):
    pass


def tokenize(condition: str) -> list[str]:
    tokens = condition.replace("(", " ( ").replace(")", " ) ").split()
    for t in tokens:
        if t in KEYWORDS or t in "()" or t.isdigit() or GROUP_NAME_RE.match(t):
            continue
        raise ConditionError(f"bad token {t!r}")
    return tokens


def parse(condition: str):
    """Parse into an AST of ('or'|'and', [children]) / ('not', child) /
    ('sel', k_or_'all', group_name). Raises ConditionError."""
    tokens = tokenize(condition)
    pos = 0

    def peek():
        return tokens[pos] if pos < len(tokens) else None

    def take(expected=None):
        nonlocal pos
        if pos >= len(tokens):
            raise ConditionError(f"unexpected end of condition {condition!r}")
        tok = tokens[pos]
        if expected is not None and tok != expected:
            raise ConditionError(f"expected {expected!r}, got {tok!r}")
        pos += 1
        return tok

    def disjunction():
        children = [conjunction()]
        while peek() == "or":
            take()
            children.append(conjunction())
        return children[0] if len(children) == 1 else ("or", children)

    def conjunction():
        children = [negation()]
        while peek() == "and":
            take()
            children.append(negation())
        return children[0] if len(children) == 1 else ("and", children)

    def negation():
        if peek() == "not":
            take()
            return ("not", negation())
        return atom()

    def atom():
        if peek() == "(":
            take()
            node = disjunction()
            take(")")
            return node
        return selector()

    def selector():
        quant = take()
        if quant != "all" and not quant.isdigit():
            raise ConditionError(f"expected quantifier, got {quant!r}")
        take("of")
        group = take()
        if group in KEYWORDS or not GROUP_NAME_RE.match(group):
            raise ConditionError(f"bad group name {group!r}")
        return ("sel", quant if quant == "all" else int(quant), group)

    ast = disjunction()
    if pos != len(tokens):
        raise ConditionError(f"trailing tokens in {condition!r}")
    return ast


def referenced_groups(ast, acc: set[str] | None = None) -> set[str]:
    acc = set() if acc is None else acc
    if ast[0] in ("or", "and"):
        for c in ast[1]:
            referenced_groups(c, acc)
    elif ast[0] == "not":
        referenced_groups(ast[1], acc)
    else:
        acc.add(ast[2])
    return acc


def selectors(ast, acc=None) -> list[tuple]:
    """All ('sel', quant, group) nodes in the AST."""
    acc = [] if acc is None else acc
    if ast[0] in ("or", "and"):
        for c in ast[1]:
            selectors(c, acc)
    elif ast[0] == "not":
        selectors(ast[1], acc)
    else:
        acc.append(ast)
    return acc


def contains_not(ast) -> bool:
    if ast[0] == "not":
        return True
    if ast[0] in ("or", "and"):
        return any(contains_not(c) for c in ast[1])
    return False


def evaluate(ast, groups: dict[str, list[str]], detected: frozenset[str]) -> bool:
    kind = ast[0]
    if kind == "or":
        return any(evaluate(c, groups, detected) for c in ast[1])
    if kind == "and":
        return all(evaluate(c, groups, detected) for c in ast[1])
    if kind == "not":
        return not evaluate(ast[1], groups, detected)
    _, quant, name = ast
    members = groups[name]
    k = len(members) if quant == "all" else quant
    return sum(m in detected for m in members) >= k


def render_predicate(ast, groups: dict[str, list[str]]) -> str:
    """Expand groups into the readable predicate stored in index.json:
    1 of g -> (a OR b), all of g -> (a AND b), k of g -> at least k of
    (a, b, c), not -> NOT. Single-member selectors render as the bare CE."""

    def rec(node):
        kind = node[0]
        if kind in ("or", "and"):
            joint = f" {kind.upper()} "
            parts = []
            for c in node[1]:
                s = rec(c)
                if c[0] in ("or", "and") and c[0] != kind:
                    s = f"({s})"
                parts.append(s)
            return joint.join(parts)
        if kind == "not":
            inner = rec(node[1])
            if node[1][0] in ("or", "and"):
                inner = f"({inner})"
            return f"NOT {inner}"
        _, quant, name = node
        members = groups[name]
        if len(members) == 1:
            return members[0]
        if quant == "all" or quant == len(members):
            return "(" + " AND ".join(members) + ")"
        if quant == 1:
            return "(" + " OR ".join(members) + ")"
        return f"at least {quant} of (" + ", ".join(members) + ")"

    return rec(ast)
