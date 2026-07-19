## Context

`conda.base.context.Context` is a ~2333-line singleton built on a custom metaclass system (`ConfigurationType` / `Configuration`) that resolves configuration from five layered sources: system condarc files, user condarc, env-level condarc, `CONDA_*` environment variables, and CLI argparse args. It exposes 60+ raw configuration fields plus ~50 computed properties (some pure, some filesystem-interrogating). Validation errors today carry no source provenance — no file path, no line number, no actionable hint.

This library (`conda-context`) replaces that system with a Pydantic v2-backed implementation while maintaining structural API compatibility sufficient for both conda plugin use and monkey-patching `conda.base.context` at plugin initialization time.

The initial target is conda **26.5.3** exactly. Each conda release maps to exactly one `conda-context` release.

## Goals / Non-Goals

**Goals:**
- Pydantic v2 model covering all 60+ config fields from conda 26.5.3
- Layered merge engine that replicates conda's source priority and merge semantics (last-wins for primitives, prepend/append for sequences, deep-merge for maps)
- Per-field provenance tracking (source file + line number, or env var name) surfaced in validation errors
- Human-readable `CondaConfigError` with file/line attribution and actionable hints; machine-readable `.as_dict()` form
- `Context` class that mirrors conda's public and private API surface closely enough for plugin use and module-attribute monkey-patching
- All computed properties from conda's `Context` replicated (both pure-computation and filesystem-interrogating tiers)
- Full `.condarc` CRUD with comment-preserving round-trip serialization (`ruamel.yaml`) and pre-save full-context validation
- Dev-time schema generator that reads conda source at a given Git tag and emits a versioned `schemas/_XX_X_X.py`

