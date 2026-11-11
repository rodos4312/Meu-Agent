# Meu coding engine — Phase 1: repository intelligence

Phase 1 gives Meu a read-only understanding of a code repository: which files exist, what
they define, how they depend on each other, which of them matter for a request, and a
compact, budgeted context to hand to a model. It is **not** connected to the agent loop
yet and adds no tool, no config key and no dependency.

The approach is inspired conceptually by Aider's *repo-map* idea (a ranked, symbol-level
map of the repository instead of whole files). No Aider source code is included; every
line of `meu_coding/` was written for Meu.

## Modules

| Module | Responsibility |
|---|---|
| `meu_coding/interfaces.py` | Frozen dataclasses shared by everything: `RepositoryFile`, `Symbol`, `ExtractionResult`, `DependencyEdge`/`EdgeKind`, `RankedItem`, `ContextItem`, `ContextBundle`, `RepositoryAnalysis`, and the `SymbolExtractorBackend` protocol. Model-independent; paths are repository-relative POSIX strings. |
| `meu_coding/repo_index.py` | `RepositoryIndexer(root, IndexConfig)`: deterministic (sorted) enumeration, default ignored directories, `.gitignore` (root and nested), include/exclude globs, binary detection (extension list + NUL byte in the first 8 KiB), size cap (1 MB), language detection by extension. Skips symlinks. `scan(known=…)` reuses unchanged records without reopening files; `file_record(path)` checks one path with the same rules. |
| `meu_coding/python_outline.py` | `PythonOutlineScanner`: the fast-index Python scanner (definitions, containers, end lines and imports from lines, no parser). |
| `meu_coding/symbols.py` | `SymbolExtractor` with a fast and a deep backend chain (below). Classes, functions, methods, module-level variables, imports and tiered references, each with name, kind, path, line, column, container and end line where known. |
| `meu_coding/graph.py` | `RepositoryGraph`: IMPORTS (file→file or `module:<name>`), DEFINES (file→symbol), BELONGS_TO (symbol→file), REFERENCES (file→symbol, symbol→symbol). Plain dicts/sets — no NetworkX. Incremental: `update_file(file, extraction)`, `remove_file(path)`. |
| `meu_coding/relevance.py` | `RelevanceEngine.rank(query)`: explainable weighted score per file, over inverted indexes kept per file (`update_path`/`remove_path`). |
| `meu_coding/context_builder.py` | `ContextBuilder.build(query, ranked, budget)`: budgeted `ContextBundle`. |
| `meu_coding/cache.py` | `MemoryCache` (default) and `JsonFileCache(directory)`, compact and sharded. |
| `meu_coding/intelligence.py` | `RepositoryIntelligence`, the public facade, and `analyze_repository(root)`. |
| `scripts/meu/coding_engine_benchmark.py` | Non-destructive benchmark. |

## Public API

```python
from meu_coding import analyze_repository

intel = analyze_repository("D:/meu-work")              # RepositoryIntelligence
intel.find_relevant_context("why does SyncManager drop pairing?", budget=12_000)  # ContextBundle
intel.rank("...", limit=50)                             # tuple[RankedItem]
intel.lookup_symbol("SyncManager")                      # definitions, by name or Class.method
intel.get_dependencies("gateway/run.py")                # files it imports (include_external=True adds module:<x>)
intel.get_reverse_dependencies("gateway.run")           # files that import it (path or module name)
intel.refresh_changed_files()                           # ChangeSet(added, modified, removed): metadata rescan
intel.refresh_changed_files(["gateway/run.py"])         # only these paths (what a write just touched)
intel.deep_analyze(["gateway/run.py"])                  # deep-parse given files (None = all)
intel.save_cache()                                      # persist deep results gathered by queries
intel.symbol_counts()                                   # definitions / imports / references / deep_files
intel.graph.related_files(path, max_distance=2)         # {path: hops}
intel.graph.symbols_for_file(path) / files_for_symbol(name) / referencing_files(name) / edges()
```

`ContextBundle.render()` returns the text to give a model; `bundle.items` carry, per file,
the selected symbols, the excerpt, the reasons, the line span and the size.

## Two-stage indexing

**Fast index** (`analyze_repository`, every file): path, language, imports and definitions
from line scanners: `PythonOutlineScanner` for Python, `LightweightFallback` for the rest.
It agrees with the AST on names, kinds, lines, containers, end lines and imports for normal
code (`tests/meu_coding/test_python_outline.py`), including late imports inside functions,
multi-line `from … import (…)`, decorators and docstrings that contain code-like text.

**Deep index** (on demand): the backend chain below, with tiered references. A file is
deep-parsed when it is among the top `deep_budget` (20) results of a query, a direct
dependency or dependant of the top 3, recently changed, or passed to `deep_analyze`.
`find_relevant_context` deepens its targets, re-ranks, then builds the context, so symbol
excerpts get exact end lines. Deep results are cached like fast ones.

## Symbol extraction and fallbacks

For the deep index, `SymbolExtractor` tries the backends in order and keeps the first that
succeeds:

