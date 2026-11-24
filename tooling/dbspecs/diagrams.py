"""Render syntax grammars as railroad diagrams (SVG + one HTML overview page)."""

from __future__ import annotations

import html
import io
from pathlib import Path

import railroad as rr

from .ebnf import BUILTINS, Grammar
from .specs import Specs
from .syntax import load_grammar

MAX_LINE_WIDTH = 720

LIGHT = {"fg": "#1d1d1f", "line": "#2b2b2e", "term": "#e6f2e6", "nonterm": "#e8eef8",
         "builtin": "#f1ece4", "group": "#9a8f7a", "accent": "#3b6fb6"}
DARK = {"fg": "#ececee", "line": "#d8d8dc", "term": "#22392a", "nonterm": "#23314a",
        "builtin": "#3a332a", "group": "#a99c84", "accent": "#7fa8e6"}

DIAGRAM_CSS = """
svg.railroad-diagram { background: transparent; }
svg.railroad-diagram path { stroke-width: 2; stroke: var(--line); fill: none; }
svg.railroad-diagram text { font: 600 13px ui-monospace, monospace; text-anchor: middle; fill: var(--fg); }
svg.railroad-diagram text.label { text-anchor: start; font-weight: 500; fill: var(--group); }
svg.railroad-diagram text.comment { font: italic 12px ui-monospace, monospace; }
svg.railroad-diagram rect { stroke-width: 2; stroke: var(--line); }
svg.railroad-diagram g.terminal rect { fill: var(--term); }
svg.railroad-diagram g.non-terminal rect { fill: var(--nonterm); }
svg.railroad-diagram g.non-terminal.builtin rect { fill: var(--builtin); stroke-dasharray: 4 3; }
svg.railroad-diagram g.non-terminal a text { fill: var(--accent); }
svg.railroad-diagram rect.group-box { stroke: var(--group); stroke-dasharray: 6 4; fill: none; }
"""


def _literal_css(palette: dict) -> str:
    css = DIAGRAM_CSS
    for key, value in palette.items():
        css = css.replace(f"var(--{key})", value)
    return css


# standalone SVG files: literal colours (simple renderers do not support CSS variables)
STANDALONE_CSS = (_literal_css(LIGHT)
                  + "@media (prefers-color-scheme: dark) {" + _literal_css(DARK) + "}")

CSS = """
:root { --bg:#fbfaf7; --fg:#1d1d1f; --muted:#6b6b70; --line:#2b2b2e; --term:#e6f2e6; --nonterm:#e8eef8;
        --builtin:#f1ece4; --group:#9a8f7a; --card:#ffffff; --border:#e3e0d8; --accent:#3b6fb6; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
        --bg:#17181a; --fg:#ececee; --muted:#9a9aa2; --line:#d8d8dc; --term:#22392a; --nonterm:#23314a;
        --builtin:#3a332a; --group:#a99c84; --card:#1f2023; --border:#33343a; --accent:#7fa8e6; } }
:root[data-theme="dark"] { --bg:#17181a; --fg:#ececee; --muted:#9a9aa2; --line:#d8d8dc; --term:#22392a;
        --nonterm:#23314a; --builtin:#3a332a; --group:#a99c84; --card:#1f2023; --border:#33343a; --accent:#7fa8e6; }
* { box-sizing: border-box; }
body { margin:0; padding:24px 16px 64px; background:var(--bg); color:var(--fg);
       font:15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1100px; margin: 0 auto; }
h1 { font-size: 26px; margin: 0 0 4px; } h2 { font-size: 20px; margin: 40px 0 8px; }
h3 { font-size: 14px; font-family: ui-monospace, monospace; margin: 20px 0 6px; color: var(--muted); font-weight: 600; }
p.lead, .notes { color: var(--muted); }
.notes { margin: 4px 0 12px; padding-left: 18px; font-size: 14px; }
nav { display:flex; gap:8px; flex-wrap:wrap; margin: 12px 0 0; }
nav a { color: var(--accent); text-decoration:none; border:1px solid var(--border); border-radius:999px; padding:2px 12px; font-size:14px; }
.card { background: var(--card); border:1px solid var(--border); border-radius: 10px; padding: 8px 16px 16px; margin: 12px 0; }
.scroll { overflow-x: auto; }
code { font-family: ui-monospace, monospace; font-size: 13px; }
""" + DIAGRAM_CSS + """
.legend { display:flex; gap:16px; flex-wrap:wrap; font-size:13px; color:var(--muted); }
.legend span::before { content:""; display:inline-block; width:14px; height:10px; margin-right:6px; border:2px solid var(--line); vertical-align:-1px; }
.legend .t::before { background: var(--term); border-radius: 5px; } .legend .n::before { background: var(--nonterm); }
.legend .b::before { background: var(--builtin); border-style: dashed; } .legend .g::before { border-color: var(--group); border-style: dashed; }
"""


def _label(ann: dict) -> str:
    parts = []
    if "since" in ann:
        parts.append(f"{ann['since']}+")
    if "until" in ann:
        parts.append(f"< {ann['until']}")
    return " ".join(parts)


