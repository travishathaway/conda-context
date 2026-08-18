## Why

The current benchmarking suite measures `CondaConfig` construction using Pydantic v2 exclusively. We have no empirical data on whether msgspec — a C-extension validation library that is consistently 2–5× faster than Pydantic for struct construction — would be a meaningful improvement for the configuration loading hot path. Beyond raw speed, we want to evaluate whether msgspec's validation API is expressive enough to faithfully reimplement all five validators currently defined in the Pydantic schema.

The long-term goal is to make the validation backend swappable at runtime via a `conda_context_backend` configuration setting in `.condarc` or via `CONTEXT_BACKEND` environment variable, so conda operators can opt into the faster backend and the benchmark suite can compare them side-by-side using identical inputs.

## What Changes

- Add `msgspec` as a hard runtime dependency alongside `pydantic`.
- Introduce `CondaConfigMsgspec` in `src/conda_context/schemas/_26_5_3_msgspec.py` — a feature-complete msgspec equivalent of `CondaConfig` with all 113 fields, all 5 validators, and all cross-field constraints. Includes a companion `_ALIAS_TO_CANONICAL` dict (23 entries) for pre-normalization and `_FIELD_DESCRIPTIONS` dict for introspection parity.
- Introduce `src/conda_context/_schema_backend.py` with `PydanticBackend`, `MsgspecBackend`, a shared `FieldError` dataclass, and a `get_backend(name)` factory.
- Add `conda_context_backend: str` as a real configuration field in both `CondaConfig` and `CondaConfigMsgspec` (default `"pydantic"`). Add `CONTEXT_BACKEND` to `_ENV_VAR_MAP` in `merge.py`.
- Update `context.py` and `errors.py` to use `_schema_backend` abstractions, removing all direct `pydantic` imports from those files.
- Extend `tests/test_benchmarks.py` with `bench_msgspec_empty` and `bench_msgspec_full_merged`, and add a `full_merged_dict_with_aliases` fixture to `conftest.py`.

## Capabilities

### New Capabilities

- `msgspec-schema`: A `CondaConfigMsgspec(msgspec.Struct)` covering all 113 conda 26.5.3 configuration fields. Includes `__post_init__` validation equivalent to all five Pydantic validators. A companion `_ALIAS_TO_CANONICAL` dict normalizes legacy YAML key names to canonical Python attribute names before `msgspec.convert` is called.
- `schema-backend`: A `_schema_backend.py` module providing `PydanticBackend`, `MsgspecBackend`, and a shared `FieldError` dataclass. Both backends expose `.build(data)`, `.validate_single(field, value)`, `.field_metadata()`, and `.errors(exc) → list[FieldError]`.
- `runtime-backend-selection`: `Context._rebuild()` reads `conda_context_backend` from the raw merged dict (resolved before schema construction) and delegates to `PydanticBackend` or `MsgspecBackend` accordingly — zero per-call overhead after selection.

### Modified Capabilities

- `benchmark-suite`: Three new benchmark functions (`bench_msgspec_empty`, `bench_msgspec_full_merged`, `bench_msgspec_full_aliases`) added to `tests/test_benchmarks.py` for side-by-side comparison with the existing pydantic benchmarks. A new `full_merged_dict_with_aliases` fixture exercises the normalization path.
- `context`: `context.py` no longer imports from `pydantic` directly. All validation, introspection, and error-normalization flows through `_schema_backend`.
- `errors`: `CondaConfigError.__init__` accepts `list[FieldError]` instead of `pydantic.ValidationError`, decoupling it from any specific validation library.

## Impact

- **New hard dependency**: `msgspec` added to `[project].dependencies` in `pyproject.toml`.
- **New pixi dependency**: `msgspec` added to pixi workspace dependencies.
- **New files**: `src/conda_context/schemas/_26_5_3_msgspec.py`, `src/conda_context/_schema_backend.py`.
- **Modified files**: `src/conda_context/schemas/_26_5_3.py`, `src/conda_context/context.py`, `src/conda_context/errors.py`, `src/conda_context/merge.py`, `tests/test_benchmarks.py`, `tests/conftest.py`, `pyproject.toml`.
- **No behaviour change by default**: `conda_context_backend` defaults to `"pydantic"`, so all existing tests and runtime behaviour are unaffected unless the setting is explicitly changed.

## Non-Goals

- Removing Pydantic as a dependency.
- Making msgspec the default backend.
- Migrating the schema generator to produce msgspec structs.
- Integrating with conda's plugin settings hook.
- Memory profiling or startup-time profiling.