1. **`PythonASTFallback`** (Python). The stdlib `ast` parser is exact and always available,
   and gives real containers (`Class.method`) and end lines. `ast.parse` only parses: no
   repository code is imported or executed.
2. **`TreeSitterExtractor`** (optional). Used only if `tree_sitter_language_pack` is
   importable; Meu does not add it as a dependency. It walks the syntax tree for named
   definition nodes and import statements, for any language the pack has a grammar for,
   and also covers Python files the stdlib parser rejects. A missing package or a missing
   grammar makes the backend report "unsupported", never an error.
3. **`LightweightFallback`**. Line regexes for Python, JavaScript/TypeScript, Go, Rust,
   Java/Kotlin/Scala, C#, C/C++, Ruby, PHP and MQL5. Tolerant of any input.

A backend that raises (a syntax error, a crashing grammar, recursion depth) is recorded in
`ExtractionResult.error` and the next backend is tried; if none fits, the result is
empty with backend `none`. Extraction never stops the analysis. Files in languages with no
backend (Markdown, JSON, …) are indexed but not read.

### Reference tiers (deep Python)

On this repository the old visitor stored one reference per distinct identifier per
enclosing definition: 1.74 M of 2.1 M symbols, almost all of them parameters, locals,
builtins and attributes of arbitrary objects, which never link to a definition. Now:

| Tier | Kept | Examples |
|---|---|---|
| HIGH | yes | a name bound by an import here, recorded under the imported name (`from x import helper as h; h()` → `helper`); an attribute of a chain rooted at an imported name (`mod.func()`, `pkg.sub.Klass`) |
| MEDIUM | yes | a name or attribute this file defines (`helper()`, `self.method()`) |
| LOW | no (`PythonASTFallback(keep_low_references=True)` keeps them) | locals, parameters, builtins, `obj.attr` of anything else |

The graph only ever linked references to definitions in the same file or in directly
imported files, so dropping LOW loses no edge.

> Tree-sitter status: the walking logic is unit-tested against a fake tree with the same
> node API; in this environment the package is not installed, so the real grammars have
> not been exercised here.

## Relevance scoring

`relevance.WEIGHTS` is the single tuning table. Signals and default points:

| Signal | Points | Reason text |
|---|---|---|
| Exact file mention (`path` or a `/`-suffix of it) | 100 | `explicitly mentioned` |
| Defines a symbol the query names in code form (`CamelCase`, `snake_case`, `` `x` ``, `x(`) | 45, +10 per extra | `defines symbol X` |
| Defines a symbol matching a plain word, case-insensitive | 8 | `defines X (case-insensitive mention)` |
| Filename words appear in order in the query | 25 | `filename matches query` |
| Directory words in the query | 5 each, max 15 | `path matches …` |
| Query keyword overlap with path + symbol words | up to 15 (proportional) | `keyword overlap: …` |
| Imported by a seed file | 18 | `imported by <seed>` |
| Imports a seed file | 14 | `imports <seed>` |
| Two import hops from a seed | 6 | `two imports from <seed>` |
| Test of a seed (`test_<stem>`, `<stem>_test`, `.test.`/`.spec.`, or a test that imports it) | 12 | `tests <seed>` |
| Seed has a related test | 3 | `related test exists: <test>` |
| Recently changed (from `refresh_changed_files`) | 8 | `recently changed` |

*Seeds* are files that are explicitly mentioned or define a code-form symbol the query
names. Stop words ("fix", "file", "the", …) are ignored for keyword signals. Results are
sorted by `(-score, path)` and are fully deterministic. There are no embeddings and no
vector store.

## Context budget

The budget is in **characters** (no model-neutral tokenizer exists in the repository yet;
roughly 4 characters per token for code). For each ranked file, in order:

- a file defining a mentioned symbol contributes that definition with 3 leading lines
  (decorators, comments), capped at 60 lines per symbol;
- any other file contributes an outline: its import lines and the signature line of each
  class/function/method, capped at 30 lines;
- every item starts with a header: path, score, top reasons, and up to 3 imports and
  importers.

Whole files are never dumped. An item that does not fit the remaining budget is trimmed
line by line (marked `… trimmed`); if even 3 lines do not fit it is omitted and listed in
`ContextBundle.omitted`. At most 12 items. `len(bundle.render()) <= budget` always holds.

## Incremental updates

`refresh_changed_files()` rescans metadata only: unchanged files keep their records without
being reopened, and only added, modified and removed files are processed.
`refresh_changed_files(paths)` checks just those paths (no tree walk). Each change goes
through `RepositoryGraph.update_file` / `remove_file` and `RelevanceEngine.update_path` /
`remove_path`:

- the file's previous definitions, imports and references are removed and the new ones
  inserted;
- imports elsewhere that tried this path or module name (each resolution records the keys
  it tried) are re-resolved, so a new file picks up importers that were waiting for it and
  a deleted one releases them;
- references of the files importing it are re-linked against its new definitions.

`tests/meu_coding/test_intelligence.py` checks that after a series of incremental changes
the edges and the ranking equal a fresh build of the same tree.

