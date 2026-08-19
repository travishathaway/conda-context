## Context

`conda-context` replaces conda's `Configuration`-backed `Context` with a Pydantic v2 model. The current implementation is correct and well-tested, but the validation backend (Pydantic) is fixed. This change introduces a swappable backend architecture and a msgspec implementation for performance comparison.

Key findings from the exploration phase:

- `msgspec.convert` resolves fields by `encode_name` exclusively — the Python attr name is silently ignored when a `field(name=...)` alias differs. `MergeEngine` outputs canonical Python attr names from env vars/argparse and raw YAML keys verbatim from files (which may be legacy alias names like `verify_ssl` or canonical names like `ssl_verify`). A pre-normalization dict (`_ALIAS_TO_CANONICAL`, 23 entries, ~0.45µs) translates alias keys to canonical before `msgspec.convert` is called. This is cheaper than any per-field alias lookup during convert.
- `__post_init__` overhead for the full validator set is small relative to schema construction. All 5 pydantic validators map cleanly to `__post_init__` with identical semantics.
- `ValueEnum.__str__` returns `.value`, so `str()` on enum instances is identical between pydantic (`use_enum_values=True`) and msgspec (stores enum instances). No `Context` property changes needed for enum fields.
- No circular init: `_rebuild()` reads `merged.get("conda_context_backend", "pydantic")` from the raw dict before constructing any schema object. `MergeEngine` is backend-agnostic.
- Measured speedup on a representative struct with validators: ~2.3× faster than pydantic. Full 113-field schema expected to show similar ratio.

## Goals / Non-Goals

**Goals:**
- Feature-complete msgspec schema that faithfully reimplements all validators.
- Swappable backend via `conda_context_backend` config field (`.condarc` or env var).
- Side-by-side pydantic vs msgspec benchmarks using identical inputs.
- Remove direct `pydantic` imports from `context.py` and `errors.py`.

**Non-Goals:**
- Making msgspec the default backend.
- Removing Pydantic.
- Migrating the schema generator.
- Integration with conda's plugin settings hook.

## Decisions

### D1: No `field(name=...)` aliases in `CondaConfigMsgspec`

`CondaConfigMsgspec` uses Python attribute names only. A `normalize_alias_keys(data)` step (using `_ALIAS_TO_CANONICAL`, 23 entries) runs before `msgspec.convert`. This is simpler, faster (no alias resolution during convert), and makes the Struct self-documenting. The 23 aliased fields are: `auto_update_conda` (alias `self_update`), `auto_activate` (`auto_activate_base`), `environment_specifier` (`env_spec`), `prefix_data_interoperability` (`pip_interop_enabled`), `disallowed_packages` (`disallow`), `root_prefix` (`root_dir`), `envs_dirs` (`envs_path`), `export_platforms` (`extra_platforms`), `ssl_verify` (`verify_ssl`), `client_ssl_cert` (`client_cert`), `client_ssl_cert_key` (`client_cert_key`), `add_anaconda_token` (`add_binstar_token`), `channels` (`channel`), `allowlist_channels` (`whitelist_channels`), `always_softlink` (`softlink`), `always_copy` (`copy`), `always_yes` (`yes`), `verbosity` (`verbose`), `json_output` (`json`), `solver` (`experimental_solver`), `anaconda_upload` (`binstar_upload`), `conda_build` (`conda-build`), `override_virtual_packages` (`virtual_packages`).

### D2: All validators in `__post_init__`, not `dec_hook`

A single `__post_init__` method implements all 5 validators. `dec_hook` would add per-type function call overhead on every field. `__post_init__` runs once after C-level construction, keeping the fast path intact.

The `ssl_verify: bool | str` validator normalizes `"true"`/`"false"` strings to `bool` using `object.__setattr__` after C-level construction. The Struct must not be declared `frozen=True`.

### D3: `FieldError` as the library-agnostic error unit

```python
@dataclass
class FieldError:
    loc: tuple[str, ...]   # field path, e.g. ("ssl_verify",)
    input: Any             # the raw invalid value
    msg: str               # human-readable error message
```

`PydanticBackend.errors(exc)` translates `pydantic.ValidationError.errors()` → `list[FieldError]`. `MsgspecBackend.errors(exc)` translates `msgspec.ValidationError` similarly. `CondaConfigError.__init__` accepts `list[FieldError]` — no longer coupled to any library.

### D4: Backend interface

```python
class BackendProtocol(Protocol):
    def build(self, data: dict[str, Any]) -> Any: ...
    def validate_single(self, field: str, value: Any) -> tuple[str, Any]: ...
    def field_metadata(self) -> dict[str, FieldMetadata]: ...
    def errors(self, exc: Exception) -> list[FieldError]: ...
```

`field_metadata()` returns a dict keyed by canonical field name with `.aliases`, `.description`, `.annotation` attributes. For `MsgspecBackend`, descriptions come from `_FIELD_DESCRIPTIONS` (same text as pydantic's `Field(description=...)`, verbatim).

### D5: `conda_context_backend` is a real schema field in both models

Added to `CondaConfig` (pydantic, `Field(default="pydantic")`) and `CondaConfigMsgspec` (msgspec, default `"pydantic"`). Added to `_ENV_VAR_MAP` as `"CONTEXT_BACKEND"`. Appears in `parameter_names`, `describe_parameter`, and `conda config --describe` like any other setting. Valid values: `"pydantic"`, `"msgspec"`.

### D6: `_rebuild()` reads backend from merged dict before schema construction

```python
def _rebuild(self):
    merged, provenance = engine.resolve()
    backend_name = merged.get("conda_context_backend", "pydantic")
    self._backend = get_backend(backend_name)
    self._config = self._backend.build(merged)
```

Selection cost is a single `dict.get()` — zero overhead.

### D7: Both pydantic and msgspec exceptions caught in `_rebuild()`

```python
import pydantic
import msgspec
...
except (pydantic.ValidationError, msgspec.ValidationError) as exc:
    raise CondaConfigError(self._backend.errors(exc), provenance) from exc
```

### D8: Benchmark fixtures

`full_merged_dict` (existing, canonical keys) — used by both pydantic and msgspec benchmarks unchanged.
`full_merged_dict_with_aliases` (new) — uses legacy alias names (`verify_ssl`, `self_update`, etc.) to exercise the `normalize_alias_keys` path specifically.

## Risks / Trade-offs

- `ssl_verify` string normalization in `__post_init__` uses `object.__setattr__` to mutate a non-frozen Struct. Idiomatic but subtle — the Struct must remain mutable (not `frozen=True`).
- `CondaConfigError` signature changes (`list[FieldError]` instead of `pydantic.ValidationError`) — exactly 3 call sites in `context.py` must be updated.
- msgspec `ValidationError` error format is different from pydantic's — the `MsgspecBackend.errors()` translation must be verified against the actual exception structure.
