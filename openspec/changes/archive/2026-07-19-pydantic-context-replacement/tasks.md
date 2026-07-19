## 1. Project Scaffolding

- [x] 1.1 Add `pydantic>=2.0` and `ruamel.yaml>=0.18,<0.19` to `pyproject.toml` dependencies
- [x] 1.2 Add `conda==26.5.3` as a pixi dev dependency in `pyproject.toml`
- [x] 1.3 Create package structure: `src/conda_context/{schemas,generator}/` directories with `__init__.py` files
- [x] 1.4 Create `src/conda_context/constants.py` with re-declarations of all enums used by conda 26.5.3's Context (`ChannelPriority`, `DepsModifier`, `PathConflict`, `SafetyChecks`, `SatSolverChoice`, `UpdateModifier`)
- [x] 1.5 Configure pixi tasks for `test`, `lint`, and `generate` in `pyproject.toml`

## 2. Error Provenance System

- [x] 2.1 Create `src/conda_context/provenance.py` with `ProvenanceInfo` dataclass (`source_type`, `path`, `line`, `env_var`) and `ProvenanceMap` type alias (`dict[str, ProvenanceInfo]`)
- [x] 2.2 Create `src/conda_context/errors.py` with `CondaConfigError` wrapping Pydantic `ValidationError` + `ProvenanceMap`
- [x] 2.3 Implement `CondaConfigError.__str__` producing human-readable multi-line output with field, value, source location, expected type, and hint
- [x] 2.4 Implement `CondaConfigError.as_dict()` returning a JSON-serialisable list of field error dicts
- [x] 2.5 Implement hint generation for common patterns: string-valued boolean fields, invalid enum values, mutually exclusive field pairs
- [x] 2.6 Write tests for all `error-provenance` spec scenarios

## 3. Merge Engine

- [x] 3.1 Create `src/conda_context/merge.py` with `MergeEngine` class
- [x] 3.2 Implement `_expand_search_path()` mirroring conda's directory expansion and file-extension filtering
- [x] 3.3 Implement YAML file loading with `ruamel.yaml`, capturing per-key line numbers for provenance
- [x] 3.4 Implement `CONDA_*` environment variable reading and mapping to field names
- [x] 3.5 Implement argparse args merging
- [x] 3.6 Implement priority-ordered merge: last-wins for primitives, prepend/append for sequences (respecting `ParameterFlag`), deep-merge for maps
- [x] 3.7 Populate `ProvenanceMap` during merge, recording winning source per field
- [x] 3.8 Write tests for all `merge-engine` spec scenarios

## 4. Config Schema — conda 26.5.3

- [x] 4.1 Create `src/conda_context/schemas/_26_5_3.py` with `CondaConfig(BaseModel)` hand-written for all 60+ fields from conda 26.5.3's `Context`
- [x] 4.2 Declare all `PrimitiveParameter` fields with correct Python types, defaults, and aliases
- [x] 4.3 Declare all `SequenceParameter` fields as `tuple[T, ...]` with correct element types and defaults
- [x] 4.4 Declare all `MapParameter` fields as `dict[str, V]` with correct value types and defaults
- [x] 4.5 Implement `@field_validator` methods for standalone validators: `channel_alias_validation`, `ssl_verify_validation`, `default_python_validation`, `list_fields_validation`
- [x] 4.6 Implement `@model_validator(mode="after")` for all `post_build_validation` cross-field constraints
- [x] 4.7 Expose schema via `conda_context.get_schema_for_version(version: str)` in `src/conda_context/__init__.py`
- [x] 4.8 Verify `CondaConfig.model_json_schema()` includes all fields with descriptions
- [x] 4.9 Write tests for all `config-schema` spec scenarios

## 5. Context Class