## Cache

`MemoryCache` (the default) keeps extractions in memory. `JsonFileCache(directory)`
persists them under a directory the caller chooses:

- 64 shard files; a save rewrites only the shards touched since the last save;
- per file one compact row: size, mtime, digest, depth, backend, error, a local string
  table, and six integers per symbol (kind, name, line, column, container, end line). No
  source text, no repeated path or language, no field names;
- rows are decoded into `Symbol` objects only when a file is asked for.

An entry is reused only while the file's size and mtime match, and with
`verify_content=True` also its SHA-256, so an edited file is always re-extracted. A corrupt
shard is ignored; a cache that raises is logged and treated as a miss.

## Security boundaries

Phase 1 is read-only by construction:

- It imports only the standard library (plus optionally `tree_sitter_language_pack`). No
  `subprocess`, `os.system`, `exec`/`eval`, `runpy` or package installation.
- Source files are opened only with `"rb"`. `ast.parse` and tree-sitter parse, never run.
- No git invocation at all (commit, reset, clean, checkout, merge or even status).
- Symlinks are skipped, so the index cannot reach outside the given root.
- Context reads only paths that came from the index.
- The single write is `JsonFileCache.save()`, to the directory the caller passes (atomic
  replace per shard). The default cache writes nothing.

`tests/meu_coding/test_read_only_boundary.py` analyses a hostile repository whose
`setup.py`, `conftest.py`, `__init__.py` and JS would leave marker files if executed, with
process spawning patched to fail, and checks that nothing changed and nothing ran.

File writes, patches, approvals, terminal execution, worktrees and git mutation remain the
responsibility of the existing Meu systems.

## Limitations

- Python import resolution: absolute (`a.b.c`, also `src/` and `lib/` layouts) and relative
  imports; no `sys.path` manipulation, namespace-package edge cases or dynamic imports.
- JS/TS: relative specifiers only; `tsconfig` path aliases and package `exports` are not
  resolved (they appear as `module:<name>`).
- Other languages: imports resolve only when the specifier names a repository file
  (`#include "x.h"`); Go/Rust/Java packages stay external.
- References are linked only to definitions in the same file or in directly imported files;
  name-only matches across the repository are deliberately not linked (too noisy).
- The `.gitignore` support is the common subset (no `.git/info/exclude`, no global ignore).
- Character budget, not tokens.
- Ranking weights are hand-set and have not been evaluated on real tasks.
- The fast Python scanner is line-based: a triple quote inside an ordinary string, or code
  after a closing triple quote on the same line, can hide definitions until the file is
  deep-parsed.
- References exist only for deep-parsed files; `referencing_files` and symbol→symbol edges
  are partial until `deep_analyze()` covers the files of interest.
- The whole analysis lives in memory.
- A `.gitignore` edit is picked up by a full `refresh_changed_files()`, not by a path-scoped
  one for files it does not name.

## Phase 2 (not started)

Orchestrator, architect/coder/reviewer roles, impact analysis, model-specific editing,
repair loops and build/test orchestration. None of it is part of Phase 1.

## Performance (Meu repository, Windows, 2026-11-11)

`scripts/meu/coding_engine_benchmark.py --deep-all` on this repository (21,679 files
indexed, 16,071 parsed). "Before" is the first Phase 1 build (every file deep-parsed with
all references, one JSON cache file, full rebuild on refresh).

| Measure | Before | After |
|---|---|---|
| Initial index (cold) | 233 s | 25 s (fast index) |
| Cached startup | 60 s | 9.6 s |
| 1-file refresh, paths given | — | 0.06 s |
| 10-file refresh, paths given | — | 0.38 s |
| 1-file refresh, full metadata rescan | 57 s | 1.5 s |
| Context query, first time (deepens ~20–40 files) | 0.5–2.2 s | 0.35–3.7 s |
| Context query, repeated | 0.5–2.2 s | 0.07–0.35 s |
| Cache size, after startup + queries | 448 MB | 18.5 MB |
| Cache size, every file deep | 448 MB | 32.9 MB |
| Symbols, startup | 2,115,560 | 379,138 (202,599 definitions + 176,539 imports) |
| References, startup / after 3 queries / every file deep | 1,736,500 | 0 / 26,775 / 644,844 |

Fast-index fidelity against the AST over the whole repository: 2 of 176,520 imports and 82
of 202,678 definitions differ (strings that contain triple quotes, such as code generators).
Those files get exact results as soon as they are deep-parsed.

Remaining cost centres:

- **First query deepening.** A first query that ranks large adapters (`slack/adapter.py`,
  thousands of lines) spends most of its time in `ast.parse` of 20–40 files; repeats and
  later queries hit the cached deep results. `deep_budget` bounds it.
- **Cached startup** is mostly the metadata walk (21,679 stats plus `.gitignore` matching)
  and rebuilding the in-memory graph and relevance index from 379 k symbols.
- **Deep-parsing everything** (`deep_analyze()`) takes ~100 s; it is never done implicitly.
