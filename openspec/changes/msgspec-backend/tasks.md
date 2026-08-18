## 1. Dependencies and configuration

- [x] 1.1  Add `msgspec` to `[project].dependencies` in `pyproject.toml`
- [x] 1.2  Add `msgspec` to `[tool.pixi.dependencies]` in `pyproject.toml`
- [x] 1.3  Add `"CONTEXT_BACKEND": "conda_context_backend"` to `_ENV_VAR_MAP`
           in `src/conda_context/merge.py`

## 2. FieldError, FieldMetadata, and BackendProtocol

- [x] 2.1  Create `src/conda_context/_schema_backend.py`
- [x] 2.2  Define `@dataclass FieldError(loc, input, msg)`
- [x] 2.3  Define `@dataclass FieldMetadata(aliases, description, annotation)`
- [x] 2.4  Define `BackendProtocol(Protocol)` with `build`, `validate_single`,
           `field_metadata`, `errors` methods
- [x] 2.5  Implement `PydanticBackend`:
           - `build(data)` → `CondaConfig(**data)`
           - `validate_single(field, value)` → uses `CondaConfig.model_validate`
           - `field_metadata()` → derived from `CondaConfig.model_fields`
           - `errors(exc: pydantic.ValidationError)` → `list[FieldError]`
- [x] 2.6  Implement `MsgspecBackend`:
           - `build(data)` → `normalize_alias_keys(data)` then `msgspec.convert`
           - `validate_single(field, value)` → `msgspec.convert({field: value}, ...)`
           - `field_metadata()` → `msgspec.structs.fields()` + `_FIELD_DESCRIPTIONS`
           - `errors(exc: msgspec.ValidationError)` → `list[FieldError]`
- [x] 2.7  Implement `normalize_alias_keys(data: dict) → dict`
- [x] 2.8  Implement `get_backend(name: str) → BackendProtocol` factory (raises
           `ValueError` for unknown names)

## 3. msgspec schema

- [x] 3.1  Create `src/conda_context/schemas/_26_5_3_msgspec.py`
- [x] 3.2  Define `_ALIAS_TO_CANONICAL: dict[str, str]` (all 23 aliased fields)
- [x] 3.3  Define `_FIELD_DESCRIPTIONS: dict[str, str]` (all field description
           strings, verbatim from the pydantic schema's `Field(description=...)`)
- [x] 3.4  Define `CondaConfigMsgspec(msgspec.Struct)`:
           - All 113 fields with correct types and defaults (no `field(name=...)` aliases)
           - `conda_context_backend: str = "pydantic"` field
           - `__post_init__` implementing all 5 validators:
             1. `ssl_verify` string normalization (`"true"`→`True`, `"false"`→`False`,
                path/truststore pass-through) via `object.__setattr__`
             2. `channel_alias` scheme presence check
             3. `default_python` format check (`[23].[0-9][0-9]?` or `""`)
             4. `list_fields` values checked against `CONDA_LIST_FIELDS`
             5. Cross-field: `always_copy` ⊕ `always_softlink`,
                `client_ssl_cert_key` requires `client_ssl_cert`

## 4. Pydantic schema — add `conda_context_backend` field

- [x] 4.1  Add `conda_context_backend: str = Field(default="pydantic", description=...)`
           to `CondaConfig` in `src/conda_context/schemas/_26_5_3.py`

## 5. Update `errors.py`

- [x] 5.1  Remove `from pydantic import ValidationError`
- [x] 5.2  Import `FieldError` from `._schema_backend`
- [x] 5.3  Change `CondaConfigError.__init__` signature to accept `list[FieldError]`
           instead of `pydantic.ValidationError`
- [x] 5.4  Update `_field_errors()` to iterate over `self._field_errors_list` directly
           instead of calling `.errors(include_url=False)`

## 6. Update `context.py`

- [x] 6.1  Remove `from pydantic import ValidationError`
- [x] 6.2  Import `get_backend` from `._schema_backend`
- [x] 6.3  Update `_rebuild()`
- [x] 6.4  Update `validate_configuration()` to use `self._backend.build(self.raw_data)`
- [x] 6.5  Update `typify_parameter()` to use `self._backend.validate_single(lookup, value)`
- [x] 6.6  Update `parameter_names` to use `self._backend.field_metadata()`
- [x] 6.7  Update `parameter_names_and_aliases` to use `self._backend.field_metadata()`
- [x] 6.8  Update `name_for_alias()` to use `self._backend.field_metadata()`
- [x] 6.9  Update `describe_parameter()` to use `self._backend.field_metadata()`

## 7. Benchmarks

- [x] 7.1  Add `full_merged_dict_with_aliases` fixture to `tests/conftest.py`
- [x] 7.2  Add `test_bench_msgspec_empty(benchmark)`
- [x] 7.3  Add `test_bench_msgspec_full_merged(benchmark, full_merged_dict)`
- [x] 7.4  Add `test_bench_msgspec_full_aliases(benchmark, full_merged_dict_with_aliases)`

## 8. Verification

- [x] 8.1  `pytest -m "not benchmark"` — all existing tests pass, no regressions
- [x] 8.2  `pytest tests/test_benchmarks.py --benchmark-disable` — all 11 existing
           + 4 new msgspec benchmarks collect and pass
- [x] 8.3  `pytest tests/test_benchmarks.py --benchmark-json=benchmark.json` — JSON
           includes `bench_msgspec_*` entries (manual verification)
- [x] 8.4  Set `conda_context_backend: msgspec` in a test `.condarc`, confirm
           `Context._rebuild()` uses `MsgspecBackend`
- [x] 8.5  Set `CONTEXT_BACKEND=msgspec` as env var, confirm same result
- [ ] 8.6  `python scripts/generate_benchmark_report.py benchmark.json` — HTML
           report includes the new msgspec benchmarks in the charts