- [x] 5.1 Create `src/conda_context/context.py` with `Context` class skeleton mirroring conda's `__init__` signature (`search_path`, `argparse_args`, `**kwargs`)
- [x] 5.2 Implement private attributes: `_cache_`, `raw_data`, `_argparse_args`, `_search_path`, `_validation_errors`
- [x] 5.3 Implement `_set_search_path()`, `_set_env_vars()`, `_set_argparse_args()`, `_reset_cache()` matching conda's `Configuration` signatures
- [x] 5.4 Wire `__init__` to call `MergeEngine`, then validate via `CondaConfig`, storing the result as `_config`; raise `CondaConfigError` on validation failure
- [x] 5.5 Implement all 60+ raw config field properties delegating to `_config`
- [x] 5.6 Implement all Tier 1 pure computed properties: `subdir`, `arch_name`, `platform`, `verbosity`, `log_level`, `default_threads`, `repodata_threads`, `fetch_threads`, `verify_threads`, `execute_threads`, `subdirs`, `default_activation_prefix`, `known_subdirs`, `export_platforms`, `bits`, `console`, `default_activation_env`, `create_default_packages`, `aggressive_update_packages`, `channels`, `channel_alias`, `migrated_channel_aliases`, `default_channels`, `custom_channels`, `custom_multichannels`, `use_only_tar_bz2`, `binstar_upload`, `trace`, `debug`, `info`, `verbose`, `override_virtual_packages`, `signing_metadata_url_base`, `user_agent`, `conda_build`, `conda_build_local_urls`
- [x] 5.7 Implement all Tier 2 filesystem-interrogating computed properties: `root_prefix`, `root_writable`, `envs_dirs`, `pkgs_dirs`, `trash_dir`, `default_prefix`, `active_prefix`, `shlvl`, `target_prefix`, `conda_prefix`, `av_data_dir`, `conda_build_local_paths`, `croot`, `local_build_root`, `config_files`
- [x] 5.8 Implement `post_build_validation()` method returning list of `ValidationError` for API compatibility
- [x] 5.9 Implement module-level `reset_context`, `stack_context`, `fresh_context`, `replace_context`, `stack_context_default`, `replace_context_default`, `context_stack`, and `context` singleton
- [x] 5.10 Write tests for all `context-class` spec scenarios

## 6. CondaRC Write API

- [x] 6.1 Create `src/conda_context/condarc.py` with `CondaRC` class
- [x] 6.2 Implement `CondaRC.load(path)` using `ruamel.yaml` round-trip loader
- [x] 6.3 Implement `CondaRC.create(path)` for in-memory empty file construction
- [x] 6.4 Implement `get(key)` and `get_all()` for reading current in-memory values
- [x] 6.5 Implement `set(key, value)` with immediate single-field type validation
- [x] 6.6 Implement `unset(key)` as a no-op-safe key removal
- [x] 6.7 Implement `prepend_channel(channel)`, `append_channel(channel)`, `add_to(key, value)`, `remove_from(key, value)`
- [x] 6.8 Implement `diff()` returning `{key: (old, new)}` for pending mutations
- [x] 6.9 Implement `save(strict=True)`: build candidate merged config → run full `CondaConfig` validation → atomic write with `ruamel.yaml`
- [x] 6.10 Implement atomic write (write to temp file, then `os.replace`) to ensure no partial writes on error
- [x] 6.11 Write tests for all `condarc-write-api` spec scenarios

## 7. Patch Helpers

- [x] 7.1 Create `src/conda_context/patch.py`
- [x] 7.2 Implement `patch_module()`: replace `conda.base.context.context` and `conda.base.context.Context` as module attributes; re-export context management functions
- [x] 7.3 Implement late-patch detection: check `sys.modules` for direct-binding conda modules and emit `RuntimeWarning` listing them
- [x] 7.4 Implement idempotency guard in `patch_module()` (no-op if already patched)
- [x] 7.5 Implement `install_import_hook()` returning an uninstallable hook object that redirects `conda.base.context` imports to `conda_context.context`
- [x] 7.6 Write tests for all `patch-helpers` spec scenarios

## 8. Schema Generator

- [x] 8.1 Create `src/conda_context/generator/__main__.py` with `extract` subcommand using `argparse`
- [x] 8.2 Implement GitHub raw file fetching for `conda/base/context.py` at a given tag
- [x] 8.3 Implement AST parser for `ParameterLoader(PrimitiveParameter(...))` declarations → Pydantic `Field` emit
- [x] 8.4 Implement AST parser for `SequenceParameter` and `MapParameter` declarations
- [x] 8.5 Implement alias extraction from `ParameterLoader(..., aliases=(...))`
- [x] 8.6 Implement `post_build_validation` parser → `@model_validator` emit
- [x] 8.7 Implement standalone validator function detection → `@field_validator` emit
- [x] 8.8 Ensure generated module imports only stdlib and pydantic (enum types sourced from `conda_context.constants`)
- [x] 8.9 Ensure deterministic field ordering (matches declaration order in conda source)
- [x] 8.10 Write tests for all `schema-generator` spec scenarios
- [x] 8.11 Run generator against conda 26.5.3 and diff output against hand-written `_26_5_3.py`; resolve all discrepancies

## 9. Integration and Validation

- [x] 9.1 Write an integration test that instantiates `Context` with a real conda 26.5.3 environment and asserts all public fields match the values returned by conda's own `context`
- [x] 9.2 Write an integration test for `patch_module()` that calls it in a subprocess before any conda imports and verifies `conda.base.context.context` is the replacement
- [x] 9.3 Write an end-to-end test for the `CondaRC` write API: create a temp `.condarc`, mutate via `CondaRC`, reload via `Context`, assert values round-trip correctly
- [x] 9.4 Verify the library imports cleanly in an environment without conda installed (only pydantic and ruamel.yaml present)
- [x] 9.5 Run the full test suite against conda 26.5.3 installed via pixi and confirm all tests pass
