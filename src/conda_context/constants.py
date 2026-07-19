"""
Re-declarations of enum types and constants from conda.base.constants for conda 26.5.3.

These are reproduced here so that conda_context can be imported without conda installed.
They are semantically identical to the originals.
"""

from __future__ import annotations

import sys
from enum import Enum, EnumMeta
from typing import Final

# ---------------------------------------------------------------------------
# Enum helpers
# ---------------------------------------------------------------------------


class ValueEnum(Enum):
    """Subclass of Enum that returns the value as its str representation."""

    def __str__(self) -> str:
        return self.value


# ---------------------------------------------------------------------------
# Safety / path enums
# ---------------------------------------------------------------------------


class SafetyChecks(ValueEnum):
    disabled = "disabled"
    warn = "warn"
    enabled = "enabled"


class PathConflict(ValueEnum):
    clobber = "clobber"
    warn = "warn"
    prevent = "prevent"


# ---------------------------------------------------------------------------
# Solver enums
# ---------------------------------------------------------------------------


class DepsModifier(ValueEnum):
    """Flags to enable alternate handling of dependencies."""

    NOT_SET = "not_set"
    NO_DEPS = "no_deps"
    ONLY_DEPS = "only_deps"


class UpdateModifier(ValueEnum):
    SPECS_SATISFIED_SKIP_SOLVE = "specs_satisfied_skip_solve"
    FREEZE_INSTALLED = "freeze_installed"
    UPDATE_DEPS = "update_deps"
    UPDATE_SPECS = "update_specs"
    UPDATE_ALL = "update_all"


class SatSolverChoice(ValueEnum):
    PYCOSAT = "pycosat"
    PYCRYPTOSAT = "pycryptosat"
    PYSAT = "pysat"


# ---------------------------------------------------------------------------
# Channel priority (has a custom metaclass in conda for case-insensitive lookup)
# ---------------------------------------------------------------------------


class ChannelPriorityMeta(EnumMeta):
    def __call__(cls, value, *args, **kwargs):  # type: ignore[override]
        try:
            return super().__call__(value, *args, **kwargs)
        except ValueError:
            if isinstance(value, str):
                # Case-insensitive lookup
                for member in cls:
                    if member.value.lower() == value.lower():
                        return member
            raise


class ChannelPriority(ValueEnum, metaclass=ChannelPriorityMeta):
    STRICT = "strict"
    FLEXIBLE = "flexible"
    DISABLED = "disabled"


# ---------------------------------------------------------------------------
# Defaults and constants
# ---------------------------------------------------------------------------

APP_NAME: Final = "conda"

DEFAULT_CHANNEL_ALIAS: Final = "https://conda.anaconda.org"

DEFAULT_CHANNELS_UNIX: Final = (
    "https://repo.anaconda.com/pkgs/main",
    "https://repo.anaconda.com/pkgs/r",
)

DEFAULT_CHANNELS_WIN: Final = (
    "https://repo.anaconda.com/pkgs/main",
    "https://repo.anaconda.com/pkgs/r",
    "https://repo.anaconda.com/pkgs/msys2",
)

DEFAULT_CHANNELS: Final = DEFAULT_CHANNELS_WIN if sys.platform == "win32" else DEFAULT_CHANNELS_UNIX

DEFAULT_CUSTOM_CHANNELS: Final = {
    "pkgs/pro": "https://repo.anaconda.com",
}

DEFAULT_AGGRESSIVE_UPDATE_PACKAGES: Final = (
    "ca-certificates",
    "certifi",
    "openssl",
)

REPODATA_FN: Final = "repodata.json"

ROOT_ENV_NAME: Final = "base"

DEFAULT_SOLVER: Final = "libmamba"

DEFAULT_CONSOLE_REPORTER_BACKEND: Final = "classic"
DEFAULT_JSON_REPORTER_BACKEND: Final = "json"

DEFAULT_CONDA_LIST_FIELDS: Final = ("name", "version", "build", "channel_name")

CONDA_LIST_FIELDS: Final = {
    "arch": "Arch",
    "build": "Build",
    "build_number": "Build number",
    "channel": "Channel URL",
    "channel_name": "Channel",
    "constrains": "Constraints",
    "depends": "Dependencies",
    "dist_str": "Dist",
    "license": "License",
    "md5": "MD5",
    "name": "Name",
    "platform": "Platform",
    "sha256": "SHA256",
    "size": "Size",
    "subdir": "Subdir",
    "timestamp": "Timestamp",
    "url": "URL",
    "version": "Version",
}

NO_PLUGINS: Final = False

# YAML extensions recognised when scanning condarc directories
YAML_EXTENSIONS: Final = (".yml", ".yaml")

# Filenames treated as condarc regardless of extension
CONDARC_FILENAMES: Final = (".condarc", "condarc")

# Default search path for condarc files (mirrors conda 26.5.3)
if sys.platform == "win32":  # pragma: no cover
    SEARCH_PATH: tuple[str, ...] = (
        "C:/ProgramData/conda/.condarc",
        "C:/ProgramData/conda/condarc",
        "C:/ProgramData/conda/condarc.d/",
    )
else:
    SEARCH_PATH = (
        "/etc/conda/.condarc",
        "/etc/conda/condarc",
        "/etc/conda/condarc.d/",
        "/var/lib/conda/.condarc",
        "/var/lib/conda/condarc",
        "/var/lib/conda/condarc.d/",
    )

SEARCH_PATH += (
    "$CONDA_ROOT/.condarc",
    "$CONDA_ROOT/condarc",
    "$CONDA_ROOT/condarc.d/",
    "~/.config/conda/.condarc",
    "~/.config/conda/condarc",
    "~/.config/conda/condarc.d/",
    "~/.conda/.condarc",
    "~/.conda/condarc",
    "~/.conda/condarc.d/",
    "~/.condarc",
    "$CONDA_PREFIX/.condarc",
    "$CONDA_PREFIX/condarc",
    "$CONDA_PREFIX/condarc.d/",
    "$CONDARC",
)