**Non-Goals:**
- Full `isinstance(ctx, conda.base.context.Context)` structural subtyping (not inheriting from conda's class)
- Replacing conda's plugin system, solver, or any subsystem beyond the configuration layer
- Supporting conda versions other than the pinned target (multi-version compatibility within one release)
- Import-hook-level monkey-patching that intercepts imports before `conda.base.context` module execution (out of scope for v1; module-attribute patching at plugin entry point is sufficient)
- Async configuration loading

## Decisions

### D1: Pydantic as validation layer, not the Context class itself

**Decision:** `CondaConfig(BaseModel)` is an inner validation model. The outer `Context` class is hand-rolled to mirror conda's stateful singleton pattern.

**Rationale:** Conda's `Context` is a mutable singleton with a complex mutation protocol (`reset_context`, `stack_context`, `push/pop`, `_reset_cache`). Pydantic models are immutable-by-default value objects. Forcing the Context to *be* a Pydantic model would require fighting Pydantic's immutability and lifecycle model. Instead, Pydantic handles what it does well — type coercion, field validation, schema documentation — and the Context wrapper handles lifecycle, caching, and mutation.

**Alternative considered:** `Context(BaseModel)` directly, using `model_config = ConfigDict(frozen=False)`. Rejected because it leaks Pydantic internals into the public API surface and makes the mutation protocol awkward.

---

### D2: ProvenanceMap is built during merge, before Pydantic validation

**Decision:** The `MergeEngine` produces both a `merged_dict` and a `ProvenanceMap` (mapping field name → `ProvenanceInfo(source_type, path, line, env_var)`). These are computed before `CondaConfig` validation runs.

**Rationale:** By the time Pydantic sees a value, source information is already lost. The only way to enrich errors with file/line is to capture provenance during the merge phase and pass it alongside the dict to the validation step. When Pydantic raises, we look up `provenance[field_name]` to construct the full error.

**Alternative considered:** Post-hoc provenance lookup by re-reading the source files after a validation error. Rejected as fragile and slow — the file could have changed between load and error.

---

### D3: ruamel.yaml for CondarC write API

**Decision:** All `.condarc` file writes use `ruamel.yaml` in round-trip mode.

**Rationale:** Plain `PyYAML` strips comments and normalizes formatting on round-trip. Users expect their manually-written comments and key ordering to survive a `conda config --set` operation. `ruamel.yaml` preserves both.

**Alternative considered:** `PyYAML` with comment stripping accepted. Rejected — user experience regression for anyone with annotated condarc files.

---

### D4: Write API validates against full merged context (snapshot)

**Decision:** `CondarC.save()` builds a candidate merged config (current on-disk state + pending mutations applied in-memory), runs it through `MergeEngine` + `CondaConfig` validation, and only writes on success.

**Rationale:** Some validation rules are cross-field (`always_copy` and `always_softlink` are mutually exclusive; `client_ssl_cert_key` requires `client_ssl_cert`). These can only be caught by validating the full merged state, not a single field in isolation.

**Circular dependency note:** The in-memory candidate is fully constructed before any disk write occurs, so there is no risk of reading a partially-written file during validation.

**Alternative considered:** Eager validation on `set()` (before `save()`). Retained as an *additional* option — `CondarC` will validate immediately on `set()` for single-field constraints (type, enum membership) and defer cross-field constraints to `save()`.

---

### D5: Versioned schema modules (generated, not hand-written for each release)

**Decision:** Each conda version produces a `schemas/_XX_X_X.py` module containing the `CondaConfig` model for that version. For v1 (conda 26.5.3), this module is hand-written. A `generator/` dev tool will produce subsequent versions by parsing conda's source at the relevant Git tag.

**Rationale:** Manually tracking field changes across conda releases is error-prone. A generator makes version diffs explicit (`diff schemas/_26_5_3.py schemas/_26_7_0.py`) and reviewable. The hand-written v1 serves as the reference implementation the generator must match.

**Generator approach:** AST-parse `conda/base/context.py` at the target tag to extract `ParameterLoader` declarations, parameter types, defaults, aliases, and validator functions. Emit corresponding Pydantic `Field(...)` declarations and `@field_validator` / `@model_validator` methods.

---

### D6: Module-attribute monkey-patching only (no import hook in v1)

**Decision:** The `patch` module provides `patch_module()` which replaces `conda.base.context.context` (the singleton) and `conda.base.context.Context` (the class) as module attributes. No `sys.meta_path` import hook.

**Rationale:** ~96% of conda's codebase uses direct name binding (`from conda.base.context import context`). This means module-attribute patching only works reliably when applied *before* any other conda module has been imported. At a conda plugin entry point, this window is open. An import hook would work earlier but is substantially more complex and fragile. v1 targets the plugin-entry-point use case; the import hook is an explicit future enhancement.

**Implication:** `patch_module()` must be called as the very first action in a plugin's entry point, before any `conda.*` imports in the plugin's own code.

---

### D7: Computed properties use real filesystem access (no injection)

**Decision:** Tier 2 computed properties (`envs_dirs`, `root_writable`, `pkgs_dirs`, `trash_dir`, etc.) call the real filesystem directly, matching conda's existing behavior.

**Rationale:** The goal is a drop-in replacement, not a fully pure/injectable system. Filesystem injection would add significant interface complexity for limited benefit in the initial version.

**Testing implication:** Tests that need to control filesystem behavior should use `tmp_path` fixtures and real directories, or set `_root_prefix` / `_envs_dirs` override parameters to point at test directories — matching the approach conda's own test suite uses.

## Risks / Trade-offs

- **Import order fragility** → `patch_module()` documentation must clearly state it must be called before any other conda imports. Violation silently fails (original context continues to be used by already-bound names). Mitigation: add a runtime guard that checks whether known conda modules are already imported and warns loudly.

- **Private API drift** → Conda's private internals (`_cache_`, `_argparse_args`, `raw_data` structure) can change between versions without notice. Each `conda-context` version bump must audit these against the new conda tag. Mitigation: the generator's test suite asserts that the generated schema's public + private API surface matches what conda's tests exercise.

- **Pydantic version constraints** → Requiring Pydantic v2 may conflict with conda plugins that depend on Pydantic v1. Mitigation: declare `pydantic>=2.0` as a hard requirement; document clearly. Conda itself does not currently depend on Pydantic, so there is no internal conflict.

- **ruamel.yaml version stability** → `ruamel.yaml`'s API has historically been unstable across minor versions. Mitigation: pin `ruamel.yaml>=0.18,<0.19` and update deliberately.

- **Computed property parity gaps** → Some computed properties in conda involve deep internal logic (e.g., `channels` resolves aliases, deduplicates, validates allowlist/denylist using `Channel` model objects). Full parity requires either reimplementing or importing from conda. For the monkey-patch use case, importing from conda is fine; for standalone use in plugins without conda installed, these properties must be self-contained. Mitigation: mark properties that require conda as `requires_conda=True` in docstrings; raise a clear `ImportError` with instructions if accessed without conda present.

- **Cross-field validation on write** → Validating the full merged context on `CondarC.save()` means that an invalid *existing* config (pre-existing error in another condarc layer) can block writes of unrelated fields. Mitigation: provide a `CondarC.save(strict=False)` option that only validates the fields being mutated.

## Migration Plan

This is a new library — no migration of existing code is required to *install* it. Migration of conda internals (monkey-patch path) is opt-in at plugin entry point:

```
1. Install conda-context (pip / conda)
2. In plugin entry point (before any conda.* imports):
   from conda_context.patch import patch_module
   patch_module()
3. All subsequent conda code in the same process uses conda-context's Context
4. Rollback: remove the patch_module() call; conda's original context is restored
```

No database migrations, no file format changes, no breaking changes to conda's own API.

## Open Questions

- **Generator completeness**: The AST-based generator needs to handle validator functions defined outside the class (e.g., `channel_alias_validation`, `ssl_verify_validation`). What's the right strategy — inline them into the generated model, or reference the originals from conda source?

- **Standalone computed properties**: For the plugin use case (conda not installed), which computed properties are truly needed standalone vs. which can raise a clear "requires conda" error? Need to audit plugin author use cases.

- **`context_stack` replication**: Conda's `context_stack` (push/pop/replace protocol used heavily in tests) needs to be re-exported from `patch.py` when monkey-patching. Should `conda_context` ship its own `context_stack` implementation that operates on the `conda-context` Context, or delegate entirely to conda's?
