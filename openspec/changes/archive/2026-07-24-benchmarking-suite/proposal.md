## Why

The new `conda-context` implementation uses eager loading — all configuration sources are parsed and validated on every `_rebuild()` call — whereas conda's own implementation uses lazy per-field loading. Before deciding whether to adopt lazy loading, we need empirical data on where the actual performance costs lie and how the two approaches compare, presented in a form suitable for sharing with colleagues.

## What Changes

- Add `pytest-benchmark` as a dev dependency and introduce `tests/test_benchmarks.py` covering cold-cache and warm-cache scenarios for `Context`, `MergeEngine`, and `CondaConfig` construction.
- Add a standalone `scripts/generate_benchmark_report.py` script that runs the benchmark suite and produces a self-contained HTML report with charts comparing this implementation against conda's lazy-loading approach.
- Benchmark fixtures and helpers (a shared `tests/conftest.py`) to support repeatable, isolated benchmark scenarios.

## Capabilities

### New Capabilities

- `benchmark-suite`: A pytest-benchmark test file (`tests/test_benchmarks.py`) covering cold and warm cache timing for the key configuration loading paths: `Context.__init__`, single `_rebuild()`, `MergeEngine.resolve()` in isolation, `CondaConfig(**merged)` in isolation, and `cached_property` warm access. Also includes equivalent benchmarks against conda's `Configuration` class for direct comparison.
- `benchmark-report`: A standalone script (`scripts/generate_benchmark_report.py`) that consumes pytest-benchmark JSON output and produces a self-contained HTML file with bar/box charts comparing this implementation to conda's, broken down by scenario (cold init, warm reads, single rebuild, etc.).

### Modified Capabilities

## Impact

- **New dev dependency**: `pytest-benchmark>=4` added to `pyproject.toml` (dev/test extras) and pixi dev feature.
- **New files**: `tests/test_benchmarks.py`, `scripts/generate_benchmark_report.py`, `tests/conftest.py`.
- **No runtime changes**: no changes to `src/conda_context/` source code.
- **CI**: benchmarks are marked with a custom `pytest` mark (`benchmark`) so they can be excluded from the normal test run (`pytest -m "not benchmark"`).
