"""W3C-style EBNF subset: parse, filter by version, match SQL token streams.

Grammar syntax (compatible with https://www.bottlecaps.de/rr/ui):
    rule      ::= expression
    expression: alternatives separated by '|', items in sequence,
                items are 'keyword' / "punct", rule references, ( groups ),
                followed by an optional ?, * or +.
    comments  /* ... */ are ignored, except version annotations:
              /* @since 8.0.13 */  /* @until 10.6 */  /* @since 10.2 @until 11 */
              which apply to the single item that follows (wrap sequences in parens).

Built-in terminals (not defined in grammar files):
    identifier      unquoted word that is not a keyword of this grammar, or a quoted identifier
    string_literal  quoted string as defined by the engine's lexical spec
    integer         digits
    expression      non-empty, parenthesis-balanced token run without top-level ','
                    (a deliberately loose stand-in for a full expression grammar)

AST nodes are tuples:
    ("seq", [nodes]) ("alt", [nodes]) ("opt", node) ("star", node) ("plus", node)
    ("kw", text) ("punct", text) ("ref", name) ("ver", {"since"/"until"}, node)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .specs import in_range

BUILTINS = ("identifier", "string_literal", "integer", "expression")


class GrammarError(ValueError):
    pass


# --- grammar parsing --------------------------------------------------------

_EBNF_TOKEN = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<comment>/\*.*?\*/)
  | (?P<define>::=)
  | (?P<quoted>'[^']*'|"[^"]*")
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>[()|?*+])
    """,
    re.S | re.X,
)
_ANNOTATION = re.compile(r"@(since|until)\s+([0-9]+(?:\.[0-9]+){0,2})")


def _ebnf_tokens(text: str):
    pos = 0
    out = []
    while pos < len(text):
        m = _EBNF_TOKEN.match(text, pos)
        if not m:
            line = text.count("\n", 0, pos) + 1
            raise GrammarError(f"line {line}: unexpected {text[pos:pos + 20]!r}")
        kind = m.lastgroup
        value = m.group(kind)
        if kind == "comment":
            ann = dict(_ANNOTATION.findall(value))
            if ann:
                out.append(("ann", ann))
        elif kind != "ws":
            out.append((kind, value))
        pos = m.end()
    return out


@dataclass
class Grammar:
    rules: dict[str, tuple]
    order: list[str]

    def keywords(self) -> set[str]:
        found: set[str] = set()

        def walk(n):
            if n[0] == "kw":
                found.add(n[1])
            elif n[0] in ("seq", "alt"):
                for c in n[1]:
                    walk(c)
            elif n[0] in ("opt", "star", "plus"):
                walk(n[1])
            elif n[0] == "ver":
                walk(n[2])

        for r in self.rules.values():
            walk(r)
        return found

    def references(self) -> set[str]:
        found: set[str] = set()

        def walk(n):
            if n[0] == "ref":
                found.add(n[1])
            elif n[0] in ("seq", "alt"):
                for c in n[1]:
                    walk(c)
            elif n[0] in ("opt", "star", "plus"):
                walk(n[1])
            elif n[0] == "ver":
                walk(n[2])

        for r in self.rules.values():
            walk(r)
        return found

    def undefined(self) -> set[str]:
        return {r for r in self.references() if r not in self.rules and r not in BUILTINS}

    def for_version(self, version: str) -> "Grammar":
        return Grammar({k: filter_version(v, version) or ("seq", []) for k, v in self.rules.items()}, self.order)


