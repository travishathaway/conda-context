## ADDED Requirements

### Requirement: Benchmark test file exists and is isolated from normal test run
A file `tests/test_benchmarks.py` SHALL exist containing all benchmark functions.
All benchmark functions SHALL be decorated with `@pytest.mark.benchmark` so that `pytest -m "not benchmark"` excludes them entirely.
The file SHALL import `pytest` and `pytest_benchmark` and fail with a clear error if `pytest-benchmark` is not installed.

#### Scenario: Normal test run excludes benchmarks
- **WHEN** the user runs `pytest -m "not benchmark"`
- **THEN** no functions from `tests/test_benchmarks.py` are collected or executed

#### Scenario: Benchmark-only run
- **WHEN** the user runs `pytest tests/test_benchmarks.py`
- **THEN** all `bench_*` functions are collected and executed

### Requirement: Shared fixtures in conftest.py
A `tests/conftest.py` SHALL be created providing at minimum:
- `condarc_file(tmp_path)` — a pytest fixture that writes a minimal `.condarc` YAML file to `tmp_path` and returns its `Path`.
- `conda_env_vars` — a pytest fixture that returns a representative `dict` of `CONDA_*` environment variable key/value pairs.
- `empty_merged_dict` — a pytest fixture returning the merged dict from `MergeEngine((), {}).resolve()[0]`.
- `full_merged_dict` — a pytest fixture returning the merged dict from `MergeEngine((condarc_path,), env_vars).resolve()[0]`.

#### Scenario: condarc_file fixture creates a readable file
- **WHEN** a test uses the `condarc_file` fixture
- **THEN** a `.condarc` file exists at the returned path and is parseable by `ruamel.YAML`

#### Scenario: empty_merged_dict fixture returns a dict
- **WHEN** a test uses the `empty_merged_dict` fixture
- **THEN** the returned value is a `dict` (possibly empty) with no file I/O at fixture setup time beyond the MergeEngine call

### Requirement: Cold-cache Context benchmarks
The benchmark file SHALL include cold-cache benchmarks for `Context` construction:
- `bench_context_init_empty`: benchmarks `Context((), None)` with no search path files and empty environment.
- `bench_context_init_with_file`: benchmarks `Context((condarc_path,), None)` with one YAML file present.

Each benchmark SHALL use the `benchmark` fixture from pytest-benchmark and SHALL call `benchmark(lambda: Context(...))` or equivalent to time the construction.

#### Scenario: bench_context_init_empty completes in reasonable time
- **WHEN** the benchmark is run
- **THEN** it completes at least 5 rounds without error and reports mean, stddev, and min times

#### Scenario: bench_context_init_with_file includes file I/O
- **WHEN** the benchmark is run with a real `.condarc` file in the search path
- **THEN** `MergeEngine._load_yaml_file` is called during each round (confirmed by benchmark completing with the file present)

### Requirement: Cold-cache MergeEngine benchmarks
The benchmark file SHALL include isolated `MergeEngine.resolve()` benchmarks:
- `bench_merge_engine_empty`: `MergeEngine((), environ={}).resolve()` — no files, no env vars.
- `bench_merge_engine_with_file`: `MergeEngine((condarc_path,), environ={}).resolve()` — one YAML file, no env vars.
- `bench_merge_engine_with_env_vars`: `MergeEngine((), environ=conda_env_vars).resolve()` — no files, representative env vars.

#### Scenario: MergeEngine benchmarks are independent of Context overhead
- **WHEN** `bench_merge_engine_empty` is run
- **THEN** no `Context` object is constructed; only `MergeEngine` and `resolve()` are timed

### Requirement: Cold-cache Pydantic model benchmarks
The benchmark file SHALL include isolated `CondaConfig` construction benchmarks:
- `bench_pydantic_empty`: `CondaConfig(**{})` — empty dict, all defaults.
- `bench_pydantic_full_merged`: `CondaConfig(**full_merged_dict)` — pre-computed merged dict passed in.

#### Scenario: Pydantic benchmarks do not perform file I/O
- **WHEN** either Pydantic benchmark is run
- **THEN** the merged dict is pre-computed (via fixture) and no `open()` calls occur during the timed section

### Requirement: Warm-cache property read benchmarks
The benchmark file SHALL include warm-cache benchmarks that access properties on an already-constructed `Context`:
- `bench_warm_property_read`: accesses `context.ssl_verify` on a pre-built `Context` object (times only the property read).
- `bench_warm_cached_property_first`: accesses `context.user_agent` for the first time after construction (times the deferred `cached_property` computation).
- `bench_warm_cached_property_second`: accesses `context.user_agent` twice — the second access is timed (should return from `_cache_` dict).

#### Scenario: Warm property read is faster than cold init
- **WHEN** both `bench_warm_property_read` and `bench_context_init_empty` are run
- **THEN** `bench_warm_property_read` mean time is at least one order of magnitude lower

### Requirement: Conda reference benchmarks
The benchmark file SHALL include equivalent benchmarks against conda's `conda.base.context.Context` class for comparison, guarded with `pytest.importorskip`:
- `bench_conda_init`: times `conda.base.context.Context.__init__` with an equivalent search path.
- `bench_conda_field_first_access`: times first access to `conda_ctx.ssl_verify` (triggers lazy load).
- `bench_conda_field_second_access`: times second access to `conda_ctx.ssl_verify` (returns from `_cache_`).

#### Scenario: Conda benchmarks skip gracefully when conda is not available
- **WHEN** `conda` is not importable
- **THEN** the conda benchmark functions are skipped with a clear skip message, not errored

#### Scenario: Conda lazy first access is slower than second access
- **WHEN** both `bench_conda_field_first_access` and `bench_conda_field_second_access` are run
- **THEN** `bench_conda_field_second_access` mean time is lower than `bench_conda_field_first_access` mean time

### Requirement: pytest-benchmark dependency declared
`pytest-benchmark>=4` SHALL be declared in `pyproject.toml` as a dev/test dependency.
The pixi dev feature in `pyproject.toml` (or `pixi.toml` if separate) SHALL also include `pytest-benchmark`.

#### Scenario: pytest-benchmark is installable via pip extras
- **WHEN** a user runs `pip install -e ".[dev]"` or `pip install -e ".[test]"`
- **THEN** `pytest-benchmark` is installed as part of that extras group
