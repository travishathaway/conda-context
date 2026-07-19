## ADDED Requirements

### Requirement: Generator CLI extracts field definitions from a conda Git tag
The system SHALL provide a `python -m conda_context.generator extract` CLI command that, given a conda Git tag (e.g., `26.5.3`), fetches `conda/base/context.py` from that tag via the GitHub API and emits a versioned Pydantic schema module to `conda_context/schemas/_<version>.py` (with dots replaced by underscores).

#### Scenario: Extract produces a versioned schema file
- **WHEN** `python -m conda_context.generator extract --conda-tag 26.5.3` is run
- **THEN** a file `conda_context/schemas/_26_5_3.py` is created containing a `CondaConfig(BaseModel)` class

#### Scenario: Extract handles unknown tag gracefully
- **WHEN** `python -m conda_context.generator extract --conda-tag 99.0.0` is run and the tag does not exist on GitHub
- **THEN** the command exits with a non-zero exit code and prints a human-readable error message

---

### Requirement: Generator maps ParameterLoader declarations to Pydantic fields
The system SHALL parse `ParameterLoader(PrimitiveParameter(...))`, `ParameterLoader(SequenceParameter(...))`, and `ParameterLoader(MapParameter(...))` declarations in conda's `context.py` and emit corresponding Pydantic `Field(...)` declarations with correct types, defaults, and aliases.

#### Scenario: PrimitiveParameter(bool) maps to Field of type bool
- **WHEN** the generator processes `add_pip_as_python_dependency = ParameterLoader(PrimitiveParameter(True))`
- **THEN** the emitted field is `add_pip_as_python_dependency: bool = Field(default=True, ...)`

#### Scenario: SequenceParameter maps to tuple field
- **WHEN** the generator processes a `SequenceParameter(PrimitiveParameter("", str))` loader
- **THEN** the emitted field type is `tuple[str, ...]`

#### Scenario: Aliases are preserved
- **WHEN** the generator processes `always_copy = ParameterLoader(PrimitiveParameter(False), aliases=("copy",))`
- **THEN** the emitted field includes `alias="copy"` or equivalent alias configuration in its `Field(...)`

---

### Requirement: Generator emits cross-field validators for post_build_validation rules
The system SHALL parse the `post_build_validation` method of conda's `Context` class and emit corresponding Pydantic `@model_validator(mode="after")` logic in the generated schema module.

#### Scenario: Mutually exclusive constraint is emitted
- **WHEN** the generator processes the `always_copy` / `always_softlink` check in `post_build_validation`
- **THEN** the generated `CondaConfig` contains a `@model_validator` that raises `ValidationError` when both are `True`

---

### Requirement: Generator emits field validators for standalone validator functions
The system SHALL detect standalone validator functions associated with `ParameterLoader` declarations (e.g., `channel_alias_validation`, `ssl_verify_validation`) and emit corresponding Pydantic `@field_validator` methods in the generated schema.

#### Scenario: ssl_verify validator is emitted
- **WHEN** the generator processes the `ssl_verify` `ParameterLoader` with `validation=ssl_verify_validation`
- **THEN** the generated `CondaConfig` contains a `@field_validator("ssl_verify")` that accepts bool or a valid file path string

---

### Requirement: Generated schema module is self-contained and importable without conda installed
The system SHALL emit schema modules that import only from the Python standard library and `pydantic`, with no runtime dependency on `conda`. Enum types used as field types SHALL be re-declared or imported from `conda_context.constants` rather than from `conda.base.constants`.

#### Scenario: Generated module imports without conda
- **WHEN** `import conda_context.schemas._26_5_3` is executed in an environment where `conda` is not installed
- **THEN** no `ImportError` is raised

#### Scenario: ChannelPriority enum is available without conda
- **WHEN** `from conda_context.schemas._26_5_3 import CondaConfig; CondaConfig(channel_priority="strict")` is called
- **THEN** no `ImportError` is raised and the field is accepted

---

### Requirement: Generator produces a diff-friendly output
The system SHALL emit generated schema modules with deterministic field ordering (matching the declaration order in conda's `context.py`) so that version-to-version diffs are minimal and reviewable.

#### Scenario: Field order is stable across runs
- **WHEN** the generator is run twice with the same conda tag
- **THEN** the two output files are byte-for-byte identical

#### Scenario: Version diff shows only changed fields
- **WHEN** two consecutive conda versions differ by one added field
- **THEN** `diff schemas/_26_5_3.py schemas/_26_7_0.py` shows exactly one added field declaration
