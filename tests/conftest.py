"""Shared pytest fixtures for the conda-context test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from conda_context.merge import MergeEngine

# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def condarc_file(tmp_path: Path) -> Path:
    """Write a minimal .condarc to *tmp_path* and return its Path.

    The file contains a representative set of non-default values so that
    benchmarks and tests that use it exercise real YAML parsing and field
    coercion rather than an empty file.
    """
    rc = tmp_path / ".condarc"
    rc.write_text(
        "ssl_verify: false\n"
        "channels:\n"
        "  - defaults\n"
        "  - conda-forge\n"
        "always_yes: true\n"
        "offline: false\n"
    )
    return rc


# ---------------------------------------------------------------------------
# Environment-variable helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def conda_env_vars() -> dict[str, str]:
    """Return a representative dict of CONDA_* environment variables.

    Values are chosen to exercise bool, int, and string coercion paths in
    MergeEngine._coerce_env_var without depending on any real env state.
    """
    return {
        "CONDA_ALWAYS_YES": "false",
        "CONDA_OFFLINE": "false",
        "CONDA_SSL_VERIFY": "true",
        "CONDA_CHANNELS": "defaults:conda-forge",
        "CONDA_VERBOSITY": "0",
        "CONDA_AUTO_UPDATE_CONDA": "true",
    }


# ---------------------------------------------------------------------------
# Pre-computed merged-dict fixtures (isolate Pydantic construction cost)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def empty_merged_dict() -> dict:
    """Merged dict produced by a no-file, no-env-var MergeEngine resolve.

    Useful for benchmarking CondaConfig(**empty_merged_dict) in isolation,
    without any filesystem I/O in the timed section.
    """
    merged, _ = MergeEngine((), environ={}).resolve()
    return merged


@pytest.fixture()
def full_merged_dict(condarc_file: Path, conda_env_vars: dict[str, str]) -> dict:
    """Merged dict from a one-file + representative-env-var resolve.

    Useful for benchmarking CondaConfig(**full_merged_dict) in isolation with
    realistic input, without filesystem I/O in the timed section.
    """
    merged, _ = MergeEngine((condarc_file,), environ=conda_env_vars).resolve()
    return merged
