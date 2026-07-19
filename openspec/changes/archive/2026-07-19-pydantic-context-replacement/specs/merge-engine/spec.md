## ADDED Requirements

### Requirement: Sources are resolved in conda's documented priority order
The system SHALL resolve configuration values from five named sources in ascending priority order: system condarc files, user condarc (`~/.condarc`), environment-level condarc (`$CONDA_PREFIX/.condarc`), `CONDA_*` environment variables, and argparse CLI arguments. A higher-priority source SHALL win for primitive fields.

#### Scenario: CLI arg overrides condarc value
- **WHEN** `~/.condarc` sets `ssl_verify: false` and argparse args set `ssl_verify=True`
- **THEN** the merged dict contains `ssl_verify: True`

#### Scenario: Env var overrides condarc value
- **WHEN** `~/.condarc` sets `always_yes: false` and `CONDA_ALWAYS_YES=1` is set in the environment
- **THEN** the merged dict contains `always_yes: True`

#### Scenario: Lower-priority file wins when higher-priority is absent
- **WHEN** the system condarc sets `ssl_verify: false` and no user condarc exists
- **THEN** the merged dict contains `ssl_verify: False`

---

### Requirement: Sequence fields follow prepend/append merge semantics
The system SHALL merge sequence-typed fields (e.g., `channels`, `pinned_packages`) using conda's prepend-by-default rule: a higher-priority source's list is prepended before the lower-priority source's list, unless the sequence parameter is configured for append.

#### Scenario: Channels from user condarc prepend system channels
- **WHEN** the system condarc defines `channels: [defaults]` and the user condarc defines `channels: [pytorch]`
- **THEN** the merged channels list is `["pytorch", "defaults"]`

#### Scenario: List append flag overrides prepend
- **WHEN** a condarc uses the `append` flag for a sequence field
- **THEN** the flagged items are appended after lower-priority items rather than prepended

---

### Requirement: Map fields are deep-merged across sources
The system SHALL merge map-typed fields (e.g., `proxy_servers`, `custom_channels`) by combining keys from all sources, with higher-priority sources' values winning on key collision.

#### Scenario: Distinct keys from two sources are both present
- **WHEN** the system condarc defines `proxy_servers: {http: proxy1}` and the user condarc defines `proxy_servers: {https: proxy2}`
- **THEN** the merged result contains both `http` and `https` keys

#### Scenario: Key collision resolved by priority
- **WHEN** both system and user condarc define `proxy_servers: {http: ...}` with different values
- **THEN** the user condarc's value wins

---

### Requirement: MergeEngine produces a ProvenanceMap alongside the merged dict
The system SHALL return a `ProvenanceMap` mapping each field name to a `ProvenanceInfo` object that records the winning source's type (`yaml_file`, `env_var`, or `argparse`), file path (for yaml sources), line number (for yaml sources), and environment variable name (for env var sources).

#### Scenario: Provenance recorded for yaml-sourced field
- **WHEN** `ssl_verify: false` appears on line 4 of `~/.condarc` and is not overridden
- **THEN** `provenance["ssl_verify"]` has `source_type="yaml_file"`, `path=Path("~/.condarc")`, `line=4`

#### Scenario: Provenance recorded for environment variable
- **WHEN** `CONDA_ALWAYS_YES=1` is set and no higher-priority source overrides it
- **THEN** `provenance["always_yes"]` has `source_type="env_var"` and `env_var="CONDA_ALWAYS_YES"`

#### Scenario: Fields at default have no provenance entry
- **WHEN** a field is not set in any source and takes its compiled-in default
- **THEN** `provenance.get("field_name")` returns `None`

---

### Requirement: MergeEngine accepts an explicit search path
The system SHALL accept an ordered list of file paths and/or directories as its search path, expanding directories to YAML files in sorted order, consistent with conda's `_expand_search_path` behaviour.

#### Scenario: Directory in search path is expanded
- **WHEN** a directory containing `a.yaml` and `b.yaml` is in the search path
- **THEN** both files are loaded, in sorted filename order, with `a.yaml` having lower priority

#### Scenario: Non-existent paths are silently skipped
- **WHEN** the search path contains a path that does not exist on disk
- **THEN** no error is raised and the path is ignored

#### Scenario: Malformed YAML files emit a warning and are skipped
- **WHEN** a condarc file in the search path contains invalid YAML
- **THEN** a warning is logged identifying the file and the file is skipped without raising an exception
