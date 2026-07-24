## Context

`conda-context` replaces conda's `Configuration` class with a new `Context` backed by Pydantic v2. Conda's original uses a lazy-loading descriptor pattern (`ParameterLoader.__get__`) — fields are only parsed the first time they are accessed and cached in `_cache_`. This project currently uses fully eager loading: every `_rebuild()` call loads all sources and validates all 60+ fields via Pydantic immediately, and `__init__` calls `_rebuild()` three times.

Before deciding whether to change the loading strategy, we need measured data on what the actual costs are, and a clear comparison with conda's approach.

Two deliverables are required:
1. A `pytest-benchmark` test suite (`tests/test_benchmarks.py`) with cold and warm cache scenarios.
2. A standalone HTML report generator (`scripts/generate_benchmark_report.py`) that consumes the benchmark JSON output and produces charts suitable for a colleague presentation.

## Goals / Non-Goals

**Goals:**
- Measure all meaningful hot/cold-path costs: `Context.__init__`, single `_rebuild()`, `MergeEngine.resolve()` alone, `CondaConfig(**merged)` alone, and warm property reads.
- Provide equivalent benchmarks against conda's `Configuration` class for direct comparison.
- Output pytest-benchmark JSON that is consumed by the report generator.
- Produce a self-contained HTML file (no external CDN calls) with grouped bar charts and box plots.
- Keep benchmark marks isolated so `pytest -m "not benchmark"` excludes them from the normal test run.

**Non-Goals:**
- Changing any source code in `src/conda_context/` (no implementation changes in this change).
- Memory profiling (scope is timing only).
- CI integration of benchmarks (left to a future change).

## Decisions

### D1: pytest-benchmark as the timing framework

**Decision**: Use `pytest-benchmark>=4` (not `asv`, `pyperf`, or manual `timeit` loops).

**Rationale**: The project already uses pytest. pytest-benchmark integrates natively as a fixture, provides automatic warm-up rounds, statistics (mean, stddev, min, IQR), and produces machine-readable JSON. It also supports `--benchmark-compare` for regression detection later.

**Alternatives considered**:
- `asv`: Powerful but requires a separate runner and conda environment management that would conflict with pixi.
- `pyperf`: Excellent statistics but no pytest integration and more setup burden.
- Manual `timeit`: No statistics, no JSON output, no warm-up management.

### D2: Benchmark file lives in `tests/test_benchmarks.py`, not a separate directory

**Decision**: Place benchmarks alongside the existing test files in `tests/`.

**Rationale**: Keeps discovery simple (`pytest tests/test_benchmarks.py`). The `@pytest.mark.benchmark` decorator (combined with `pytest -m "not benchmark"`) provides sufficient isolation from the normal test suite.

### D3: Shared fixtures in `tests/conftest.py`

**Decision**: Introduce `tests/conftest.py` with shared fixtures used by both `test_benchmarks.py` and potentially the existing tests.

**Rationale**: No `conftest.py` exists today — helpers are duplicated as module-level functions. The benchmark tests need shared tmp_path-based YAML file fixtures and an isolated environment dict. Centralising these in `conftest.py` avoids duplication.

**Key fixtures**:
- `condarc_file(tmp_path)` — writes a minimal `.condarc` and returns the `Path`.
- `conda_env_vars` — returns a dict of representative `CONDA_*` env vars for benchmarking.
- `empty_merged_dict` — returns the raw merged dict from a no-file, no-env-var resolve (for isolating `CondaConfig` construction).
- `full_merged_dict` — returns the merged dict from a single YAML + env var resolve.

### D4: HTML report uses Plotly (bundled) via `plotly.io.to_html`

**Decision**: Use `plotly` to render charts in the HTML report. The report script bundles the Plotly JS inline (using `include_plotlyjs="cdn"` is explicitly avoided; use `include_plotlyjs=True` for self-contained output).

**Rationale**: Plotly produces interactive charts (hover for exact values, zoom) which are more useful in a presentation than static matplotlib PNGs. The self-contained option means no external dependencies at viewing time.

**Alternatives considered**:
- `matplotlib` + `base64` PNG embedding: Static, harder to read exact values.
- `bokeh`: Similar capability to Plotly but larger bundle and less familiar to most colleagues.
- Raw `Chart.js` via a Jinja2 template: More portable but requires manual layout work.

### D5: Report script is a standalone Python script, not a pytest plugin

**Decision**: `scripts/generate_benchmark_report.py` is invoked directly (`python scripts/generate_benchmark_report.py <benchmark.json> --output report.html`), not as a pytest hook or plugin.

**Rationale**: Decouples the report from the test run. Users can re-run the report against saved JSON without re-running benchmarks. Also makes the script inspectable and editable without understanding pytest internals.

### D6: Benchmark scenarios

The benchmark file covers these scenarios (each is a separate `bench_*` function):

| Scenario | What it measures | Cache state |
|---|---|---|
| `bench_context_init_empty` | `Context((), None)` — no files, no env | Cold |
| `bench_context_init_with_file` | `Context((path,), None)` — one YAML file | Cold |
| `bench_single_rebuild_empty` | One `_rebuild()` call after init | Cold |
| `bench_merge_engine_empty` | `MergeEngine((), {}).resolve()` | Cold |
| `bench_merge_engine_with_file` | `MergeEngine((path,), {}).resolve()` | Cold |
| `bench_merge_engine_with_env_vars` | `MergeEngine((), env_vars).resolve()` | Cold |
| `bench_pydantic_empty` | `CondaConfig(**{})` | Cold (CPU only) |
| `bench_pydantic_full_merged` | `CondaConfig(**full_merged_dict)` | Cold (CPU only) |
| `bench_warm_property_read` | `ctx.ssl_verify` (post-init) | Warm |
| `bench_warm_cached_property_first` | `ctx.user_agent` first access | Warm (deferred) |
| `bench_warm_cached_property_second` | `ctx.user_agent` second access | Hot (cached) |
| `bench_conda_init` | `conda Configuration.__init__` with same search path | Cold (conda reference) |
| `bench_conda_field_first_access` | `conda_ctx.ssl_verify` first access | Warm (lazy) |
| `bench_conda_field_second_access` | `conda_ctx.ssl_verify` second access | Hot (cached) |

## Risks / Trade-offs

- **Filesystem noise** → Mitigation: Use `tmp_path` for all file-based benchmarks. pytest-benchmark's `--benchmark-warmup` and multiple rounds average over filesystem cache effects.
- **conda availability** → Mitigation: The conda comparison benchmarks are guarded with `pytest.importorskip("conda.base.context")`. If conda is not available, those benchmarks are skipped rather than erroring.
- **Triple-rebuild in `__init__`** → This is an existing limitation being measured, not fixed here. The benchmark will quantify it clearly (`bench_context_init_empty` will show ~3× the cost of `bench_single_rebuild_empty`).
- **plotly dependency for report** → `plotly` is not a runtime dependency. It is declared as an optional `[report]` extra in `pyproject.toml`. Users who only want raw JSON can skip it.
