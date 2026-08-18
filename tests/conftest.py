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
# Pre-computed merged-dict fixtures (isolate schema construction cost)
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


@pytest.fixture()
def full_merged_dict_with_aliases(tmp_path: Path) -> dict:
    """Merged dict using legacy alias key names for all 23 aliased fields.

    Simulates a user who has written their .condarc using old alias names
    (e.g. ``verify_ssl`` instead of ``ssl_verify``, ``self_update`` instead of
    ``auto_update_conda``).  Used to benchmark the alias-normalization path
    in MsgspecBackend.build().
    """
    rc = tmp_path / ".condarc"
    rc.write_text(
        # Use alias names for all 23 aliased fields
        "verify_ssl: false\n"          # alias for ssl_verify
        "channel:\n"                    # alias for channels
        "  - defaults\n"
        "  - conda-forge\n"
        "yes: true\n"                   # alias for always_yes
        "verbose: 0\n"                  # alias for verbosity
        "copy: false\n"                 # alias for always_copy
        "softlink: false\n"             # alias for always_softlink
        "disallow: []\n"                # alias for disallowed_packages
        "self_update: true\n"           # alias for auto_update_conda
        "auto_activate_base: true\n"    # alias for auto_activate
        "pip_interop_enabled: false\n"  # alias for prefix_data_interoperability
        "extra_platforms: []\n"         # alias for export_platforms
        "client_cert: null\n"           # alias for client_ssl_cert
        "client_cert_key: null\n"       # alias for client_ssl_cert_key
        "add_binstar_token: true\n"     # alias for add_anaconda_token
        "whitelist_channels: []\n"      # alias for allowlist_channels
        "json: false\n"                 # alias for json_output
        "experimental_solver: classic\n"  # alias for solver
        "binstar_upload: null\n"        # alias for anaconda_upload
        "virtual_packages: {}\n"        # alias for override_virtual_packages
    )
    merged, _ = MergeEngine((rc,), environ={}).resolve()
    return merged

