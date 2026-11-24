"""Statement syntax specs: grammar loading and example checks."""

from __future__ import annotations

from functools import lru_cache

from .ebnf import Grammar, matches, parse_grammar, tokenize
from .specs import Specs, in_range, parse_version


def grammar_path(specs: Specs, syn_id: str, engine: str):
    syn = specs.get("syntax", syn_id)
    return specs.path("syntax", syn_id).parent / syn["grammars"][engine]["file"]


_cache: dict = {}


def load_grammar(specs: Specs, syn_id: str, engine: str) -> Grammar:
    path = grammar_path(specs, syn_id, engine)
    key = (str(path), path.stat().st_mtime)
    if key not in _cache:
        _cache[key] = parse_grammar(path.read_text(encoding="utf-8"))
    return _cache[key]


def lexical_for(specs: Specs, engine: str) -> dict:
    return specs.get("lexical", specs.get("engine", engine)["lexical"])


def grammar_accepts(specs: Specs, syn_id: str, engine: str, version: str, sql: str) -> bool:
    syn = specs.get("syntax", syn_id)
    g = load_grammar(specs, syn_id, engine).for_version(version)
    return matches(g, syn["grammars"][engine]["start"], tokenize(sql, lexical_for(specs, engine)))


def grammar_should_accept(expect: str) -> bool:
    return expect in ("valid", "semantic-error")


def server_should_accept(expect: str) -> bool:
    return expect == "valid"


def check_versions(specs: Specs, syn_id: str, engine: str) -> list[str]:
    """Versions to check offline: engine series plus every boundary used by examples."""
    syn = specs.get("syntax", syn_id)
    floor = syn["grammars"][engine].get("since", "0")
    points = {v["series"] for v in specs.get("engine", engine)["versions"]}
    for ex in syn["examples"]:
        rng = ex["engines"].get(engine)
        if rng:
            points |= {rng[k] for k in ("since", "until") if k in rng}
    return sorted((p for p in points if parse_version(p) >= parse_version(floor)), key=parse_version)


def examples_for(syn: dict, engine: str, version: str):
    for i, ex in enumerate(syn["examples"]):
        rng = ex["engines"].get(engine)
        if rng is not None and in_range(version, rng):
            yield i, ex


def offline_check(specs: Specs, syn_id: str) -> list[str]:
    syn = specs.get("syntax", syn_id)
    problems = []
    for engine in syn["grammars"]:
        for version in check_versions(specs, syn_id, engine):
            for i, ex in examples_for(syn, engine, version):
                got = grammar_accepts(specs, syn_id, engine, version, ex["sql"])
                if got != grammar_should_accept(ex["expect"]):
                    problems.append(
                        f"example {i} on {engine} {version}: grammar {'accepts' if got else 'rejects'} "
                        f"but expect={ex['expect']}: {ex['sql']}")
    return problems
