## Why

`conda.base.context.Context` is built on a bespoke metaclass-based configuration system that produces opaque, low-quality validation errors (no file location, no line number, no actionable hint) and has no safe, programmatic API for mutating `.condarc` files. This library replaces it with a Pydantic-backed implementation that delivers precise, human-readable errors with full source provenance, a type-safe configuration model, and a round-trip-safe `.condarc` write API — while remaining a structural drop-in for conda's existing codebase.

## What Changes

- **New library `conda-context`** — a standalone Python package that can be used in conda plugins or used to monkey-patch `conda.base.context` at runtime.
- **Pydantic-backed `CondaConfig` model** — all 60+ configuration fields from conda 26.5.3 typed, documented, and validated via Pydantic v2.
- **`MergeEngine`** — resolves conda's layered configuration sources (system condarc → user condarc → env condarc → env vars → CLI args) in priority order, producing a merged dict alongside a `ProvenanceMap` that records the origin file path, line number, or environment variable name for every resolved value.
- **`Context` class** — mirrors conda's existing `Context` public and private API surface (including `_cache_`, `raw_data`, `_argparse_args`, `_set_search_path()`, `_reset_cache()`, etc.) and all computed properties, delegating validation to `CondaConfig`.
- **`CondarC` write API** — full CRUD for `.condarc` files using `ruamel.yaml` for comment-preserving round-trips; validates proposed mutations against the full merged context before writing.
- **`CondaConfigError`** — enriched error type wrapping Pydantic `ValidationError` with provenance data; human-readable `__str__` and machine-readable `.as_dict()`.
- **`patch` module** — thin helpers for monkey-patching `conda.base.context` at plugin entry point time (module-attribute replacement) and an import hook for earlier patching.
- **Schema generator (`generator/`)** — dev tool that reads conda source at a given Git tag and emits a versioned `schemas/_XX_X_X.py`; one conda release = one `conda-context` release.
- **Version pinning** — initial release targets conda 26.5.3 exactly; each subsequent conda release requires a corresponding `conda-context` release generated from that tag.

## Capabilities

### New Capabilities

- `config-schema`: Pydantic v2 model (`CondaConfig`) covering all conda 26.5.3 configuration fields with types, defaults, aliases, cross-field validators, and field-level documentation.
- `merge-engine`: Layered configuration source resolution (condarc files + env vars + CLI args) producing a merged dict and a `ProvenanceMap` (field → source file/line or env var name).
- `context-class`: Drop-in `Context` class mirroring conda's public and private API, all computed properties, and the mutation protocol (`reset_context`, `stack_context`, `fresh_context`).
- `condarc-write-api`: Full `.condarc` CRUD — `set`, `unset`, `add_to`, `remove_from`, `prepend_channel`, `append_channel` — with comment-preserving round-trip serialization and pre-save full-context validation.
- `error-provenance`: `CondaConfigError` with per-field source attribution (file path + line number or env var name), human-readable formatting, and structured `.as_dict()` output.
- `patch-helpers`: `patch_module()` for plugin-time monkey-patching and `install_import_hook()` for early-import replacement of `conda.base.context`.
- `schema-generator`: Dev-time CLI tool that extracts field definitions from a conda source tag and emits a versioned Pydantic schema module.

### Modified Capabilities

*(none — this is a new library; no existing specs to modify)*

## Impact

- **Dependencies added**: `pydantic>=2.0`, `ruamel.yaml`
- **Dev dependencies added**: `conda` (pinned to 26.5.3, for generator and test parity)
- **conda dependency at runtime**: optional — the library works standalone; conda is only required if using the monkey-patch path or running integration tests
- **Affected conda internals** (when monkey-patching): `conda.base.context` module attribute `context` and class `Context`; the `reset_context`, `stack_context`, `fresh_context`, `replace_context` functions must be re-exported from the replacement module
- **Version contract**: `conda-context` version matches the conda version it targets exactly (e.g., `conda-context==26.5.3` targets `conda==26.5.3`)
