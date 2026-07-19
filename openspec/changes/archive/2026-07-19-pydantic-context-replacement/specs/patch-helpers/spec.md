## ADDED Requirements

### Requirement: patch_module replaces the conda.base.context singleton and class
The system SHALL provide a `patch_module()` function in `conda_context.patch` that replaces both `conda.base.context.context` (the singleton) and `conda.base.context.Context` (the class) with their `conda-context` equivalents by mutating the `conda.base.context` module's attributes.

#### Scenario: Patch replaces module-level context singleton
- **WHEN** `patch_module()` is called before any other `conda.*` module is imported
- **THEN** `conda.base.context.context` is an instance of `conda_context.context.Context`

#### Scenario: Patch replaces module-level Context class
- **WHEN** `patch_module()` is called
- **THEN** `conda.base.context.Context` is `conda_context.context.Context`

#### Scenario: Re-exported context management functions remain callable
- **WHEN** `patch_module()` is called
- **THEN** `conda.base.context.reset_context`, `stack_context`, `fresh_context`, and `replace_context` are callable and operate on the replaced context

---

### Requirement: patch_module warns when called after conda modules have been imported
The system SHALL detect whether any direct-binding conda modules (e.g., `conda.cli.main`, `conda.core.solve`) have already been imported at the time `patch_module()` is called and emit a `RuntimeWarning` if so, because those modules hold references to the original `context` object.

#### Scenario: Warning emitted when patching late
- **WHEN** `import conda.cli.main` is executed before `patch_module()` is called
- **THEN** `patch_module()` emits a `RuntimeWarning` naming at least one already-imported module

#### Scenario: No warning when patching before conda modules
- **WHEN** `patch_module()` is called before any `conda.*` modules beyond `conda.base.context` are imported
- **THEN** no `RuntimeWarning` is emitted

---

### Requirement: install_import_hook intercepts conda.base.context at import time
The system SHALL provide an `install_import_hook()` function that installs a `sys.meta_path` finder that intercepts the import of `conda.base.context` and returns the `conda_context.context` module in its place, ensuring the replacement is used regardless of import order.

#### Scenario: Import hook causes conda.base.context to resolve to replacement
- **WHEN** `install_import_hook()` is called before `import conda` is executed
- **THEN** `import conda.base.context; conda.base.context.context` is an instance of `conda_context.context.Context`

#### Scenario: Import hook can be uninstalled
- **WHEN** `install_import_hook()` returns a hook object and `hook.uninstall()` is called
- **THEN** `sys.meta_path` no longer contains the hook and subsequent imports of `conda.base.context` resolve to the original conda module

---

### Requirement: patch_module is idempotent
The system SHALL allow `patch_module()` to be called multiple times without error; subsequent calls after the first SHALL be no-ops.

#### Scenario: Second call to patch_module does not raise
- **WHEN** `patch_module()` is called twice in succession
- **THEN** no exception is raised and `conda.base.context.context` is still an instance of `conda_context.context.Context`
