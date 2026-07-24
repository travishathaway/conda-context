## ADDED Requirements

### Requirement: CondaConfigError carries field-level provenance information
The system SHALL provide a `CondaConfigError` exception class that wraps one or more Pydantic `ValidationError` instances and enriches each with a `ProvenanceInfo` object identifying the source of the invalid value (file path + line number, or environment variable name).

#### Scenario: Error from yaml file includes file path and line number
- **WHEN** `ssl_verify: yess` appears on line 7 of `~/.condarc` and validation fails
- **THEN** the raised `CondaConfigError` contains a field error for `ssl_verify` with `source_type="yaml_file"`, `path=Path("~/.condarc")`, and `line=7`

#### Scenario: Error from environment variable includes variable name
- **WHEN** `CONDA_SSL_VERIFY=yess` is set and validation fails
- **THEN** the raised `CondaConfigError` contains a field error for `ssl_verify` with `source_type="env_var"` and `env_var="CONDA_SSL_VERIFY"`

#### Scenario: Error for field with no provenance (default-derived) omits source
- **WHEN** a cross-field validation fails for a field that was not set in any source
- **THEN** the error for that field has no source attribution and does not raise a `KeyError`

---

### Requirement: CondaConfigError.__str__ produces a human-readable message
The system SHALL format `CondaConfigError` as a multi-line human-readable string that identifies the field name, the invalid value, the source location, the expected type or constraint, and an actionable hint where possible.

#### Scenario: Human-readable output for invalid yaml value
- **WHEN** `str(error)` is called on a `CondaConfigError` for `ssl_verify: yess` from `~/.condarc:7`
- **THEN** the string contains all of: the field name `ssl_verify`, the value `yess`, the file path `~/.condarc`, the line number `7`, and a description of the expected type

#### Scenario: Human-readable output for env var error
- **WHEN** `str(error)` is called on a `CondaConfigError` from `CONDA_SSL_VERIFY=yess`
- **THEN** the string contains the environment variable name `CONDA_SSL_VERIFY` and the expected type

#### Scenario: Multiple field errors are each formatted
- **WHEN** a `CondaConfigError` contains errors for both `always_copy` and `always_softlink`
- **THEN** `str(error)` contains a distinct section for each field

---

### Requirement: CondaConfigError.as_dict returns a machine-readable structure
The system SHALL provide an `as_dict()` method that returns a list of dicts, one per field error, each containing `field`, `value`, `message`, `hint`, and a `source` sub-dict with `type`, and conditionally `path`, `line`, or `env_var`.

#### Scenario: as_dict structure for yaml error
- **WHEN** `error.as_dict()` is called for a `ssl_verify` error from `~/.condarc:7`
- **THEN** the result is a list containing a dict with keys `field`, `value`, `message`, `hint`, and `source`, where `source` has `type="yaml_file"`, `path`, and `line`

#### Scenario: as_dict is JSON-serialisable
- **WHEN** `json.dumps(error.as_dict())` is called
- **THEN** no `TypeError` is raised (all values are JSON-compatible primitives)

---

### Requirement: Hints are generated for common misconfiguration patterns
The system SHALL include a human-readable `hint` in `CondaConfigError` for known misconfiguration patterns: boolean fields given string values, invalid enum values, and mutually exclusive field combinations.

#### Scenario: Hint for string-valued boolean field
- **WHEN** `ssl_verify: yess` is encountered
- **THEN** the error hint suggests the correct YAML boolean syntax (e.g., `ssl_verify: true`)

#### Scenario: Hint for invalid enum value
- **WHEN** `channel_priority: invalid` is encountered
- **THEN** the error hint lists the valid choices (`flexible`, `strict`, `disabled`)

#### Scenario: Hint for mutually exclusive fields
- **WHEN** both `always_copy: true` and `always_softlink: true` are set
- **THEN** the error hint explains they are mutually exclusive and which one to unset
