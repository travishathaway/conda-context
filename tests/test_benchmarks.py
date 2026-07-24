"""
Benchmark suite for conda-context vs conda's own configuration loading.

Cold-cache benchmarks
---------------------
These time the cost of constructing objects from scratch on every round:

  bench_context_init_empty          Context((), None) — no files, empty env
  bench_context_init_with_file      Context((path,), None) — one YAML file
  bench_single_rebuild_empty        One _rebuild() call on an existing Context
  bench_merge_engine_empty          MergeEngine((), {}).resolve()
  bench_merge_engine_with_file      MergeEngine((path,), {}).resolve()
  bench_merge_engine_with_env_vars  MergeEngine((), env_vars).resolve()
  bench_pydantic_empty              CondaConfig(**{})
  bench_pydantic_full_merged        CondaConfig(**full_merged_dict)

Warm-cache benchmarks
---------------------
These time property access on a Context that is already constructed:

  bench_warm_property_read          ctx.ssl_verify (plain property)
  bench_warm_cached_property_first  ctx.user_agent first access (deferred)
  bench_warm_cached_property_second ctx.user_agent second access (cached)

CLI end-to-end benchmarks
--------------------------
These time a full subprocess invocation of the conda CLI.  They require
conda to be importable and condactx to be on PATH; they are skipped otherwise.

  bench_condactx_info               ``condactx info`` — via our patched Context
  bench_conda_info                  ``conda info``    — conda's own Context (reference)

Conda reference benchmarks
--------------------------
These require conda to be importable; they are skipped otherwise.

  bench_conda_init                  conda Context init (lazy-loading baseline)
  bench_conda_field_first_access    conda ctx.ssl_verify first access (lazy)
  bench_conda_field_second_access   conda ctx.ssl_verify second access (cached)

Run with timing enabled:
  pytest tests/test_benchmarks.py \\
      --benchmark-warmup=on \\
      --benchmark-min-rounds=10 \\
      --benchmark-json=benchmark_output.json

Run as a smoke test (no timing overhead):
  pytest tests/test_benchmarks.py --benchmark-disable

Exclude from normal test runs:
  pytest -m "not benchmark"
"""

from __future__ import annotations

import shutil as _shutil
from pathlib import Path

import pytest

pytest.importorskip("pytest_benchmark", reason="pytest-benchmark is required to run benchmarks")

from conda_context.context import Context  # noqa: E402
from conda_context.merge import MergeEngine  # noqa: E402
from conda_context.schemas._26_5_3 import CondaConfig  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Marker applied to every benchmark function so that
# ``pytest -m "not benchmark"`` skips this entire file.
pytestmark = pytest.mark.benchmark


def _make_context_no_env(search_path: tuple = ()) -> Context:
    """Build a Context with a controlled (empty) OS-environment contribution.

    We monkey-patch MergeEngine._load_env_vars for the duration of the
    construction so that real CONDA_* variables in the test runner's process
    do not pollute timings or cause unexpected validation errors.
    """
    import unittest.mock as mock

    with mock.patch.object(MergeEngine, "_load_env_vars", return_value=({}, {})):
        return Context(search_path, None)


# ---------------------------------------------------------------------------
# Cold-cache: Context construction
# ---------------------------------------------------------------------------


def test_bench_context_init_empty(benchmark):
    """Time Context((), None) with no search-path files and no env vars."""
    benchmark(_make_context_no_env, ())


def test_bench_context_init_with_file(benchmark, condarc_file: Path):
    """Time Context((path,), None) with one YAML file present."""

    def _build():
        import unittest.mock as mock

        with mock.patch.object(MergeEngine, "_load_env_vars", return_value=({}, {})):
            return Context((condarc_file,), None)

    benchmark(_build)


