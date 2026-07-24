## ADDED Requirements

### Requirement: All conda 26.5.3 configuration fields are modelled
The system SHALL provide a Pydantic v2 `BaseModel` subclass named `CondaConfig` that declares every configuration field present in `conda.base.context.Context` for conda version 26.5.3, with correct Python types, default values, field aliases, and docstrings matching conda's own documentation.

#### Scenario: Field count matches conda 26.5.3
- **WHEN** `CondaConfig.model_fields` is inspected
- **THEN** every public configuration key documented in conda 26.5.3's `Context` class is present as a named field

#### Scenario: Default values match conda defaults
- **WHEN** `CondaConfig()` is instantiated with no arguments
- **THEN** every field value equals the corresponding default defined in conda 26.5.3's `ParameterLoader` declarations

#### Scenario: Field aliases are honoured
- **WHEN** `CondaConfig` is instantiated with a dict that uses a conda alias (e.g., `"copy"` for `always_copy`, `"softlink"` for `always_softlink`)
- **THEN** the field is populated correctly without error

---

### Requirement: Primitive fields accept and coerce expected types
The system SHALL coerce string representations of booleans, integers, and floats to their native Python types, consistent with conda's existing coercion behaviour.

#### Scenario: String "true" coerced to bool
- **WHEN** `CondaConfig(add_pip_as_python_dependency="true")` is called
- **THEN** the field value is `True` (Python bool)

#### Scenario: String integer coerced to int
- **WHEN** `CondaConfig(number_channel_notices="3")` is called
- **THEN** the field value is `3` (Python int)

---

### Requirement: Enum fields validate membership
The system SHALL reject values not in the allowed set for enum-typed fields and raise a `CondaConfigError` identifying the field, the invalid value, and the set of valid choices.

#### Scenario: Invalid channel_priority value
- **WHEN** `CondaConfig(channel_priority="invalid")` is called
- **THEN** a `CondaConfigError` is raised naming the field `channel_priority` and listing `flexible`, `strict`, `disabled` as valid choices

#### Scenario: Valid channel_priority value accepted
- **WHEN** `CondaConfig(channel_priority="strict")` is called
- **THEN** no error is raised and the field value equals `ChannelPriority.STRICT`

---

### Requirement: Cross-field validation rules are enforced
The system SHALL enforce all cross-field constraints present in conda 26.5.3's `post_build_validation`, raising a `CondaConfigError` that identifies all failing fields.

#### Scenario: always_copy and always_softlink mutually exclusive
- **WHEN** `CondaConfig(always_copy=True, always_softlink=True)` is called
- **THEN** a `CondaConfigError` is raised naming both `always_copy` and `always_softlink` as conflicting

#### Scenario: client_ssl_cert_key requires client_ssl_cert
- **WHEN** `CondaConfig(client_ssl_cert_key="/path/to/key")` is called without `client_ssl_cert`
- **THEN** a `CondaConfigError` is raised naming `client_ssl_cert` as required

---

### Requirement: Schema is introspectable as JSON Schema
The system SHALL expose the full configuration schema as a JSON Schema document via `CondaConfig.model_json_schema()`, including field descriptions, types, defaults, and enum values.

#### Scenario: JSON Schema generation
- **WHEN** `CondaConfig.model_json_schema()` is called
- **THEN** the returned dict is a valid JSON Schema object containing a `properties` key with entries for every configuration field

---

### Requirement: Schema module is versioned
The system SHALL place `CondaConfig` for conda 26.5.3 in `conda_context/schemas/_26_5_3.py` and expose it via `conda_context.get_schema_for_version("26.5.3")`.

#### Scenario: Version lookup returns correct model
- **WHEN** `conda_context.get_schema_for_version("26.5.3")` is called
- **THEN** the returned class is `CondaConfig` from `conda_context.schemas._26_5_3`

#### Scenario: Unknown version raises clear error
- **WHEN** `conda_context.get_schema_for_version("99.0.0")` is called
- **THEN** a `ValueError` is raised naming `99.0.0` as unsupported and listing available versions
