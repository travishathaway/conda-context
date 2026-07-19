## ADDED Requirements

### Requirement: Context exposes all public configuration fields from conda 26.5.3
The system SHALL provide a `Context` class whose public attribute access interface matches conda 26.5.3's `Context` class for all non-deprecated configuration fields, returning values of the same Python types.

#### Scenario: Scalar field access
- **WHEN** a `Context` is instantiated and `context.ssl_verify` is accessed
- **THEN** the value is a `bool` or `str` (path to CA bundle), matching the merged config value

#### Scenario: Sequence field access
- **WHEN** `context.channels` is accessed
- **THEN** the value is a `tuple[str, ...]`

---

### Requirement: Context exposes all private attributes required by conda internals
The system SHALL expose the private attributes `_cache_`, `raw_data`, `_argparse_args`, `_search_path`, and `_validation_errors` with the same types and semantics as conda 26.5.3's `Context`.

#### Scenario: raw_data structure
- **WHEN** `context.raw_data` is accessed
- **THEN** it is a `dict` mapping source names (e.g., `"cmd_line"`, `"/home/user/.condarc"`) to parameter dicts

#### Scenario: _cache_ cleared on reset
- **WHEN** `context._reset_cache()` is called
- **THEN** `context._cache_` is an empty dict

---

### Requirement: Context supports the mutation protocol
The system SHALL implement `_set_search_path()`, `_set_env_vars()`, `_set_argparse_args()`, and `_reset_cache()` with the same call signatures as conda 26.5.3's `Configuration` base class.

#### Scenario: _set_argparse_args updates context values
- **WHEN** `context._set_argparse_args(Namespace(always_yes=True))` is called
- **THEN** `context.always_yes` returns `True`

#### Scenario: _reset_cache clears memoized values
- **WHEN** a computed property has been accessed and then `_reset_cache()` is called
- **THEN** the next access recomputes the value from current raw_data

---

### Requirement: Context participates in reset_context, stack_context, and fresh_context
The system SHALL provide module-level functions `reset_context`, `stack_context`, `fresh_context`, and `replace_context` in `conda_context.context` with the same signatures and semantics as those in `conda.base.context`.

#### Scenario: reset_context updates the global singleton
- **WHEN** `reset_context(args=Namespace(ssl_verify=False))` is called
- **THEN** `context.ssl_verify` returns `False`

#### Scenario: stack_context restores original state on exit
- **WHEN** a `with stack_context(["/tmp/test.condarc"], args=None):` block exits
- **THEN** `context` reflects the state it had before the block was entered

#### Scenario: fresh_context provides empty configuration
- **WHEN** `with fresh_context():` is entered
- **THEN** all configuration fields return their default values within the block

---

### Requirement: Context replicates all pure computed properties
The system SHALL implement all Tier 1 (pure computation) computed properties from conda 26.5.3's `Context`, including `subdir`, `arch_name`, `platform`, `verbosity`, `log_level`, `default_threads`, `repodata_threads`, `fetch_threads`, `verify_threads`, `execute_threads`, `subdirs`, and `default_activation_prefix`.

#### Scenario: subdir reflects current platform
- **WHEN** running on Linux x86_64 with no override set
- **THEN** `context.subdir` returns `"linux-64"`

#### Scenario: subdir respects _subdir override
- **WHEN** `_subdir` is set to `"osx-arm64"`
- **THEN** `context.subdir` returns `"osx-arm64"`

#### Scenario: fetch_threads default when both overrides are zero
- **WHEN** `_fetch_threads` and `_default_threads` are both `0`
- **THEN** `context.fetch_threads` returns `5`

---

### Requirement: Context replicates all filesystem-interrogating computed properties
The system SHALL implement all Tier 2 (filesystem-interrogating) computed properties from conda 26.5.3's `Context`, including `root_prefix`, `root_writable`, `envs_dirs`, `pkgs_dirs`, `trash_dir`, `default_prefix`, `active_prefix`, `conda_prefix`, `conda_build_local_paths`, and `croot`.

#### Scenario: envs_dirs returns only existing directories
- **WHEN** `_envs_dirs` is set to a list containing both an existing and a non-existing path
- **THEN** `context.envs_dirs` contains only the path that exists on disk

#### Scenario: root_writable reflects filesystem permissions
- **WHEN** the root prefix directory is not writable by the current user
- **THEN** `context.root_writable` returns `False`

---

### Requirement: Context singleton is accessible as a module-level attribute
The system SHALL expose a pre-initialised `context` singleton in `conda_context.context` that is created with the default conda search path at import time, mirroring `conda.base.context.context`.

#### Scenario: Module-level context is a Context instance
- **WHEN** `from conda_context.context import context` is executed
- **THEN** `context` is an instance of `conda_context.context.Context`

#### Scenario: Module-level context reflects system condarc files
- **WHEN** a condarc file exists in the default search path
- **THEN** `context` reflects values from that file
