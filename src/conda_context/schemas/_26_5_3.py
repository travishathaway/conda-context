"""
CondaConfig — Pydantic v2 model for conda 26.5.3 configuration.

Hand-written for conda 26.5.3. This module is the reference implementation
that the schema generator must match for subsequent conda releases.

All field names, types, defaults, and aliases match conda 26.5.3's
``Context`` class declarations exactly.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from conda_context.constants import (
    CONDA_LIST_FIELDS,
    DEFAULT_AGGRESSIVE_UPDATE_PACKAGES,
    DEFAULT_CHANNEL_ALIAS,
    DEFAULT_CHANNELS,
    DEFAULT_CONDA_LIST_FIELDS,
    DEFAULT_CONSOLE_REPORTER_BACKEND,
    DEFAULT_CUSTOM_CHANNELS,
    DEFAULT_SOLVER,
    NO_PLUGINS,
    REPODATA_FN,
    ROOT_ENV_NAME,
    ChannelPriority,
    DepsModifier,
    PathConflict,
    SafetyChecks,
    SatSolverChoice,
    UpdateModifier,
)


def _default_python_default() -> str:
    ver = sys.version_info
    return f"{ver.major}.{ver.minor}"


class CondaConfig(BaseModel):
    """Pydantic model for all conda 26.5.3 configuration fields.

    Field names match conda's public configuration keys. Private conda fields
    (those prefixed with ``_``) are exposed here without the underscore prefix
    since they represent the canonical user-facing config key names.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        use_enum_values=True,
        extra="ignore",  # ignore unknown keys from condarc
    )

    # ------------------------------------------------------------------
    # General behaviour
    # ------------------------------------------------------------------

    add_pip_as_python_dependency: bool = Field(
        default=True,
        description="Automatically add pip, wheel and setuptools as Python dependencies.",
    )
    allow_conda_downgrades: bool = Field(
        default=False,
        description="Allow conda itself to be downgraded.",
    )
    allow_cycles: bool = Field(
        default=True,
        description="Allow cyclic dependencies in the solver.",
    )
    allow_softlinks: bool = Field(
        default=False,
        description="Allow the use of soft-links when hard-links are not possible.",
    )
    auto_update_conda: bool = Field(
        default=True,
        alias="self_update",
        description="Automatically update conda when a newer version is available.",
    )
    auto_activate: bool = Field(
        default=True,
        alias="auto_activate_base",
        description="Automatically activate the base environment on shell start.",
    )
    default_activation_env: str = Field(
        default=ROOT_ENV_NAME,
        alias="default_activation_env",
        description="Default environment to activate on shell start.",
    )
    auto_stack: int = Field(
        default=0,
        description="Automatically stack environments when activating.",
    )
    notify_outdated_conda: bool = Field(
        default=True,
        description="Notify the user when conda is outdated.",
    )
    clobber: bool = Field(
        default=False,
        description="Allow clobbering of overlapping file paths within packages.",
    )
    changeps1: bool = Field(
        default=True,
        description="When activating an environment, change the shell prompt.",
    )
    env_prompt: str = Field(
        default="({default_env}) ",
        description="Template for the shell prompt when an environment is active.",
    )
    environment_specifier: str | None = Field(
        default=None,
        alias="env_spec",
        description="(Experimental) Environment specifier.",
    )
    create_default_packages: tuple[str, ...] = Field(
        default=(),
        alias="create_default_packages",
        description="Packages automatically installed into every new environment.",
    )
    register_envs: bool = Field(
        default=True,
        description="Register newly created environments in ~/.conda/environments.txt.",
    )
    protect_frozen_envs: bool = Field(
        default=True,
        description="Prevent modification of frozen (base) environments.",
    )
    default_python: str | None = Field(
        default_factory=_default_python_default,
        description="Default Python version to use when creating new environments.",
    )
    download_only: bool = Field(
        default=False,
        description="Only download packages; do not install or link.",
    )
    enable_private_envs: bool = Field(
        default=False,
        description="Enable private environments.",
    )
    force_32bit: bool = Field(
        default=False,
        description="Force conda to use 32-bit packages on 64-bit systems.",
    )
    non_admin_enabled: bool = Field(
        default=True,
        description="Allow non-admin users to install packages.",
    )
    prefix_data_interoperability: bool = Field(
        default=False,
        alias="pip_interop_enabled",
        description="Allow conda to interact with pip-installed packages.",
    )

    # ------------------------------------------------------------------
    # Threading
    # ------------------------------------------------------------------

    default_threads: int = Field(
        default=0,
        alias="default_threads",
        description="Default number of threads for all thread-pool operations. 0 = auto.",
    )
    repodata_threads: int = Field(
        default=0,
        alias="repodata_threads",
        description="Threads for repodata downloads. 0 = use default_threads.",
    )
    fetch_threads: int = Field(
        default=0,
        alias="fetch_threads",
        description="Threads for package downloads. 0 = use default_threads (or 5).",
    )
    verify_threads: int = Field(
        default=0,
        alias="verify_threads",
        description="Threads for package verification. 0 = use default_threads.",
    )
    execute_threads: int = Field(
        default=0,
        alias="execute_threads",
        description="Threads for package installation. 0 defaults to 1.",
    )

    # ------------------------------------------------------------------
    # Safety & Security
    # ------------------------------------------------------------------

    aggressive_update_packages: tuple[str, ...] = Field(
        default=tuple(DEFAULT_AGGRESSIVE_UPDATE_PACKAGES),
        alias="aggressive_update_packages",
        description="Packages that are aggressively updated to their latest versions.",
    )
    safety_checks: SafetyChecks = Field(
        default=SafetyChecks.warn,
        description="Safety checks level: disabled, warn, or enabled.",
    )
    extra_safety_checks: bool = Field(
        default=False,
        description="Enable additional (slower) safety checks.",
    )
    signing_metadata_url_base: str | None = Field(
        default=None,
        alias="signing_metadata_url_base",
        description="Base URL for package signing metadata.",
    )
    path_conflict: PathConflict = Field(
        default=PathConflict.clobber,
        description="How to handle path conflicts: clobber, warn, or prevent.",
    )
    pinned_packages: tuple[str, ...] = Field(
        default=(),
        description="Packages that are pinned to a specific version.",
    )
    disallowed_packages: tuple[str, ...] = Field(
        default=(),
        alias="disallow",
        description="Packages that are disallowed from being installed.",
    )
    rollback_enabled: bool = Field(
        default=True,
        description="Enable rollback on failed transactions.",
    )
    track_features: tuple[str, ...] = Field(
        default=(),
        description="Features to track (deprecated concept but still read).",
    )
    use_index_cache: bool = Field(
        default=False,
        description="Use cached repodata even if it has expired.",
    )
    separate_format_cache: bool = Field(
        default=False,
        description="Use separate cache directories for different repodata formats.",
    )

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    root_prefix: str = Field(
        default="",
        alias="root_dir",
        description="Path to the root conda prefix (base environment).",
    )
    envs_dirs: tuple[str, ...] = Field(
        default=(),
        alias="envs_path",
        description="Search path for conda environments.",
    )
    pkgs_dirs: tuple[str, ...] = Field(
        default=(),
        alias="pkgs_dirs",
        description="Directories where conda caches downloaded packages.",
    )
    subdir: str = Field(
        default="",
        alias="subdir",
        description="Platform subdirectory (e.g., linux-64). Empty = auto-detect.",
    )
    subdirs: tuple[str, ...] = Field(
        default=(),
        alias="subdirs",
        description="List of platform subdirectories to include in solves.",
    )
    export_platforms: tuple[str, ...] = Field(
        default=(),
        alias="extra_platforms",
        description="Additional platforms to include in exported environment files.",
    )

    # ------------------------------------------------------------------
    # Repodata / caching
    # ------------------------------------------------------------------

    local_repodata_ttl: bool | int = Field(
        default=1,
        description=(
            "How long to cache repodata locally. "
            "True/1 = respect Cache-Control; False/0 = always fetch."
        ),
    )

    # ------------------------------------------------------------------
    # Remote connection
    # ------------------------------------------------------------------

    ssl_verify: bool | str = Field(
        default=True,
        alias="verify_ssl",
        description=(
            "Verify SSL certificates. True/False or a path to a CA bundle "
            "or directory, or 'truststore' to use the OS certificate store."
        ),
    )
    client_ssl_cert: str | None = Field(
        default=None,
        alias="client_cert",
        description="Path to client SSL certificate.",
    )
    client_ssl_cert_key: str | None = Field(
        default=None,
        alias="client_cert_key",
        description="Path to client SSL certificate key.",
    )
    proxy_servers: dict[str, str | None] = Field(
        default_factory=dict,
        description="Proxy server URLs keyed by protocol (http, https, etc.).",
    )
    remote_connect_timeout_secs: float = Field(
        default=9.15,
        description="Timeout in seconds for establishing remote connections.",
    )
    remote_read_timeout_secs: float = Field(
        default=60.0,
        description="Timeout in seconds for reading remote responses.",
    )
    remote_max_retries: int = Field(
        default=3,
        description="Maximum number of retries for failed remote requests.",
    )
    remote_backoff_factor: int = Field(
        default=1,
        description="Backoff factor for retry delays.",
    )
    add_anaconda_token: bool = Field(
        default=True,
        alias="add_binstar_token",
        description="Automatically add Anaconda.org authentication token to requests.",
    )

    # ------------------------------------------------------------------
    # Channel configuration
    # ------------------------------------------------------------------

    allow_non_channel_urls: bool = Field(
        default=False,
        description="Allow URLs that are not valid channel URLs.",
    )
    channel_alias: str = Field(
        default=DEFAULT_CHANNEL_ALIAS,
        alias="channel_alias",
        description="Base URL prepended to channel shortnames.",
    )
    channel_priority: ChannelPriority = Field(
        default=ChannelPriority.FLEXIBLE,
        description="Channel priority: flexible, strict, or disabled.",
    )
    channels: tuple[str, ...] = Field(
        default=(),
        alias="channel",
        description="List of channels to search for packages.",
    )
    channel_settings: tuple[dict[str, str], ...] = Field(
        default=(),
        description="Per-channel settings.",
    )
    custom_channels: dict[str, str] = Field(
        default_factory=lambda: dict(DEFAULT_CUSTOM_CHANNELS),
        alias="custom_channels",
        description="Custom channel name → URL mappings.",
    )
    custom_multichannels: dict[str, list[str]] = Field(
        default_factory=dict,
        alias="custom_multichannels",
        description="Custom multichannel name → list of channel URLs.",
    )
    default_channels: tuple[str, ...] = Field(
        default=tuple(DEFAULT_CHANNELS),
        alias="default_channels",
        description="Default channels used when no channel is specified.",
    )
    migrated_channel_aliases: tuple[str, ...] = Field(
        default=(),
        alias="migrated_channel_aliases",
        description="Former channel aliases that should be treated as the current alias.",
    )
    migrated_custom_channels: dict[str, str] = Field(
        default_factory=dict,
        description="Migrated custom channel mappings.",
    )
    override_channels_enabled: bool = Field(
        default=True,
        description="Allow --override-channels CLI flag.",
    )
    show_channel_urls: bool | None = Field(
        default=None,
        description="Show channel URLs when displaying packages.",
    )
    use_local: bool = Field(
        default=False,
        description="Include the local channel (~/conda-bld) automatically.",
    )
    allowlist_channels: tuple[str, ...] = Field(
        default=(),
        alias="whitelist_channels",
        description="Only allow packages from these channels.",
    )
    denylist_channels: tuple[str, ...] = Field(
        default=(),
        description="Block packages from these channels.",
    )
    repodata_fns: tuple[str, ...] = Field(
        default=("current_repodata.json", REPODATA_FN),
        description="Repodata filenames to try, in order.",
    )
    use_only_tar_bz2: bool | None = Field(
        default=None,
        alias="use_only_tar_bz2",
        description="Force conda to use only .tar.bz2 packages.",
    )

    # ------------------------------------------------------------------
    # Installation behaviour
    # ------------------------------------------------------------------

    always_softlink: bool = Field(
        default=False,
        alias="softlink",
        description="Always use soft links when linking packages.",
    )
    always_copy: bool = Field(
        default=False,
        alias="copy",
        description="Always copy files when linking packages.",
    )
    always_yes: bool | None = Field(
        default=None,
        alias="yes",
        description="Automatically answer yes to confirmation prompts.",
    )

    # ------------------------------------------------------------------
    # Output / UX
    # ------------------------------------------------------------------

    verbosity: int = Field(
        default=0,
        alias="verbose",
        description="Verbosity level (0=normal, 1=verbose, 2=more verbose).",
    )
    debug: bool = Field(
        default=False,
        alias="debug",
        description="Enable debug logging.",
    )
    trace: bool = Field(
        default=False,
        alias="trace",
        description="Enable trace logging (more verbose than debug).",
    )
    dev: bool = Field(
        default=False,
        description="Enable development mode.",
    )
    dry_run: bool = Field(
        default=False,
        description="Only show what would be done without making changes.",
    )
    error_upload_url: str = Field(
        default="https://conda.io/conda-post/unexpected-error",
        alias="error_upload_url",
        description="URL for uploading unexpected error reports.",
    )
    force: bool = Field(
        default=False,
        description="Force operations even when unsafe.",
    )
    json_output: bool = Field(
        default=False,
        alias="json",
        description="Output in JSON format.",
    )
    console: str = Field(
        default=DEFAULT_CONSOLE_REPORTER_BACKEND,
        alias="console",
        description="Console reporter backend.",
    )
    list_fields: tuple[str, ...] = Field(
        default=tuple(DEFAULT_CONDA_LIST_FIELDS),
        description="Fields to display in `conda list` output.",
    )
    offline: bool = Field(
        default=False,
        description="Do not connect to the internet.",
    )
    quiet: bool = Field(
        default=False,
        description="Suppress non-error output.",
    )
    ignore_pinned: bool = Field(
        default=False,
        description="Ignore pinned package constraints.",
    )
    report_errors: bool | None = Field(
        default=None,
        alias="report_errors",
        description="Automatically report errors to the conda team.",
    )
    shortcuts: bool = Field(
        default=True,
        description="Create shortcuts for GUI applications on Windows.",
    )
    number_channel_notices: int = Field(
        default=5,
        description="Maximum number of channel notices to display.",
    )
    shortcuts_only: tuple[str, ...] = Field(
        default=(),
        description="Only create shortcuts for these packages.",
    )
    experimental: tuple[str, ...] = Field(
        default=(),
        description="Experimental features to enable.",
    )
    preview: tuple[str, ...] = Field(
        default=(),
        description="Preview features to enable.",
    )
    no_lock: bool = Field(
        default=False,
        description="Disable locking of the package cache.",
    )
    repodata_use_zst: bool = Field(
        default=True,
        description="Use zst-compressed repodata when available.",
    )
    repodata_use_shards: bool = Field(
        default=True,
        description="Use sharded repodata when available.",
    )
    envvars_force_uppercase: bool = Field(
        default=True,
        description="Force CONDA_* environment variables to uppercase.",
    )

    # ------------------------------------------------------------------
    # Solver configuration
    # ------------------------------------------------------------------

    deps_modifier: DepsModifier = Field(
        default=DepsModifier.NOT_SET,
        description="Modifier for dependency resolution behaviour.",
    )
    update_modifier: UpdateModifier = Field(
        default=UpdateModifier.UPDATE_SPECS,
        description="How to handle updates during install/update operations.",
    )
    sat_solver: SatSolverChoice = Field(
        default=SatSolverChoice.PYCOSAT,
        description="SAT solver backend to use (classic solver only).",
    )
    solver_ignore_timestamps: bool = Field(
        default=False,
        description="Ignore package timestamps when solving.",
    )
    solver: str = Field(
        default=DEFAULT_SOLVER,
        alias="experimental_solver",
        description="Solver plugin to use (e.g., 'libmamba', 'classic').",
    )
    force_remove: bool = Field(
        default=False,
        description="Force removal of packages even if it would break dependencies.",
    )
    force_reinstall: bool = Field(
        default=False,
        description="Force reinstallation of packages.",
    )
    target_prefix_override: str = Field(
        default="",
        description="Override the target prefix for operations.",
    )
    unsatisfiable_hints: bool = Field(
        default=True,
        description="Show hints when the solver cannot satisfy constraints.",
    )
    unsatisfiable_hints_check_depth: int = Field(
        default=2,
        description="Depth of the dependency graph to check for unsatisfiable hints.",
    )

    # ------------------------------------------------------------------
    # conda-build
    # ------------------------------------------------------------------

    bld_path: str = Field(
        default="",
        description="Path to the conda-build build directory.",
    )
    anaconda_upload: bool | None = Field(
        default=None,
        alias="binstar_upload",
        description="Automatically upload built packages to Anaconda.org.",
    )
    croot: str = Field(
        default="",
        alias="croot",
        description="Root directory for conda-build source caches and work folders.",
    )
    conda_build: dict[str, str] = Field(
        default_factory=dict,
        alias="conda-build",
        description="Settings passed directly to conda-build.",
    )

    # ------------------------------------------------------------------
    # Virtual packages
    # ------------------------------------------------------------------

    override_virtual_packages: dict[str, str | None] = Field(
        default_factory=dict,
        alias="virtual_packages",
        description="Override virtual package versions.",
    )

    # ------------------------------------------------------------------
    # Plugin configuration
    # ------------------------------------------------------------------

    no_plugins: bool = Field(
        default=bool(NO_PLUGINS),
        description="Disable all conda plugins.",
    )

    # ------------------------------------------------------------------
    # Field validators
    # ------------------------------------------------------------------

    @field_validator("ssl_verify", mode="before")
    @classmethod
    def _validate_ssl_verify(cls, v: Any) -> Any:
        """Validate ssl_verify: must be bool, a path to a CA bundle, or 'truststore'."""
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            if v.lower() in ("true", "1", "yes"):
                return True
            if v.lower() in ("false", "0", "no"):
                return False
            if sys.version_info < (3, 10) and v == "truststore":
                raise ValueError(
                    "`ssl_verify: truststore` is only supported on Python 3.10 or later"
                )
            if v != "truststore" and not Path(v).exists():
                raise ValueError(
                    f"ssl_verify value '{v}' must be a boolean, a path to a "
                    "certificate bundle file, a path to a directory containing "
                    "certificates of trusted CAs, or 'truststore' to use the "
                    "operating system certificate store."
                )
            return v
        return v

    @field_validator("channel_alias", mode="before")
    @classmethod
    def _validate_channel_alias(cls, v: Any) -> Any:
        """Validate channel_alias: must have a scheme/protocol."""
        if v and isinstance(v, str):
            from urllib.parse import urlparse

            parsed = urlparse(v)
            if not parsed.scheme:
                raise ValueError(f"channel_alias value '{v}' must have scheme/protocol.")
        return v

    @field_validator("default_python", mode="before")
    @classmethod
    def _validate_default_python(cls, v: Any) -> Any:
        """Validate default_python: must be of the form '[23].[0-9][0-9]?' or ''."""
        if v is None or v == "":
            return v
        if isinstance(v, str) and len(v) >= 3 and v[1] == ".":
            try:
                fv = float(v)
                if 2.0 <= fv < 4.0:
                    return v
            except ValueError:
                pass
        raise ValueError(f"default_python value '{v}' not of the form '[23].[0-9][0-9]?' or ''")

    @field_validator("list_fields", mode="before")
    @classmethod
    def _validate_list_fields(cls, v: Any) -> Any:
        """Validate list_fields: all values must be valid conda list column names."""
        if isinstance(v, list | tuple):
            invalid = set(v).difference(CONDA_LIST_FIELDS)
            if invalid:
                raise ValueError(
                    f"Invalid value(s): {sorted(invalid)}. "
                    f"Valid values are: {sorted(CONDA_LIST_FIELDS)}"
                )
        return v

    # ------------------------------------------------------------------
    # Cross-field validators (post_build_validation equivalents)
    # ------------------------------------------------------------------

    @model_validator(mode="after")
    def _cross_field_validation(self) -> CondaConfig:
        """Enforce cross-field constraints from conda's post_build_validation."""
        errors: list[str] = []

        if self.always_copy and self.always_softlink:
            errors.append(
                "'always_copy' and 'always_softlink' are mutually exclusive. "
                "Only one can be set to 'True'."
            )

        if self.client_ssl_cert_key and not self.client_ssl_cert:
            errors.append("'client_ssl_cert' is required when 'client_ssl_cert_key' is defined")

        if errors:
            raise ValueError("\n".join(errors))

        return self
