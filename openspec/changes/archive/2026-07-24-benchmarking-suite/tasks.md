## 1. Dependencies and Configuration

- [x] 1.1 Add `pytest-benchmark>=4` to the `[project.optional-dependencies]` dev/test extras in `pyproject.toml`
- [x] 1.2 Add `plotly>=5` to a new `[report]` optional-dependencies group in `pyproject.toml`
- [x] 1.3 Add `pytest-benchmark` to the pixi dev feature dependencies in `pyproject.toml`
- [x] 1.4 Register a `benchmark` pytest mark in `pyproject.toml` under `[tool.pytest.ini_options]` to suppress warnings about unknown marks

## 2. Shared Test Fixtures

- [x] 2.1 Create `tests/conftest.py` with a `condarc_file(tmp_path)` fixture that writes a minimal `.condarc` to `tmp_path` and returns the `Path`
- [x] 2.2 Add a `conda_env_vars` fixture to `tests/conftest.py` returning a representative `dict` of `CONDA_*` env var key/value pairs
- [x] 2.3 Add an `empty_merged_dict` fixture that returns `MergeEngine((), environ={}).resolve()[0]`
- [x] 2.4 Add a `full_merged_dict` fixture that uses `condarc_file` and `conda_env_vars` to return a merged dict from a one-file + env-var resolve

## 3. Benchmark Test File — Cold Cache

- [x] 3.1 Create `tests/test_benchmarks.py` with `@pytest.mark.benchmark` on all functions and a module-level `pytest.importorskip("pytest_benchmark")` guard
- [x] 3.2 Implement `bench_context_init_empty(benchmark)` — benchmarks `Context((), None)` with no env vars
- [x] 3.3 Implement `bench_context_init_with_file(benchmark, condarc_file)` — benchmarks `Context((condarc_file,), None)` with one YAML file
- [x] 3.4 Implement `bench_single_rebuild_empty(benchmark)` — constructs a `Context` before timed section, then benchmarks a single `_rebuild()` call
- [x] 3.5 Implement `bench_merge_engine_empty(benchmark)` — benchmarks `MergeEngine((), environ={}).resolve()`
- [x] 3.6 Implement `bench_merge_engine_with_file(benchmark, condarc_file)` — benchmarks `MergeEngine((condarc_file,), environ={}).resolve()`
- [x] 3.7 Implement `bench_merge_engine_with_env_vars(benchmark, conda_env_vars)` — benchmarks `MergeEngine((), environ=conda_env_vars).resolve()`
- [x] 3.8 Implement `bench_pydantic_empty(benchmark)` — benchmarks `CondaConfig(**{})`
- [x] 3.9 Implement `bench_pydantic_full_merged(benchmark, full_merged_dict)` — benchmarks `CondaConfig(**full_merged_dict)`

## 4. Benchmark Test File — Warm Cache

- [x] 4.1 Implement `bench_warm_property_read(benchmark)` — pre-builds a `Context`, benchmarks a single `ctx.ssl_verify` read
- [x] 4.2 Implement `bench_warm_cached_property_first(benchmark)` — pre-builds a `Context`, benchmarks first access to `ctx.user_agent` (triggers deferred computation)
- [x] 4.3 Implement `bench_warm_cached_property_second(benchmark)` — pre-builds a `Context` and accesses `ctx.user_agent` once in setup, then benchmarks the second access

## 5. Benchmark Test File — Conda Reference

- [x] 5.1 Add a module-level `conda = pytest.importorskip("conda.base.context")` guard at the top of the conda reference section
- [x] 5.2 Implement `bench_conda_init(benchmark, condarc_file)` — benchmarks `conda.base.context.Context.__init__` with an equivalent search path
- [x] 5.3 Implement `bench_conda_field_first_access(benchmark, condarc_file)` — pre-builds a conda `Context`, benchmarks first `ctx.ssl_verify` access (lazy load)
- [x] 5.4 Implement `bench_conda_field_second_access(benchmark, condarc_file)` — pre-builds a conda `Context` and accesses `ssl_verify` once in setup, benchmarks the second (cached) access

## 6. Report Generator Script

- [x] 6.1 Create `scripts/` directory and `scripts/generate_benchmark_report.py` with `argparse` CLI accepting: positional `json_path`, `--output` (default `benchmark_report.html`), `--title`
- [x] 6.2 Add a graceful import check for `plotly` at script startup — print install hint and exit 1 if missing
- [x] 6.3 Implement JSON loading and parsing of pytest-benchmark output format (extracting `name`, `stats.mean`, `stats.stddev`, and per-round `stats.data` from each benchmark entry)
- [x] 6.4 Implement logic to split benchmark names into `conda-context` vs `conda` groups (benchmarks prefixed `bench_conda_` are the reference group)
- [x] 6.5 Implement the grouped bar chart using `plotly.graph_objects.Bar` with error bars (±1 stddev), y-axis in µs, grouped bar mode
- [x] 6.6 Implement the box plot using `plotly.graph_objects.Box` with per-round data, side-by-side groups per scenario
- [x] 6.7 Implement the sortable summary HTML table (use `plotly.graph_objects.Table` or raw HTML with a small inline JS sort function)
- [x] 6.8 Implement the narrative interpretation section: compute and render prose citing actual values (largest cost scenario, triple-rebuild overhead ratio, cold init comparison, warm vs cold ratio)
- [x] 6.9 Assemble all figures and the narrative into a single HTML string using `plotly.io.to_html` with `include_plotlyjs=True` (self-contained) and write to the output path
- [x] 6.10 Verify the output HTML contains no external URLs (automated check in the script or a unit test)

## 7. Verification

- [x] 7.1 Run `pytest tests/test_benchmarks.py --benchmark-disable` to confirm benchmarks collect and run without the timing framework active (smoke test)
- [x] 7.2 Run `pytest tests/test_benchmarks.py --benchmark-warmup=on --benchmark-min-rounds=5 --benchmark-json=benchmark_output.json` and confirm JSON is produced
- [x] 7.3 Run `python scripts/generate_benchmark_report.py benchmark_output.json --output report.html` and confirm HTML file is produced
- [x] 7.4 Open `report.html` in a browser and visually confirm all three charts and the summary table render correctly
- [x] 7.5 Run `pytest -m "not benchmark"` and confirm no benchmark tests are collected
- [x] 7.6 Run `pytest tests/` (all tests including benchmarks disabled) and confirm existing tests still pass