def to_railroad(node, anchor_prefix: str, grammar: Grammar):
    kind = node[0]
    rec = lambda n: to_railroad(n, anchor_prefix, grammar)  # noqa: E731
    if kind == "kw" or kind == "punct":
        return rr.Terminal(node[1])
    if kind == "ref":
        if node[1] in BUILTINS:
            return rr.NonTerminal(node[1], cls="builtin")
        return rr.NonTerminal(node[1], href=f"#{anchor_prefix}-{node[1]}")
    if kind == "list":
        return rr.OneOrMore(rec(node[1]), rr.Terminal(node[2]))
    if kind == "seq":
        items = _merge_lists(node[1])
        if not items:
            return rr.Skip()
        return rr.Sequence(*[rec(i) for i in items]) if len(items) > 1 else rec(items[0])
    if kind == "alt":
        return rr.Choice(0, *[rec(i) for i in node[1]])
    if kind == "opt":
        return rr.Optional(rec(node[1]))
    if kind == "star":
        return rr.ZeroOrMore(rec(node[1]))
    if kind == "plus":
        return rr.OneOrMore(rec(node[1]))
    if kind == "ver":
        return rr.Group(rec(node[2]), _label(node[1]))
    raise ValueError(node)


def _merge_lists(items: list) -> list:
    """X ( ',' X )*  ->  ("list", X, ',') so it renders as a loop with separator."""
    out, i = [], 0
    while i < len(items):
        cur = items[i]
        nxt = items[i + 1] if i + 1 < len(items) else None
        if (nxt is not None and nxt[0] == "star" and nxt[1][0] == "seq" and len(nxt[1][1]) == 2
                and nxt[1][1][0][0] == "punct" and nxt[1][1][1] == cur):
            out.append(("list", cur, nxt[1][1][0][1]))
            i += 2
        else:
            out.append(cur)
            i += 1
    return out


def _wrap(items: list) -> list:
    """Greedy line breaking of a top-level sequence by rendered width."""
    lines, cur, width = [], [], 0
    for it in items:
        w = it.width + 20
        if cur and width + w > MAX_LINE_WIDTH:
            lines.append(cur)
            cur, width = [], 0
        cur.append(it)
        width += w
    if cur:
        lines.append(cur)
    return lines


def rule_diagram(name: str, node, anchor_prefix: str, grammar: Grammar) -> str:
    if node[0] == "seq" and len(node[1]) > 1:
        parts = [to_railroad(n, anchor_prefix, grammar) for n in _merge_lists(node[1])]
        lines = _wrap(parts)
        body = rr.Stack(*[rr.Sequence(*l) for l in lines]) if len(lines) > 1 else rr.Sequence(*parts)
    else:
        body = to_railroad(node, anchor_prefix, grammar)
    diagram = rr.Diagram(body)
    buf = io.StringIO()
    diagram.writeSvg(buf.write)
    return buf.getvalue()


def _standalone(svg: str) -> str:
    """Make a renderer-embedded SVG a valid standalone file (namespaces + inline CSS)."""
    head, rest = svg.split(">", 1)
    if "xmlns=" not in head:
        head += ' xmlns="http://www.w3.org/2000/svg"'
    if "xmlns:xlink" not in head:
        head += ' xmlns:xlink="http://www.w3.org/1999/xlink"'
    return head + "><style><![CDATA[" + STANDALONE_CSS + "]]></style>" + rest


def render_all(specs: Specs, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    engines = specs.docs["engine"]
    sections = []
    toc = []
    for syn_id, syn in sorted(specs.docs["syntax"].items()):
        toc.append(f'<a href="#{syn_id}">{html.escape(syn["title"])}</a>')
        parts = [f'<h2 id="{syn_id}">{html.escape(syn["title"])}</h2>']
        if syn.get("description"):
            parts.append(f'<p class="lead">{html.escape(syn["description"])}</p>')
        sub = []
        for eid, g in syn["grammars"].items():
            sub.append(f'<a href="#{syn_id}-{eid}">{html.escape(engines[eid]["name"])}</a>')
        parts.append(f"<nav>{''.join(sub)}</nav>")
        for eid, g in syn["grammars"].items():
            grammar = load_grammar(specs, syn_id, eid)
            prefix = f"{syn_id}-{eid}"
            since = f" {g['since']}+" if "since" in g else ""
            parts.append(f'<div class="card" id="{prefix}"><h2 style="margin-top:12px">'
                         f'{html.escape(engines[eid]["name"])}<small style="color:var(--muted);font-weight:400">{since}</small></h2>')
            if g.get("notes"):
                parts.append('<ul class="notes">' + "".join(f"<li>{html.escape(n)}</li>" for n in g["notes"]) + "</ul>")
            svg_dir = out_dir / syn_id / eid
            svg_dir.mkdir(parents=True, exist_ok=True)
            for rule in grammar.order:
                svg = rule_diagram(rule, grammar.rules[rule], prefix, grammar)
                (svg_dir / f"{rule}.svg").write_text(
                    _standalone(svg), encoding="utf-8")
                parts.append(f'<h3 id="{prefix}-{rule}">{rule}</h3><div class="scroll">{svg}</div>')
            parts.append("</div>")
        sections.append("\n".join(parts))

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SQL Syntax Diagrams</title><style>{CSS}</style></head>
<body><main>
<h1>SQL syntax diagrams</h1>
<p class="lead">Generated from the curated EBNF in <code>syntax/</code>. Every example in the specs is checked against
both the grammar and real servers. Dashed boxes mark parts that exist only in some versions.</p>
<div class="legend"><span class="t">keyword / symbol</span><span class="n">rule (click to jump)</span>
<span class="b">built-in (identifier, expression, ...)</span><span class="g">version-dependent</span></div>
<nav>{''.join(toc)}</nav>
{''.join(sections)}
</main></body></html>
"""
    index = out_dir / "index.html"
    index.write_text(page, encoding="utf-8")
    return index