def test_bench_single_rebuild_empty(benchmark):
    """Time a single _rebuild() call on an already-initialised Context.

    The Context is built once outside the timed loop so that only the cost
    of one rebuild (one MergeEngine + one Pydantic validation) is measured.
    This isolates the per-rebuild cost from the 3× overhead in __init__.
    """
    import unittest.mock as mock

    with mock.patch.object(MergeEngine, "_load_env_vars", return_value=({}, {})):
        ctx = Context((), None)

    benchmark(ctx._rebuild)


# ---------------------------------------------------------------------------
# Cold-cache: MergeEngine in isolation
# ---------------------------------------------------------------------------


def test_bench_merge_engine_empty(benchmark):
    """Time MergeEngine((), environ={}).resolve() — no files, no env vars."""

    def _resolve():
        return MergeEngine((), environ={}).resolve()

    benchmark(_resolve)


def test_bench_merge_engine_with_file(benchmark, condarc_file: Path):
    """Time MergeEngine((path,), environ={}).resolve() — one YAML file."""

    def _resolve():
        return MergeEngine((condarc_file,), environ={}).resolve()

    benchmark(_resolve)


def test_bench_merge_engine_with_env_vars(benchmark, conda_env_vars: dict):
    """Time MergeEngine((), environ=conda_env_vars).resolve() — env vars only."""

    def _resolve():
        return MergeEngine((), environ=conda_env_vars).resolve()

    benchmark(_resolve)


# ---------------------------------------------------------------------------
# Cold-cache: Pydantic model construction in isolation
# ---------------------------------------------------------------------------


def test_bench_pydantic_empty(benchmark):
    """Time CondaConfig(**{}) — pure Pydantic construction, all defaults."""
    benchmark(CondaConfig)


def test_bench_pydantic_full_merged(benchmark, full_merged_dict: dict):
    """Time CondaConfig(**full_merged_dict) — realistic input, no I/O."""
    benchmark(CondaConfig, **full_merged_dict)


# ---------------------------------------------------------------------------
# Warm-cache: property reads on an already-built Context
# ---------------------------------------------------------------------------


def test_bench_warm_property_read(benchmark):
    """Time a single ctx.ssl_verify read (plain @property, no deferred work)."""
    import unittest.mock as mock

    with mock.patch.object(MergeEngine, "_load_env_vars", return_value=({}, {})):
        ctx = Context((), None)

    benchmark(lambda: ctx.ssl_verify)


def test_bench_warm_cached_property_first(benchmark):
    """Time the *first* access to ctx.user_agent (deferred cached_property).

    Each benchmark round evicts the cached value so that every round pays the
    first-access cost (platform.* calls + string assembly).
    """
    import unittest.mock as mock

    with mock.patch.object(MergeEngine, "_load_env_vars", return_value=({}, {})):
        ctx = Context((), None)

    def _setup():
        ctx.__dict__.pop("user_agent", None)

    def _access():
        return ctx.user_agent

    benchmark.pedantic(_access, setup=_setup, rounds=20, warmup_rounds=2)


def test_bench_warm_cached_property_second(benchmark):
    """Time the *second* access to ctx.user_agent (hot cache, near-zero cost).

    user_agent is accessed once in setup so that every timed round returns
    directly from the cached_property slot.
    """
    import unittest.mock as mock

    with mock.patch.object(MergeEngine, "_load_env_vars", return_value=({}, {})):
        ctx = Context((), None)

    # Prime the cache once.
    _ = ctx.user_agent

    benchmark(lambda: ctx.user_agent)


# ---------------------------------------------------------------------------
# Conda reference benchmarks (skipped when conda is not importable)
# ---------------------------------------------------------------------------

try:
    import conda.base.context as _conda_ctx_module  # type: ignore[import]

    _CONDA_AVAILABLE = True
except ImportError:
    _CONDA_AVAILABLE = False

_conda_skip = pytest.mark.skipif(
    not _CONDA_AVAILABLE,
    reason="conda is not importable — skipping conda reference benchmarks",
)

_CONDACTX_ON_PATH = _shutil.which("condactx") is not None

