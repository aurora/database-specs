---
name: audit-inventory
description: Independent completeness audit of one engine's feature inventory and its scope classification (inventory/<engine>/, scope/<engine>.yaml) against the official documentation and the real server. Use when the user asks to audit, cross-check or verify the inventory / scope / completeness of an engine, e.g. "/audit-inventory manticore".
argument-hint: <engine>
context: fork
agent: general-purpose
---

# Inventory audit (independent review)

You review the work of another session that built the specs. You have NOT seen that session and
must not trust its conclusions: check them against the sources. The goal is to find what is
missing or misclassified, not to confirm that everything is fine.

Engine to audit: **$ARGUMENTS** (if empty, ask which engine).

## Inputs

- `inventory/<engine>/<version>.yaml` - generated item list: `kw:` keywords and `<parser>:<rule>:`
  grammar forms (from the server's parser sources at the build commit, see `sources`), `docs:`
  entries of the manual's reference index.
- `scope/<engine>.yaml` - hand-written classification (covered / planned / open / out-of-scope).
- `uv run dbspecs coverage` then the `## Inventory` section of `COVERAGE.md` - the grouped result.
- `uv run dbspecs show ...` - resolved specs (read CLAUDE.md for usage).

## Checks

1. **Blind spots of the inventory.** The grammar does not contain names resolved in C++ tables
   (functions, OPTION names, table settings, SET variables) or statements handled outside the
   parser (Manticore: the Buddy sidecar). For each `docs:` section relevant to a database client
   (SQL commands, SELECT, options, full-text operators, functions, data types), open the linked
   manual pages (use the web-fetch agent / WebFetch) and list syntax elements that have no
   matching inventory item. Typical finds: individual OPTION names, FACET / GROUP modifiers,
   statement variants only shown in examples.
2. **Covered really covered?** For every `covered` rule, pick at least two of its items and check
   that the cited spec describes that exact form: for syntax specs, build a statement from the
   form and run `uv run dbspecs show syntax <id> -e <engine> -v <version> --sql "..."`; for
   operations / queries, read `dbspecs show`. A form the grammar rejects is a finding.
3. **Out-of-scope plausible?** The repository serves a database client (object tree, table editor,
   query editor with highlighting and autocomplete, AI-generated SQL). Flag out-of-scope reasons
   that a client user would disagree with.
4. **Open / planned still accurate?** Check that open reasons are true (e.g. a spec now exists) and
   that planned roadmap items exist in `roadmap.yaml`.
5. **Server check (optional, only if docker/podman works).** For up to ten findings, verify against
   the real server with `uv run dbspecs test --target <engine>`-style containers or a scratch
   container; never run user-management commands such as GRANT on a server you did not start.

## Rules

- Do not edit spec files, scope or inventory. Write the report only.
- Facts in your own words; never copy documentation prose. Names and short syntax forms are fine.
- Every finding names its source (manual URL, grammar item id, command output).

## Output

Write `dist/audit/<engine>-<version>.md` with sections: Summary (counts per finding type),
Missing from the inventory, Misclassified, Covered but not described, Out-of-scope to reconsider,
Stale open / planned entries, Proposed scope.yaml changes (as a YAML snippet, not applied).
Finish with the report path and the three most important findings.
