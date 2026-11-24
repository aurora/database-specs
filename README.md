# database-specs

Machine-readable, versioned specifications of SQL database engines - everything a
database client needs to support an engine fully: lexical rules (highlighting, statement
splitting, quoting), wire-protocol type codes, introspection queries, capabilities with
version ranges, and SQL templates for client operations.

The repository is implementation-agnostic: no knowledge of any particular client, language
or driver. Consumers read the bundled JSON (`dist/db-specs.json`).

## Layout

| Directory | Content |
|---|---|
| `engines/` | One file per engine: versions, protocols, catalogs, version detection. |
| `protocols/` | Wire protocols: type codes and column flags as client libraries expose them (MYSQL_FIELD.type, PQftype OIDs, ...). |
| `lexical/` | Tokenizer rules per dialect: identifier/string quoting, comments, parameters, delimiters, keyword sources. |
| `capabilities/<area>/` | Yes/no/partial facts with version ranges and executable probes. |
| `operations/<area>/` | SQL a client generates itself (alter column, browse table, validate syntax) as templates per engine/version. |
| `queries/<area>/<name>/` | Query contract (`query.yaml`: parameters + normalized result columns) and one `.sql` file per engine/version variant. |
| `syntax/<area>/<statement>/` | Curated EBNF per engine (`<engine>.ebnf`) plus `syntax.yaml` with examples; rendered as railroad diagrams. |
| `keywords/<engine>/` | Generated keyword lists per exact server / library version (`dbspecs keywords`): reserved = fails as an unquoted column name, probed on the real server. |
| `tests/` | `targets.yaml` (container images; SQLite runs a small worker in `python:*-slim` images or locally) and `cases/` (integration tests). |
| `schemas/` | JSON Schemas for every file kind. |
| `tooling/` | Python tooling (`dbspecs` CLI). |

## Status

[COVERAGE.md](COVERAGE.md) shows per spec item and engine what is tested against real servers,
partly covered, only documented, not applicable or missing, followed by the planned items from
[roadmap.yaml](roadmap.yaml). It is generated (`uv run dbspecs coverage`, and after every test run).

## Conventions

- **Version ranges**: `since` is inclusive, `until` exclusive. `"8"` means `8.0.0`. Within a
  list, the last matching entry wins.
- **Status**: `supported`, `partial`, `unsupported`, `unknown`. An engine missing from a
  capability is `unknown` - never read that as unsupported.
- **Evidence** (`sources[].evidence`): `tested` (automated test here), `docs` (checked against
  official docs), `observed`, `unverified` (from knowledge, still to be checked).
- **Query contracts**: every variant returns exactly the declared columns in order. SQL uses
  `:name` placeholders; consumers map them to `?` / `$1` / their driver's style.
- **Templates**: mustache subset - `{{param}}` and `{{#param}}...{{/param}}` (only if set).
  Identifier parameters are quoted by the consumer using the engine's lexical spec.
- **Syntax (EBNF)**: W3C notation (pastes into https://www.bottlecaps.de/rr/ui). Version
  annotations in comments apply to the next item: `/* @since 8.0.13 */ ( '(' expression ')' )`.
  Built-ins: `identifier`, `string_literal`, `integer`, `expression` (loose: any balanced token
  run). This is curated documentation-level syntax, not a parser grammar. Each example
  declares `expect: valid | invalid | semantic-error` per engine/version range and is checked
  offline against the grammar for every version series (`validate`) and against real servers
  (`test`).
- **Derived engines** (MariaDB, Percona, TiDB, CockroachDB, ...) get their own engine file.
  `extends` documents the lineage but facts are never inherited silently.
- Do not copy prose from vendor documentation (MySQL docs are not freely licensed); state
  facts in your own words and link the source.

## Using the specs from a client project

- **At runtime** a client should consume the built bundle `dist/db-specs.json` (shipped as a
  resource or turned into generated code), never the YAML sources.
- **While developing** a client, include this repository as a git submodule (pins the spec
  version the client is built against) and let people and coding agents query it with
  `dbspecs show`. Snippet for the client's `CLAUDE.md` (adjust the path):

  ````markdown
  ## Database specifications

  Engine facts (capabilities per version, introspection SQL, client operation templates,
  lexical rules, statement syntax) come from `vendor/database-specs`. Do not guess dialect
  behaviour and do not read its YAML directly - resolve it for the exact engine/version:

  ```bash
  uv run --project vendor/database-specs dbspecs show profile -e mysql -v 8.0.13
  uv run --project vendor/database-specs dbspecs show capability returning -e mariadb -v 10.6
  uv run --project vendor/database-specs dbspecs show query list-columns -e postgresql -v 16
  uv run --project vendor/database-specs dbspecs show syntax create-index -e mysql -v 8.4 --sql "..."
  uv run --project vendor/database-specs dbspecs show list
  ```

  `unknown` means not researched - not unsupported. Exit code 3 means there is no query variant
  for that version (gap). If a fact is missing or wrong, fix it in database-specs (with a test),
  not with a workaround in this repository.
  ````

## Tooling

Requires [uv](https://docs.astral.sh/uv/) and Docker or Podman.

```bash
uv run dbspecs validate            # schemas + cross references
uv run dbspecs build               # -> dist/db-specs.json, dist/syntax/index.html (+ SVGs)
uv run dbspecs coverage            # -> COVERAGE.md, dist/coverage.html
uv run dbspecs test                # all targets in tests/targets.yaml
uv run dbspecs test --target mysql-8.4 --target postgresql
```

`show` resolves specs for one engine/version (capabilities, query variants, templates,
version-filtered grammars, a full `profile`), as text or `--json`; see `dbspecs show -h`.

`test` starts a throw-away container per target, runs every capability probe (a probe must
succeed exactly when the capability is declared supported/partial) and every test case, and
writes `dist/verification.json`, which `build` embeds into the bundle.