_cli_skip = pytest.mark.skipif(
    not (_CONDA_AVAILABLE and _CONDACTX_ON_PATH),
    reason="conda not importable or condactx not on PATH — skipping CLI benchmarks",
)


@_conda_skip
def test_bench_conda_init(benchmark, condarc_file: Path):
    """Time conda's own Context.__init__ with an equivalent search path.

    This is the lazy-loading baseline: conda reads all YAML files upfront but
    defers per-field parsing to first attribute access.
    """
    import unittest.mock as mock

    def _build():
        # Suppress CONDA_* env vars from the runner process (same isolation as
        # our own benchmarks) by stubbing _set_env_vars.
        with mock.patch.object(
            _conda_ctx_module.Context,
            "_set_env_vars",
            lambda self, *a, **kw: self,
        ):
            return _conda_ctx_module.Context(
                search_path=(condarc_file,),
                argparse_args=None,
            )

    benchmark(_build)


@_conda_skip
def test_bench_conda_field_first_access(benchmark, condarc_file: Path):
    """Time the *first* access to conda ctx.ssl_verify (lazy descriptor load).

    Each round resets the cache so that every round pays the lazy-parse cost.
    """
    import unittest.mock as mock

    with mock.patch.object(
        _conda_ctx_module.Context,
        "_set_env_vars",
        lambda self, *a, **kw: self,
    ):
        ctx = _conda_ctx_module.Context(
            search_path=(condarc_file,),
            argparse_args=None,
        )

    def _setup():
        ctx._reset_cache()

    def _access():
        return ctx.ssl_verify

    benchmark.pedantic(_access, setup=_setup, rounds=20, warmup_rounds=2)


@_conda_skip
def test_bench_conda_field_second_access(benchmark, condarc_file: Path):
    """Time the *second* access to conda ctx.ssl_verify (populated _cache_).

    ssl_verify is accessed once before the timed loop so every round returns
    directly from the _cache_ dict.
    """
    import unittest.mock as mock

    with mock.patch.object(
        _conda_ctx_module.Context,
        "_set_env_vars",
        lambda self, *a, **kw: self,
    ):
        ctx = _conda_ctx_module.Context(
            search_path=(condarc_file,),
            argparse_args=None,
        )

    # Prime the cache.
    _ = ctx.ssl_verify

    benchmark(lambda: ctx.ssl_verify)


# ---------------------------------------------------------------------------
# CLI end-to-end benchmarks (skipped when conda is not importable or
# condactx is not on PATH)
# ---------------------------------------------------------------------------


@_cli_skip
def test_bench_condactx_info(benchmark):
    """Time a full ``condactx info`` subprocess invocation end-to-end.

    This measures the wall-clock cost of running conda's ``info`` command
    through the condactx wrapper (our patched Context) including Python
    interpreter start-up, import time, and all conda initialisation.

    Uses pedantic mode with a small round count because each invocation
    takes hundreds of milliseconds.
    """
    import subprocess

    def _run():
        result = subprocess.run(
            ["condactx", "info"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"condactx info failed (exit {result.returncode}):\n{result.stderr}"
        )

    benchmark.pedantic(_run, rounds=5, warmup_rounds=1)


@_cli_skip
def test_bench_conda_info(benchmark):
    """Time a full ``conda info`` subprocess invocation end-to-end.

    This is the reference baseline for the CLI benchmark: the same
    ``conda info`` command run without the condactx wrapper, using
    conda's own unpatched Context. Paired with ``test_bench_condactx_info``
    to measure the overhead introduced by conda-context's import hook and
    eager-load strategy.

    Uses pedantic mode with a small round count because each invocation
    takes hundreds of milliseconds.
    """
    import subprocess

    def _run():
        result = subprocess.run(
            ["conda", "info"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"conda info failed (exit {result.returncode}):\n{result.stderr}"
        )

    benchmark.pedantic(_run, rounds=5, warmup_rounds=1)