def parse_grammar(text: str) -> Grammar:
    toks = _ebnf_tokens(text)
    rules: dict[str, tuple] = {}
    order: list[str] = []
    i = 0

    def peek(k=0):
        return toks[i + k] if i + k < len(toks) else (None, None)

    def at_rule_start():
        return peek()[0] == "name" and peek(1)[0] == "define"

    def parse_alt():
        nonlocal i
        alts = [parse_seq()]
        while peek() == ("op", "|"):
            i += 1
            alts.append(parse_seq())
        return alts[0] if len(alts) == 1 else ("alt", alts)

    def parse_seq():
        nonlocal i
        items = []
        while True:
            kind, val = peek()
            if kind is None or at_rule_start() or (kind == "op" and val in "|)"):
                break
            ann = None
            if kind == "ann":
                ann = val
                i += 1
            item = parse_item()
            items.append(("ver", ann, item) if ann else item)
        return items[0] if len(items) == 1 else ("seq", items)

    def parse_item():
        nonlocal i
        kind, val = peek()
        if kind == "quoted":
            text = val[1:-1]
            node = ("kw", text.upper()) if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", text) else ("punct", text)
            i += 1
        elif kind == "name":
            node = ("ref", val)
            i += 1
        elif (kind, val) == ("op", "("):
            i += 1
            node = parse_alt()
            if peek() != ("op", ")"):
                raise GrammarError(f"expected ')' near token {i}: {peek()}")
            i += 1
        else:
            raise GrammarError(f"unexpected token {peek()}")
        kind, val = peek()
        if kind == "op" and val in "?*+":
            i += 1
            node = ({"?": "opt", "*": "star", "+": "plus"}[val], node)
        return node

    while i < len(toks):
        if not at_rule_start():
            raise GrammarError(f"expected 'name ::=' but got {peek()}")
        name = peek()[1]
        i += 2
        if name in rules:
            raise GrammarError(f"rule '{name}' defined twice")
        rules[name] = parse_alt()
        order.append(name)
    return Grammar(rules, order)


def filter_version(node, version: str):
    """Remove items whose annotation excludes `version`. Returns None if nothing is left."""
    kind = node[0]
    if kind == "ver":
        return filter_version(node[2], version) if in_range(version, node[1]) else None
    if kind == "seq":
        kids = [k for k in (filter_version(c, version) for c in node[1]) if k is not None]
        return ("seq", kids)
    if kind == "alt":
        kids = [k for k in (filter_version(c, version) for c in node[1]) if k is not None]
        if not kids:
            return None
        return kids[0] if len(kids) == 1 else ("alt", kids)
    if kind in ("opt", "star"):
        inner = filter_version(node[1], version)
        return (kind, inner) if inner is not None else ("seq", [])
    if kind == "plus":
        inner = filter_version(node[1], version)
        return ("plus", inner) if inner is not None else None
    return node


# --- SQL tokenizer (driven by the lexical spec) -----------------------------

@dataclass(frozen=True)
class Tok:
    kind: str  # word | qident | string | number | punct
    text: str


_PUNCT2 = ("<=", ">=", "<>", "!=", "::", "||", "->")


def _active(entry: dict) -> bool:
    """Quote rule applies with default session settings."""
    if "prefix" in entry:
        return False
    when = entry.get("when")
    return when is None or when.get("effect") == "disables"


