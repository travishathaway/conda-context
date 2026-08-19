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
        description=(
            "When allow_softlinks is True, conda uses hard-links when possible, and soft-links\n"
            "(symlinks) when hard-links are not possible, such as when installing on a\n"
            "different filesystem than the one that the package cache is on. When\n"
            "allow_softlinks is False, conda still uses hard-links when possible, but when it\n"
            "is not possible, conda copies files. Individual packages can override\n"
            "this setting, specifying that certain files should never be soft-linked (see the\n"
            "no_link option in the build recipe documentation).\n"
        ),
    )
    auto_update_conda: bool = Field(
        default=True,
        alias="self_update",
        description="Automatically update conda when a newer or higher priority version is detected.\n",  # noqa: E501
    )
    auto_activate: bool = Field(
        default=True,
        alias="auto_activate_base",
        description=(
            "Automatically activate the environment given at 'default_activation_env'\n"
            "during shell initialization.\n"
        ),
    )
    default_activation_env: str = Field(
        default=ROOT_ENV_NAME,
        alias="default_activation_env",
        description=(
            "The environment to be automatically activated on startup if 'auto_activate'\n"
            "is True. Also sets the default environment to activate when 'conda activate'\n"
            "receives no arguments.\n"
        ),
    )
    auto_stack: int = Field(
        default=0,
        description=(
            "Implicitly use --stack when using activate if current level of nesting\n"
            "(as indicated by CONDA_SHLVL environment variable) is less than or equal to\n"
            "specified value. 0 or false disables automatic stacking, 1 or true enables\n"
            "it for one level.\n"
        ),
    )
    notify_outdated_conda: bool = Field(
        default=True,
        description=(
            "Notify if a newer version of conda is detected during a create, install, update,\n"
            "or remove operation.\n"
        ),
    )
    clobber: bool = Field(
        default=False,
        description="Allow clobbering of overlapping file paths within packages.",
    )
    changeps1: bool = Field(
        default=True,
        description=(
            "When using activate, change the command prompt ($PS1) to include the\n"
            "activated environment.\n"
        ),
    )
    env_prompt: str = Field(
        default="({default_env}) ",
        description=(
            "Template for prompt modification based on the active environment. Currently\n"
            "supported template variables are '{prefix}', '{name}', and '{default_env}'.\n"
            "'{prefix}' is the absolute path to the active environment. '{name}' is the\n"
            "basename of the active environment prefix. '{default_env}' holds the value\n"
            "of '{name}' if the active environment is a conda named environment ('-n'\n"
            "flag), or otherwise holds the value of '{prefix}'. Templating uses python's\n"
            "str.format() method.\n"
        ),
    )
    environment_specifier: str | None = Field(
        default=None,
        alias="env_spec",
        description=(
            "**EXPERIMENTAL** While experimental, expect both major and minor changes across minor releases.\n"  # noqa: E501
            "\n"
            "The name of the environment specifier plugin that should be used for this context.\n"
            "If not specified, the plugin manager will try to detect the plugin to use.\n"
        ),
    )
    create_default_packages: tuple[str, ...] = Field(
        default=(),
        alias="create_default_packages",
        description="Packages that are by default added to a newly created environments.\n",
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
        description=(
            "Solve an environment and ensure package caches are populated, but exit\n"
            "prior to unlinking and linking packages into the prefix\n"
        ),
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
        description=(
            "Allows completion of conda's create, install, update, and remove operations, for\n"
            "non-privileged (non-root or non-administrator) users.\n"
        ),
    )
    prefix_data_interoperability: bool = Field(
        default=False,
        alias="pip_interop_enabled",
        description="Enable plugins to allow conda to interact with non-conda-installed packages.\n",  # noqa: E501
    )

    # ------------------------------------------------------------------
    # Threading
    # ------------------------------------------------------------------

    default_threads: int = Field(
        default=0,
        alias="default_threads",
        description=(
            "Threads to use by default for parallel operations.  Default is None,\n"
            "which allows operations to choose themselves.  For more specific\n"
            "control, see the other *_threads parameters:\n"
            "    * repodata_threads - for fetching/loading repodata\n"
            "    * verify_threads - for verifying package contents in transactions\n"
            "    * execute_threads - for carrying out the unlinking and linking steps\n"
        ),
    )
    repodata_threads: int = Field(
        default=0,
        alias="repodata_threads",
        description=(
            "Threads to use when downloading and reading repodata.  When not set,\n"
            "defaults to None, which uses the default ThreadPoolExecutor behavior.\n"
        ),
    )
    fetch_threads: int = Field(
        default=0,
        alias="fetch_threads",
        description=(
            "Threads to use when downloading packages.  When not set,\n"
            "defaults to None, which uses the default ThreadPoolExecutor behavior.\n"
        ),
    )
    verify_threads: int = Field(
        default=0,
        alias="verify_threads",
        description=(
            "Threads to use when performing the transaction verification step.  When not set,\n"
            "defaults to 1.\n"
        ),
    )
    execute_threads: int = Field(
        default=0,
        alias="execute_threads",
        description=(
            "Threads to use when performing the unlink/link transaction.  When not set,\n"
            "defaults to 1.  This step is pretty strongly I/O limited, and you may not\n"
            "see much benefit here.\n"
        ),
    )

    # ------------------------------------------------------------------
    # Safety & Security
    # ------------------------------------------------------------------

    aggressive_update_packages: tuple[str, ...] = Field(
        default=tuple(DEFAULT_AGGRESSIVE_UPDATE_PACKAGES),
        alias="aggressive_update_packages",
        description=(
            "A list of packages that, if installed, are always updated to the latest possible\n"
            "version.\n"
        ),
    )
    safety_checks: SafetyChecks = Field(
        default=SafetyChecks.warn,
        description=(
            "Enforce available safety guarantees during package installation.\n"
            "The value must be one of 'enabled', 'warn', or 'disabled'.\n"
        ),
    )
    extra_safety_checks: bool = Field(
        default=False,
        description=(
            "Spend extra time validating package contents.  Currently, runs sha256 verification\n"
            "on every file within each package during installation.\n"
        ),
    )
    signing_metadata_url_base: str | None = Field(
        default=None,
        alias="signing_metadata_url_base",
        description=(
            "Base URL for obtaining trust metadata updates (i.e., the `*.root.json` and\n"
            "`key_mgr.json` files) used to verify metadata and (eventually) package signatures.\n"
        ),
    )
    path_conflict: PathConflict = Field(
        default=PathConflict.clobber,
        description=(
            "The method by which conda handle's conflicting/overlapping paths during a\n"
            "create, install, or update operation. The value must be one of 'clobber',\n"
            "'warn', or 'prevent'. The '--clobber' command-line flag or clobber\n"
            "configuration parameter overrides path_conflict set to 'prevent'.\n"
        ),
    )
    pinned_packages: tuple[str, ...] = Field(
        default=(),
        description=(
            "A list of package specs to pin for every environment resolution.\n"
            "This parameter is in BETA, and its behavior may change in a future release.\n"
        ),
    )
    disallowed_packages: tuple[str, ...] = Field(
        default=(),
        alias="disallow",
        description=(
            "Package specifications to disallow installing. The default is to allow\n"
            "all packages.\n"
        ),
    )
    rollback_enabled: bool = Field(
        default=True,
        description=(
            "Should any error occur during an unlink/link transaction, revert any disk\n"
            "mutations made to that point in the transaction.\n"
        ),
    )
    track_features: tuple[str, ...] = Field(
        default=(),
        description=(
            "A list of features that are tracked by default. An entry here is similar to\n"
            "adding an entry to the create_default_packages list.\n"
        ),
    )
    use_index_cache: bool = Field(
        default=False,
        description="Use cache of channel index files, even if it has expired.\n",
    )
    separate_format_cache: bool = Field(
        default=False,
        description=(
            "Treat .tar.bz2 files as different from .conda packages when\n"
            "filenames are otherwise similar. This defaults to False, so\n"
            "that your package cache doesn't churn when rolling out the new\n"
            "package format. If you'd rather not assume that a .tar.bz2 and\n"
            ".conda from the same place represent the same content, set this\n"
            "to True.\n"
        ),
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
        description=(
            "The list of directories to search for named environments. When creating a new\n"
            "named environment, the environment will be placed in the first writable\n"
            "location.\n"
        ),
    )
    pkgs_dirs: tuple[str, ...] = Field(
        default=(),
        alias="pkgs_dirs",
        description=(
            "The list of directories where locally-available packages are linked from at\n"
            "install time. Packages not locally available are downloaded and extracted\n"
            "into the first writable directory.\n"
        ),
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
        description=(
            "Additional platform(s)/subdir(s) for export (e.g., linux-64, osx-64, win-64), current\n"  # noqa: E501
            "platform is always included.\n"
        ),
    )

    # ------------------------------------------------------------------
    # Repodata / caching
    # ------------------------------------------------------------------

    local_repodata_ttl: bool | int = Field(
        default=1,
        description=(
            "For a value of False or 0, always fetch remote repodata (HTTP 304 responses\n"
            "respected). For a value of True or 1, respect the HTTP Cache-Control max-age\n"
            "header. Any other positive integer values is the number of seconds to locally\n"
            "cache repodata before checking the remote server for an update.\n"
        ),
    )

    # ------------------------------------------------------------------
    # Remote connection
    # ------------------------------------------------------------------

    ssl_verify: bool | str = Field(
        default=True,
        alias="verify_ssl",
        description=(
            "Conda verifies SSL certificates for HTTPS requests, just like a web\n"
            "browser. By default, SSL verification is enabled, and conda operations will\n"
            "fail if a required url's certificate cannot be verified. Setting ssl_verify to\n"
            "False disables certification verification. The value for ssl_verify can also\n"
            "be (1) a path to a CA bundle file, (2) a path to a directory containing\n"
            "certificates of trusted CA, or (3) 'truststore' to use the\n"
            "operating system certificate store.\n"
        ),
    )
    client_ssl_cert: str | None = Field(
        default=None,
        alias="client_cert",
        description=(
            "A path to a single file containing a private key and certificate (e.g. .pem\n"
            "file). Alternately, use client_ssl_cert_key in conjunction with client_ssl_cert\n"
            "for individual files.\n"
        ),
    )
    client_ssl_cert_key: str | None = Field(
        default=None,
        alias="client_cert_key",
        description="Used in conjunction with client_ssl_cert for a matching key file.\n",
    )
    proxy_servers: dict[str, str | None] = Field(
        default_factory=dict,
        description=(
            "A mapping to enable proxy settings. Keys can be either (1) a scheme://hostname\n"
            "form, which will match any request to the given scheme and exact hostname, or\n"
            "(2) just a scheme, which will match requests to that scheme. Values are are\n"
            "the actual proxy server, and are of the form\n"
            "'scheme://[user:password@]host[:port]'. The optional 'user:password' inclusion\n"
            "enables HTTP Basic Auth with your proxy.\n"
        ),
    )
    remote_connect_timeout_secs: float = Field(
        default=9.15,
        description=(
            "The number seconds conda will wait for your client to establish a connection\n"
            "to a remote url resource.\n"
        ),
    )
    remote_read_timeout_secs: float = Field(
        default=60.0,
        description=(
            "Once conda has connected to a remote resource and sent an HTTP request, the\n"
            "read timeout is the number of seconds conda will wait for the server to send\n"
            "a response.\n"
        ),
    )
    remote_max_retries: int = Field(
        default=3,
        description="The maximum number of retries each HTTP connection should attempt.\n",
    )
    remote_backoff_factor: int = Field(
        default=1,
        description="The factor determines the time HTTP connection should wait for attempt.\n",
    )
    add_anaconda_token: bool = Field(
        default=True,
        alias="add_binstar_token",
        description=(
            "In conjunction with the anaconda command-line client (installed with\n"
            "`conda install anaconda-client`), and following logging into an Anaconda\n"
            "Server API site using `anaconda login`, automatically apply a matching\n"
            "private token to enable access to private packages and channels.\n"
        ),
    )

    # ------------------------------------------------------------------
    # Channel configuration
    # ------------------------------------------------------------------

    allow_non_channel_urls: bool = Field(
        default=False,
        description=(
            "Warn, but do not fail, when conda detects a channel url is not a valid channel.\n"
        ),
    )
    channel_alias: str = Field(
        default=DEFAULT_CHANNEL_ALIAS,
        alias="channel_alias",
        description="The prepended url location to associate with channel names.\n",
    )
    channel_priority: ChannelPriority = Field(
        default=ChannelPriority.FLEXIBLE,
        description=(
            "Accepts values of 'strict', 'flexible', and 'disabled'. The default value\n"
            "is 'flexible'. With strict channel priority, packages in lower priority channels\n"
            "are not considered if a package with the same name appears in a higher\n"
            "priority channel. With flexible channel priority, the solver may reach into\n"
            "lower priority channels to fulfill dependencies, rather than raising an\n"
            "unsatisfiable error. With channel priority disabled, package version takes\n"
            "precedence, and the configured priority of channels is used only to break ties.\n"
            "In previous versions of conda, this parameter was configured as either True or\n"
            "False. True is now an alias to 'flexible'.\n"
        ),
    )
    channels: tuple[str, ...] = Field(
        default=(),
        alias="channel",
        description="The list of conda channels to include for relevant operations.\n",
    )
    channel_settings: tuple[dict[str, str], ...] = Field(
        default=(),
        description=(
            "A list of mappings that allows overriding certain settings for a single channel.\n"
            'Each list item should include at least the "channel" key and the setting you would\n'
            "like to override.\n"
        ),
    )
    custom_channels: dict[str, str] = Field(
        default_factory=lambda: dict(DEFAULT_CUSTOM_CHANNELS),
        alias="custom_channels",
        description=(
            "A map of key-value pairs where the key is a channel name and the value is\n"
            "a channel location. Channels defined here override the default\n"
            "'channel_alias' value. The channel name (key) is not included in the channel\n"
            "location (value).  For example, to override the location of the 'conda-forge'\n"
            "channel where the url to repodata is\n"
            "https://anaconda-repo.dev/packages/conda-forge/linux-64/repodata.json, add an\n"
            "entry 'conda-forge: https://anaconda-repo.dev/packages'.\n"
        ),
    )
    custom_multichannels: dict[str, list[str]] = Field(
        default_factory=dict,
        alias="custom_multichannels",
        description=(
            "A multichannel is a metachannel composed of multiple channels. The only reserved\n"
            "multichannel is 'local', which is a list of file:// channel locations where\n"
            "conda-build stashes successfully-built packages and cannot be overridden.\n"
            "Other multichannels, including 'defaults', can be defined or customized with\n"
            "custom_multichannels, where the key is the multichannel name and the value is\n"
            "a list of channel names and/or channel urls. The 'defaults' multichannel can\n"
            "also be customized using the 'default_channels' parameter (a historical setting\n"
            "from when 'defaults' was reserved). If both are defined,\n"
            "'custom_multichannels.defaults' takes precedence.\n"
        ),
    )
    default_channels: tuple[str, ...] = Field(
        default=tuple(DEFAULT_CHANNELS),
        alias="default_channels",
        description=(
            "The list of channel names and/or urls used for the 'defaults' multichannel.\n"
            "Can be overridden by 'custom_multichannels.defaults'.\n"
        ),
    )
    migrated_channel_aliases: tuple[str, ...] = Field(
        default=(),
        alias="migrated_channel_aliases",
        description=(
            "A list of previously-used channel_alias values. Useful when switching between\n"
            "different Anaconda Repository instances.\n"
        ),
    )
    migrated_custom_channels: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "A map of key-value pairs where the key is a channel name and the value is\n"
            "the previous location of the channel.\n"
        ),
    )
    override_channels_enabled: bool = Field(
        default=True,
        description="Permit use of the --override-channels command-line flag.\n",
    )
    show_channel_urls: bool | None = Field(
        default=None,
        description="Show channel URLs when displaying what is going to be downloaded.\n",
    )
    use_local: bool = Field(
        default=False,
        description="Include the local channel (~/conda-bld) automatically.",
    )
    allowlist_channels: tuple[str, ...] = Field(
        default=(),
        alias="whitelist_channels",
        description=(
            "The exclusive list of channels allowed to be used on the system. Use of any\n"
            "other channels will result in an error. If conda-build channels are to be\n"
            "allowed, along with the --use-local command line flag, be sure to include the\n"
            "'local' channel in the list. If the list is empty or left undefined, no\n"
            "channel exclusions will be enforced.\n"
        ),
    )
    denylist_channels: tuple[str, ...] = Field(
        default=(),
        description=(
            "The list of channels that are denied to be used on the system. Use of any\n"
            "of these channels will result in an error. If conda-build channels are to be\n"
            "allowed, along with the --use-local command line flag, be sure to not include\n"
            "the 'local' channel in the list. If the list is empty or left undefined, no\n"
            "channel exclusions will be enforced.\n"
        ),
    )
    repodata_fns: tuple[str, ...] = Field(
        default=("current_repodata.json", REPODATA_FN),
        description=(
            "Specify filenames for repodata fetching. The default is ('current_repodata.json',\n"
            "'repodata.json'), which tries a subset of the full index containing only the\n"
            "latest version for each package, then falls back to repodata.json.  You may\n"
            "want to specify something else to use an alternate index that has been reduced\n"
            "somehow.\n"
        ),
    )
    use_only_tar_bz2: bool | None = Field(
        default=None,
        alias="use_only_tar_bz2",
        description=(
            "A boolean indicating that only .tar.bz2 conda packages should be downloaded.\n"
            "This is forced to True if conda-build is installed and older than 3.18.3,\n"
            "because older versions of conda break when conda feeds it the new file format.\n"
        ),
    )

    # ------------------------------------------------------------------
    # Installation behaviour
    # ------------------------------------------------------------------

    always_softlink: bool = Field(
        default=False,
        alias="softlink",
        description=(
            "Register a preference that files be soft-linked (symlinked) into a prefix during\n"
            "install rather than hard-linked. The link source is the 'pkgs_dir' package cache\n"
            "from where the package is being linked. WARNING: Using this option can result in\n"
            "corruption of long-lived conda environments. Package caches are *caches*, which\n"
            "means there is some churn and invalidation. With this option, the contents of\n"
            "environments can be switched out (or erased) via operations on other environments.\n"
        ),
    )
    always_copy: bool = Field(
        default=False,
        alias="copy",
        description=(
            "Register a preference that files be copied into a prefix during install rather\n"
            "than hard-linked.\n"
        ),
    )
    always_yes: bool | None = Field(
        default=None,
        alias="yes",
        description=(
            "Automatically choose the 'yes' option whenever asked to proceed with a conda\n"
            "operation, such as when running `conda install`.\n"
        ),
    )

    # ------------------------------------------------------------------
    # Output / UX
    # ------------------------------------------------------------------

    verbosity: int = Field(
        default=0,
        alias="verbose",
        description="Sets output log level. 0 is warn. 1 is info. 2 is debug. 3 is trace.\n",
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
        description="Ensure all output written to stdout is structured json.\n",
    )
    console: str = Field(
        default=DEFAULT_CONSOLE_REPORTER_BACKEND,
        alias="console",
        description=(
            "Configure different backends to be used while rendering normal console output.\n"
            'Defaults to "classic".\n'
        ),
    )
    list_fields: tuple[str, ...] = Field(
        default=tuple(DEFAULT_CONDA_LIST_FIELDS),
        description="Default fields to report as columns in the output of `conda list`.\n",
    )
    offline: bool = Field(
        default=False,
        description="Restrict conda to cached download content and file:// based urls.\n",
    )
    quiet: bool = Field(
        default=False,
        description="Disable progress bar display and other output.\n",
    )
    ignore_pinned: bool = Field(
        default=False,
        description="Ignore pinned package constraints.",
    )
    report_errors: bool | None = Field(
        default=None,
        alias="report_errors",
        description=(
            "Opt in, or opt out, of automatic error reporting to core maintainers. Error\n"
            "reports are anonymous, with only the error stack trace and information given\n"
            "by `conda info` being sent.\n"
        ),
    )
    shortcuts: bool = Field(
        default=True,
        description=(
            "Allow packages to create OS-specific shortcuts (e.g. in the Windows Start\n"
            "Menu) at install time.\n"
        ),
    )
    number_channel_notices: int = Field(
        default=5,
        description=(
            "Sets the number of channel notices to be displayed when running commands\n"
            'the "install", "create", "update", "env create", and "env update" . Defaults\n'
            "to 5. In order to completely suppress channel notices, set this to 0.\n"
        ),
    )
    shortcuts_only: tuple[str, ...] = Field(
        default=(),
        description="Create shortcuts only for the specified package names.\n",
    )
    experimental: tuple[str, ...] = Field(
        default=(),
        description="List of experimental features to enable.\n",
    )
    preview: tuple[str, ...] = Field(
        default=(),
        description="List of preview features to opt into.\n",
    )
    no_lock: bool = Field(
        default=False,
        description="Disable index cache lock (defaults to enabled).\n",
    )
    repodata_use_zst: bool = Field(
        default=True,
        description="Use `repodata.json.zst` if available.\n",
    )
    repodata_use_shards: bool = Field(
        default=True,
        description="Use sharded repodata if available.\n",
    )
    envvars_force_uppercase: bool = Field(
        default=True,
        description="Force uppercase for new environment variable names. Defaults to True.\n",
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
        description=(
            "A string to choose between the different solver logics implemented in\n"
            "conda. A solver logic takes care of turning your requested packages into a\n"
            "list of specs to add and/or remove from a given environment, based on their\n"
            "dependencies and specified constraints.\n"
        ),
    )
    force_remove: bool = Field(
        default=False,
        description="Force removal of packages even if it would break dependencies.",
    )
    force_reinstall: bool = Field(
        default=False,
        description=(
            "Ensure that any user-requested package for the current operation is uninstalled\n"
            "and reinstalled, even if that package already exists in the environment.\n"
        ),
    )
    target_prefix_override: str = Field(
        default="",
        description="Override the target prefix for operations.",
    )
    unsatisfiable_hints: bool = Field(
        default=True,
        description=(
            "A boolean to determine if conda should find conflicting packages in the case\n"
            "of a failed install.\n"
        ),
    )
    unsatisfiable_hints_check_depth: int = Field(
        default=2,
        description=(
            "An integer that specifies how many levels deep to search for unsatisfiable\n"
            "dependencies. If this number is 1 it will complete the unsatisfiable hints\n"
            "fastest (but perhaps not the most complete). The higher this number, the\n"
            "longer the generation of the unsat hint will take. Defaults to 3.\n"
        ),
    )

    # ------------------------------------------------------------------
    # conda-build
    # ------------------------------------------------------------------

    bld_path: str = Field(
        default="",
        description=(
            "The location where conda-build will put built packages. Same as 'croot', but\n"
            "'croot' takes precedence when both are defined. Also used in construction of the\n"
            "'local' multichannel.\n"
        ),
    )
    anaconda_upload: bool | None = Field(
        default=None,
        alias="binstar_upload",
        description="Automatically upload packages built with conda build to anaconda.org.\n",
    )
    croot: str = Field(
        default="",
        alias="croot",
        description=(
            "The location where conda-build will put built packages. Same as 'bld_path', but\n"
            "'croot' takes precedence when both are defined. Also used in construction of the\n"
            "'local' multichannel.\n"
        ),
    )
    conda_build: dict[str, str] = Field(
        default_factory=dict,
        alias="conda-build",
        description="General configuration parameters for conda-build.\n",
    )

    # ------------------------------------------------------------------
    # Virtual packages
    # ------------------------------------------------------------------

    override_virtual_packages: dict[str, str | None] = Field(
        default_factory=dict,
        alias="virtual_packages",
        description="Set override values for virtual packages.\n",
    )

    # ------------------------------------------------------------------
    # Plugin configuration
    # ------------------------------------------------------------------

    no_plugins: bool = Field(
        default=bool(NO_PLUGINS),
        description="Disable all currently-registered plugins, except built-in conda plugins.\n",
    )

    # ------------------------------------------------------------------
    # Backend selection
    # ------------------------------------------------------------------

    conda_context_backend: str = Field(
        default="pydantic",
        description=(
            "Validation backend to use for conda-context configuration loading.\n"
            "Valid values are 'pydantic' (default) and 'msgspec'.\n"
            "Can be set in .condarc or via CONTEXT_BACKEND environment variable.\n"
        ),
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
