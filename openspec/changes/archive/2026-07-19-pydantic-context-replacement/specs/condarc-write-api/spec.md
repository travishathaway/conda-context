## ADDED Requirements

### Requirement: CondarC loads an existing .condarc file for reading and writing
The system SHALL provide a `CondarC` class with a `CondarC.load(path)` class method that reads an existing YAML file into memory, preserving comments, key ordering, and formatting for later round-trip serialization.

#### Scenario: Load existing file
- **WHEN** `CondarC.load(Path("~/.condarc"))` is called on a valid YAML file
- **THEN** a `CondarC` instance is returned with all key-value pairs from the file accessible

#### Scenario: Load non-existent file raises error
- **WHEN** `CondarC.load(Path("/nonexistent/.condarc"))` is called
- **THEN** a `FileNotFoundError` is raised

#### Scenario: Comments are preserved after round-trip
- **WHEN** a `.condarc` file containing inline YAML comments is loaded, a key is modified, and `save()` is called
- **THEN** the written file retains the original comments on unmodified keys

---

### Requirement: CondarC creates a new empty .condarc file
The system SHALL provide a `CondarC.create(path)` class method that initialises an in-memory empty configuration targeting the given path, without writing to disk until `save()` is called.

#### Scenario: Create does not write to disk immediately
- **WHEN** `CondarC.create(Path("/tmp/new.condarc"))` is called
- **THEN** the file at `/tmp/new.condarc` does NOT exist on disk yet

#### Scenario: Save after create writes a valid YAML file
- **WHEN** `CondarC.create(path).set("ssl_verify", False).save()` is called
- **THEN** the file at `path` exists and contains `ssl_verify: false`

---

### Requirement: CondarC.set writes a scalar, list, or map value
The system SHALL provide a `set(key, value)` method that updates or inserts a configuration key. Single-field type constraints SHALL be validated immediately; cross-field constraints are deferred to `save()`.

#### Scenario: Set a new scalar key
- **WHEN** `condarc.set("ssl_verify", False)` is called on a CondarC with no existing `ssl_verify`
- **THEN** `condarc.get("ssl_verify")` returns `False`

#### Scenario: Set overrides an existing key
- **WHEN** `ssl_verify` is already `True` and `condarc.set("ssl_verify", False)` is called
- **THEN** `condarc.get("ssl_verify")` returns `False`

#### Scenario: Set with invalid type raises immediately
- **WHEN** `condarc.set("ssl_verify", "yess")` is called
- **THEN** a `CondaConfigError` is raised before `save()` is called, identifying `ssl_verify` and the invalid value

---

### Requirement: CondarC.unset removes a key from this file
The system SHALL provide an `unset(key)` method that removes the key from the in-memory representation of this specific file. The effective configuration will then fall back to lower-priority sources.

#### Scenario: Unset removes key
- **WHEN** `condarc.unset("ssl_verify")` is called on a CondarC where `ssl_verify` is present
- **THEN** `condarc.get("ssl_verify")` returns `None`

#### Scenario: Unset on absent key is a no-op
- **WHEN** `condarc.unset("ssl_verify")` is called when `ssl_verify` is not present
- **THEN** no error is raised

---

### Requirement: CondarC provides list mutation methods for sequence fields
The system SHALL provide `prepend_channel(channel)`, `append_channel(channel)`, `add_to(key, value)`, and `remove_from(key, value)` methods for mutating sequence-typed fields.

#### Scenario: prepend_channel adds channel to front
- **WHEN** channels is `["defaults"]` and `condarc.prepend_channel("pytorch")` is called
- **THEN** `condarc.get("channels")` is `["pytorch", "defaults"]`

#### Scenario: append_channel adds channel to back
- **WHEN** channels is `["defaults"]` and `condarc.append_channel("conda-forge")` is called
- **THEN** `condarc.get("channels")` is `["defaults", "conda-forge"]`

#### Scenario: remove_from removes a specific value
- **WHEN** channels is `["pytorch", "defaults"]` and `condarc.remove_from("channels", "pytorch")` is called
- **THEN** `condarc.get("channels")` is `["defaults"]`

#### Scenario: remove_from absent value is a no-op
- **WHEN** `condarc.remove_from("channels", "nonexistent")` is called
- **THEN** no error is raised and the list is unchanged

---

### Requirement: CondarC.save validates against the full merged context before writing
The system SHALL, on `save()`, build a candidate merged configuration from all active condarc sources with this file's pending changes applied, run full `CondaConfig` validation on the candidate, and only write to disk if validation passes.

#### Scenario: Cross-field conflict caught at save
- **WHEN** `condarc.set("always_copy", True)` is called and `always_softlink: true` exists in another condarc layer, then `save()` is called
- **THEN** a `CondaConfigError` is raised naming the conflict before any bytes are written to disk

#### Scenario: Save writes atomically (no partial write on error)
- **WHEN** validation fails during `save()`
- **THEN** the target file's content is unchanged from before `save()` was called

#### Scenario: Save with strict=False skips cross-field validation
- **WHEN** `condarc.save(strict=False)` is called with a cross-field conflict present
- **THEN** the file is written without raising a cross-field `CondaConfigError`

---

### Requirement: CondarC.get_all returns all keys set in this file
The system SHALL provide a `get_all()` method that returns a dict of all key-value pairs explicitly set in this file (not defaults or values inherited from other sources).

#### Scenario: get_all returns only this file's keys
- **WHEN** `~/.condarc` sets `ssl_verify: false` and `channels: [defaults]`
- **THEN** `CondarC.load("~/.condarc").get_all()` returns `{"ssl_verify": False, "channels": ["defaults"]}`

---

### Requirement: CondarC.diff reports pending changes
The system SHALL provide a `diff()` method that returns a dict of `{key: (old_value, new_value)}` for all mutations made since the file was loaded or created, not yet persisted to disk.

#### Scenario: diff reflects pending mutations
- **WHEN** `condarc.set("ssl_verify", False)` is called on a file that had `ssl_verify: true`
- **THEN** `condarc.diff()` returns `{"ssl_verify": (True, False)}`

#### Scenario: diff is empty before any mutations
- **WHEN** a file is loaded and no mutations are made
- **THEN** `condarc.diff()` returns an empty dict