def tokenize(sql: str, lexical: dict) -> list[Tok]:
    ident_quotes = [q for q in lexical["identifiers"]["quotes"] if _active(q)]
    string_quotes = [q for q in lexical["strings"] if _active(q) and q.get("kind") == "string"]
    line_comments = [c["open"].strip() for c in lexical["comments"] if c["kind"] == "line"]
    out: list[Tok] = []
    i, n = 0, len(sql)

    def read_quoted(q):
        nonlocal i
        close = q["close"]
        esc = q.get("escape", [])
        j = i + len(q["open"])
        buf = []
        while j < n:
            ch = sql[j]
            if ch == "\\" and "backslash" in esc and j + 1 < n:
                buf.append(sql[j + 1])
                j += 2
                continue
            if sql.startswith(close, j):
                if "double" in esc and sql.startswith(close, j + len(close)):
                    buf.append(close)
                    j += 2 * len(close)
                    continue
                i = j + len(close)
                return "".join(buf)
            buf.append(ch)
            j += 1
        raise ValueError("unterminated quoted token")

    while i < n:
        ch = sql[i]
        if ch.isspace():
            i += 1
            continue
        if any(sql.startswith(lc, i) for lc in line_comments):
            j = sql.find("\n", i)
            i = n if j < 0 else j
            continue
        if sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        q = next((q for q in ident_quotes if sql.startswith(q["open"], i)), None)
        if q:
            out.append(Tok("qident", read_quoted(q)))
            continue
        q = next((q for q in string_quotes if sql.startswith(q["open"], i)), None)
        if q:
            out.append(Tok("string", read_quoted(q)))
            continue
        m = re.match(r"[A-Za-z_][A-Za-z0-9_$]*", sql[i:])
        if m:
            out.append(Tok("word", m.group(0)))
            i += m.end()
            continue
        m = re.match(r"\d+(\.\d+)?", sql[i:])
        if m:
            out.append(Tok("number", m.group(0)))
            i += m.end()
            continue
        two = sql[i:i + 2]
        if two in _PUNCT2:
            out.append(Tok("punct", two))
            i += 2
            continue
        out.append(Tok("punct", ch))
        i += 1
    while out and out[-1] == Tok("punct", ";"):
        out.pop()
    return out


# --- matching ---------------------------------------------------------------

def matches(grammar: Grammar, start: str, tokens: list[Tok]) -> bool:
    keywords = grammar.keywords()
    toks = tuple(tokens)

    @lru_cache(maxsize=None)
    def rule(name: str, pos: int) -> frozenset:
        if name in grammar.rules:
            return node(grammar.rules[name], pos)
        return builtin(name, pos)

    def builtin(name, pos) -> frozenset:
        if pos >= len(toks):
            return frozenset()
        t = toks[pos]
        if name == "identifier":
            ok = t.kind == "qident" or (t.kind == "word" and t.text.upper() not in keywords)
            return frozenset({pos + 1}) if ok else frozenset()
        if name == "string_literal":
            return frozenset({pos + 1}) if t.kind == "string" else frozenset()
        if name == "integer":
            return frozenset({pos + 1}) if t.kind == "number" and t.text.isdigit() else frozenset()
        if name == "expression":
            ends, depth = set(), 0
            for j in range(pos, len(toks)):
                tj = toks[j]
                if tj == Tok("punct", "("):
                    depth += 1
                elif tj == Tok("punct", ")"):
                    if depth == 0:
                        break
                    depth -= 1
                elif tj == Tok("punct", ",") and depth == 0:
                    break
                if depth == 0:
                    ends.add(j + 1)
            return frozenset(ends)
        raise GrammarError(f"unknown rule '{name}'")

    def node(n, pos) -> frozenset:
        kind = n[0]
        if kind == "kw":
            ok = pos < len(toks) and toks[pos].kind == "word" and toks[pos].text.upper() == n[1]
            return frozenset({pos + 1}) if ok else frozenset()
        if kind == "punct":
            ok = pos < len(toks) and toks[pos] == Tok("punct", n[1])
            return frozenset({pos + 1}) if ok else frozenset()
        if kind == "ref":
            return rule(n[1], pos)
        if kind == "seq":
            cur = frozenset({pos})
            for child in n[1]:
                cur = frozenset(e for p in cur for e in node(child, p))
                if not cur:
                    break
            return cur
        if kind == "alt":
            return frozenset(e for c in n[1] for e in node(c, pos))
        if kind == "opt":
            return frozenset({pos}) | node(n[1], pos)
        if kind in ("star", "plus"):
            seen = set() if kind == "plus" else {pos}
            frontier = {pos}
            while frontier:
                nxt = {e for p in frontier for e in node(n[1], p)} - seen
                nxt.discard(pos) if kind == "star" else None
                seen |= nxt
                frontier = nxt
            return frozenset(seen)
        if kind == "ver":
            raise GrammarError("unfiltered version annotation; call for_version() first")
        raise GrammarError(f"bad node {n!r}")

    return len(toks) in rule(start, 0)
