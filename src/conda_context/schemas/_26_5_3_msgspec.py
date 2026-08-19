"""
CondaConfigMsgspec — msgspec.Struct for conda 26.5.3 configuration.

Feature-complete equivalent of CondaConfig (Pydantic), using msgspec for
maximum construction performance.

Key differences from the Pydantic schema:
- No field(name=...) aliases. Use normalize_alias_keys() before msgspec.convert().
- Validators implemented in __post_init__ (runs after C-level construction).
- Descriptions stored separately in _FIELD_DESCRIPTIONS (no Field metadata).
- Enum fields store enum instances (not values); ValueEnum.__str__ returns .value
  so str() on them is identical to the Pydantic use_enum_values=True behaviour.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import msgspec
import msgspec.structs

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

# ---------------------------------------------------------------------------
# Alias → canonical name map (23 entries)
# Used by normalize_alias_keys() in _schema_backend.py
# ---------------------------------------------------------------------------

_ALIAS_TO_CANONICAL: dict[str, str] = {
    "self_update": "auto_update_conda",
    "auto_activate_base": "auto_activate",
    "env_spec": "environment_specifier",
    "pip_interop_enabled": "prefix_data_interoperability",
    "disallow": "disallowed_packages",
    "root_dir": "root_prefix",
    "envs_path": "envs_dirs",
    "extra_platforms": "export_platforms",
    "verify_ssl": "ssl_verify",
    "client_cert": "client_ssl_cert",
    "client_cert_key": "client_ssl_cert_key",
    "add_binstar_token": "add_anaconda_token",
    "channel": "channels",
    "whitelist_channels": "allowlist_channels",
    "softlink": "always_softlink",
    "copy": "always_copy",
    "yes": "always_yes",
    "verbose": "verbosity",
    "json": "json_output",
    "experimental_solver": "solver",
    "binstar_upload": "anaconda_upload",
    "conda-build": "conda_build",
    "virtual_packages": "override_virtual_packages",
}


# ---------------------------------------------------------------------------
# Field descriptions (verbatim from CondaConfig Field(description=...))
# ---------------------------------------------------------------------------

_FIELD_DESCRIPTIONS: dict[str, str] = {
    "add_pip_as_python_dependency": "Automatically add pip, wheel and setuptools as Python dependencies.",
    "allow_conda_downgrades": "Allow conda itself to be downgraded.",
    "allow_cycles": "Allow cyclic dependencies in the solver.",
    "allow_softlinks": (
        "When allow_softlinks is True, conda uses hard-links when possible, and soft-links\n"
        "(symlinks) when hard-links are not possible, such as when installing on a\n"
        "different filesystem than the one that the package cache is on. When\n"
        "allow_softlinks is False, conda still uses hard-links when possible, but when it\n"
        "is not possible, conda copies files. Individual packages can override\n"
        "this setting, specifying that certain files should never be soft-linked (see the\n"
        "no_link option in the build recipe documentation).\n"
    ),
    "auto_update_conda": "Automatically update conda when a newer or higher priority version is detected.\n",
    "auto_activate": (
        "Automatically activate the environment given at 'default_activation_env'\n"
        "during shell initialization.\n"
    ),
    "default_activation_env": (
        "The environment to be automatically activated on startup if 'auto_activate'\n"
        "is True. Also sets the default environment to activate when 'conda activate'\n"
        "receives no arguments.\n"
    ),
    "auto_stack": (
        "Implicitly use --stack when using activate if current level of nesting\n"
        "(as indicated by CONDA_SHLVL environment variable) is less than or equal to\n"
        "specified value. 0 or false disables automatic stacking, 1 or true enables\n"
        "it for one level.\n"
    ),
    "notify_outdated_conda": (
        "Notify if a newer version of conda is detected during a create, install, update,\n"
        "or remove operation.\n"
    ),
    "clobber": "Allow clobbering of overlapping file paths within packages.",
    "changeps1": (
        "When using activate, change the command prompt ($PS1) to include the\n"
        "activated environment.\n"
    ),
    "env_prompt": (
        "Template for prompt modification based on the active environment. Currently\n"
        "supported template variables are '{prefix}', '{name}', and '{default_env}'.\n"
        "'{prefix}' is the absolute path to the active environment. '{name}' is the\n"
        "basename of the active environment prefix. '{default_env}' holds the value\n"
        "of '{name}' if the active environment is a conda named environment ('-n'\n"
        "flag), or otherwise holds the value of '{prefix}'. Templating uses python's\n"
        "str.format() method.\n"
    ),
    "environment_specifier": (
        "**EXPERIMENTAL** While experimental, expect both major and minor changes across minor releases.\n"
        "\n"
        "The name of the environment specifier plugin that should be used for this context.\n"
        "If not specified, the plugin manager will try to detect the plugin to use.\n"
    ),
    "create_default_packages": "Packages that are by default added to a newly created environments.\n",
    "register_envs": "Register newly created environments in ~/.conda/environments.txt.",
    "protect_frozen_envs": "Prevent modification of frozen (base) environments.",
    "default_python": "Default Python version to use when creating new environments.",
    "download_only": (
        "Solve an environment and ensure package caches are populated, but exit\n"
        "prior to unlinking and linking packages into the prefix\n"
    ),
    "enable_private_envs": "Enable private environments.",
    "force_32bit": "Force conda to use 32-bit packages on 64-bit systems.",
    "non_admin_enabled": (
        "Allows completion of conda's create, install, update, and remove operations, for\n"
        "non-privileged (non-root or non-administrator) users.\n"
    ),
    "prefix_data_interoperability": "Enable plugins to allow conda to interact with non-conda-installed packages.\n",
    "default_threads": (
        "Threads to use by default for parallel operations.  Default is None,\n"
        "which allows operations to choose themselves.  For more specific\n"
        "control, see the other *_threads parameters:\n"
        "    * repodata_threads - for fetching/loading repodata\n"
        "    * verify_threads - for verifying package contents in transactions\n"
        "    * execute_threads - for carrying out the unlinking and linking steps\n"
    ),
    "repodata_threads": (
        "Threads to use when downloading and reading repodata.  When not set,\n"
        "defaults to None, which uses the default ThreadPoolExecutor behavior.\n"
    ),
    "fetch_threads": (
        "Threads to use when downloading packages.  When not set,\n"
        "defaults to None, which uses the default ThreadPoolExecutor behavior.\n"
    ),
    "verify_threads": (
        "Threads to use when performing the transaction verification step.  When not set,\n"
        "defaults to 1.\n"
    ),
    "execute_threads": (
        "Threads to use when performing the unlink/link transaction.  When not set,\n"
        "defaults to 1.  This step is pretty strongly I/O limited, and you may not\n"
        "see much benefit here.\n"
    ),
    "aggressive_update_packages": (
        "A list of packages that, if installed, are always updated to the latest possible\n"
        "version.\n"
    ),
    "safety_checks": (
        "Enforce available safety guarantees during package installation.\n"
        "The value must be one of 'enabled', 'warn', or 'disabled'.\n"
    ),
    "extra_safety_checks": (
        "Spend extra time validating package contents.  Currently, runs sha256 verification\n"
        "on every file within each package during installation.\n"
    ),
    "signing_metadata_url_base": (
        "Base URL for obtaining trust metadata updates (i.e., the `*.root.json` and\n"
        "`key_mgr.json` files) used to verify metadata and (eventually) package signatures.\n"
    ),
    "path_conflict": (
        "The method by which conda handle's conflicting/overlapping paths during a\n"
        "create, install, or update operation. The value must be one of 'clobber',\n"
        "'warn', or 'prevent'. The '--clobber' command-line flag or clobber\n"
        "configuration parameter overrides path_conflict set to 'prevent'.\n"
    ),
    "pinned_packages": (
        "A list of package specs to pin for every environment resolution.\n"
        "This parameter is in BETA, and its behavior may change in a future release.\n"
    ),
    "disallowed_packages": (
        "Package specifications to disallow installing. The default is to allow\n"
        "all packages.\n"
    ),
    "rollback_enabled": (
        "Should any error occur during an unlink/link transaction, revert any disk\n"
        "mutations made to that point in the transaction.\n"
    ),
    "track_features": (
        "A list of features that are tracked by default. An entry here is similar to\n"
        "adding an entry to the create_default_packages list.\n"
    ),
    "use_index_cache": "Use cache of channel index files, even if it has expired.\n",
    "separate_format_cache": (
        "Treat .tar.bz2 files as different from .conda packages when\n"
        "filenames are otherwise similar. This defaults to False, so\n"
        "that your package cache doesn't churn when rolling out the new\n"
        "package format. If you'd rather not assume that a .tar.bz2 and\n"
        ".conda from the same place represent the same content, set this\n"
        "to True.\n"
    ),
    "root_prefix": "Path to the root conda prefix (base environment).",
    "envs_dirs": (
        "The list of directories to search for named environments. When creating a new\n"
        "named environment, the environment will be placed in the first writable\n"
        "location.\n"
    ),
    "pkgs_dirs": (
        "The list of directories where locally-available packages are linked from at\n"
        "install time. Packages not locally available are downloaded and extracted\n"
        "into the first writable directory.\n"
    ),
    "subdir": "Platform subdirectory (e.g., linux-64). Empty = auto-detect.",
    "subdirs": "List of platform subdirectories to include in solves.",
    "export_platforms": (
        "Additional platform(s)/subdir(s) for export (e.g., linux-64, osx-64, win-64), current\n"
        "platform is always included.\n"
    ),
    "local_repodata_ttl": (
        "For a value of False or 0, always fetch remote repodata (HTTP 304 responses\n"
        "respected). For a value of True or 1, respect the HTTP Cache-Control max-age\n"
        "header. Any other positive integer values is the number of seconds to locally\n"
        "cache repodata before checking the remote server for an update.\n"
    ),
    "ssl_verify": (
        "Conda verifies SSL certificates for HTTPS requests, just like a web\n"
        "browser. By default, SSL verification is enabled, and conda operations will\n"
        "fail if a required url's certificate cannot be verified. Setting ssl_verify to\n"
        "False disables certification verification. The value for ssl_verify can also\n"
        "be (1) a path to a CA bundle file, (2) a path to a directory containing\n"
        "certificates of trusted CA, or (3) 'truststore' to use the\n"
        "operating system certificate store.\n"
    ),
    "client_ssl_cert": (
        "A path to a single file containing a private key and certificate (e.g. .pem\n"
        "file). Alternately, use client_ssl_cert_key in conjunction with client_ssl_cert\n"
        "for individual files.\n"
    ),
    "client_ssl_cert_key": "Used in conjunction with client_ssl_cert for a matching key file.\n",
    "proxy_servers": (
        "A mapping to enable proxy settings. Keys can be either (1) a scheme://hostname\n"
        "form, which will match any request to the given scheme and exact hostname, or\n"
        "(2) just a scheme, which will match requests to that scheme. Values are are\n"
        "the actual proxy server, and are of the form\n"
        "'scheme://[user:password@]host[:port]'. The optional 'user:password' inclusion\n"
        "enables HTTP Basic Auth with your proxy.\n"
    ),
    "remote_connect_timeout_secs": (
        "The number seconds conda will wait for your client to establish a connection\n"
        "to a remote url resource.\n"
    ),
    "remote_read_timeout_secs": (
        "Once conda has connected to a remote resource and sent an HTTP request, the\n"
        "read timeout is the number of seconds conda will wait for the server to send\n"
        "a response.\n"
    ),
    "remote_max_retries": "The maximum number of retries each HTTP connection should attempt.\n",
    "remote_backoff_factor": "The factor determines the time HTTP connection should wait for attempt.\n",
    "add_anaconda_token": (
        "In conjunction with the anaconda command-line client (installed with\n"
        "`conda install anaconda-client`), and following logging into an Anaconda\n"
        "Server API site using `anaconda login`, automatically apply a matching\n"
        "private token to enable access to private packages and channels.\n"
    ),
    "allow_non_channel_urls": "Warn, but do not fail, when conda detects a channel url is not a valid channel.\n",
    "channel_alias": "The prepended url location to associate with channel names.\n",
    "channel_priority": (
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
    "channels": "The list of conda channels to include for relevant operations.\n",
    "channel_settings": (
        "A list of mappings that allows overriding certain settings for a single channel.\n"
        'Each list item should include at least the "channel" key and the setting you would\n'
        "like to override.\n"
    ),
    "custom_channels": (
        "A map of key-value pairs where the key is a channel name and the value is\n"
        "a channel location. Channels defined here override the default\n"
        "'channel_alias' value. The channel name (key) is not included in the channel\n"
        "location (value).  For example, to override the location of the 'conda-forge'\n"
        "channel where the url to repodata is\n"
        "https://anaconda-repo.dev/packages/conda-forge/linux-64/repodata.json, add an\n"
        "entry 'conda-forge: https://anaconda-repo.dev/packages'.\n"
    ),
    "custom_multichannels": (
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
    "default_channels": (
        "The list of channel names and/or urls used for the 'defaults' multichannel.\n"
        "Can be overridden by 'custom_multichannels.defaults'.\n"
    ),
    "migrated_channel_aliases": (
        "A list of previously-used channel_alias values. Useful when switching between\n"
        "different Anaconda Repository instances.\n"
    ),
    "migrated_custom_channels": (
        "A map of key-value pairs where the key is a channel name and the value is\n"
        "the previous location of the channel.\n"
    ),
    "override_channels_enabled": "Permit use of the --override-channels command-line flag.\n",
    "show_channel_urls": "Show channel URLs when displaying what is going to be downloaded.\n",
    "use_local": "Include the local channel (~/conda-bld) automatically.",
    "allowlist_channels": (
        "The exclusive list of channels allowed to be used on the system. Use of any\n"
        "other channels will result in an error. If conda-build channels are to be\n"
        "allowed, along with the --use-local command line flag, be sure to include the\n"
        "'local' channel in the list. If the list is empty or left undefined, no\n"
        "channel exclusions will be enforced.\n"
    ),
    "denylist_channels": (
        "The list of channels that are denied to be used on the system. Use of any\n"
        "of these channels will result in an error. If conda-build channels are to be\n"
        "allowed, along with the --use-local command line flag, be sure to not include\n"
        "the 'local' channel in the list. If the list is empty or left undefined, no\n"
        "channel exclusions will be enforced.\n"
    ),
    "repodata_fns": (
        "Specify filenames for repodata fetching. The default is ('current_repodata.json',\n"
        "'repodata.json'), which tries a subset of the full index containing only the\n"
        "latest version for each package, then falls back to repodata.json.  You may\n"
        "want to specify something else to use an alternate index that has been reduced\n"
        "somehow.\n"
    ),
    "use_only_tar_bz2": (
        "A boolean indicating that only .tar.bz2 conda packages should be downloaded.\n"
        "This is forced to True if conda-build is installed and older than 3.18.3,\n"
        "because older versions of conda break when conda feeds it the new file format.\n"
    ),
    "always_softlink": (
        "Register a preference that files be soft-linked (symlinked) into a prefix during\n"
        "install rather than hard-linked. The link source is the 'pkgs_dir' package cache\n"
        "from where the package is being linked. WARNING: Using this option can result in\n"
        "corruption of long-lived conda environments. Package caches are *caches*, which\n"
        "means there is some churn and invalidation. With this option, the contents of\n"
        "environments can be switched out (or erased) via operations on other environments.\n"
    ),
    "always_copy": (
        "Register a preference that files be copied into a prefix during install rather\n"
        "than hard-linked.\n"
    ),
    "always_yes": (
        "Automatically choose the 'yes' option whenever asked to proceed with a conda\n"
        "operation, such as when running `conda install`.\n"
    ),
    "verbosity": "Sets output log level. 0 is warn. 1 is info. 2 is debug. 3 is trace.\n",
    "debug": "Enable debug logging.",
    "trace": "Enable trace logging (more verbose than debug).",
    "dev": "Enable development mode.",
    "dry_run": "Only show what would be done without making changes.",
    "error_upload_url": "URL for uploading unexpected error reports.",
    "force": "Force operations even when unsafe.",
    "json_output": "Ensure all output written to stdout is structured json.\n",
    "console": (
        "Configure different backends to be used while rendering normal console output.\n"
        'Defaults to "classic".\n'
    ),
    "list_fields": "Default fields to report as columns in the output of `conda list`.\n",
    "offline": "Restrict conda to cached download content and file:// based urls.\n",
    "quiet": "Disable progress bar display and other output.\n",
    "ignore_pinned": "Ignore pinned package constraints.",
    "report_errors": (
        "Opt in, or opt out, of automatic error reporting to core maintainers. Error\n"
        "reports are anonymous, with only the error stack trace and information given\n"
        "by `conda info` being sent.\n"
    ),
    "shortcuts": (
        "Allow packages to create OS-specific shortcuts (e.g. in the Windows Start\n"
        "Menu) at install time.\n"
    ),
    "number_channel_notices": (
        "Sets the number of channel notices to be displayed when running commands\n"
        'the "install", "create", "update", "env create", and "env update" . Defaults\n'
        "to 5. In order to completely suppress channel notices, set this to 0.\n"
    ),
    "shortcuts_only": "Create shortcuts only for the specified package names.\n",
    "experimental": "List of experimental features to enable.\n",
    "preview": "List of preview features to opt into.\n",
    "no_lock": "Disable index cache lock (defaults to enabled).\n",
    "repodata_use_zst": "Use `repodata.json.zst` if available.\n",
    "repodata_use_shards": "Use sharded repodata if available.\n",
    "envvars_force_uppercase": "Force uppercase for new environment variable names. Defaults to True.\n",
    "deps_modifier": "Modifier for dependency resolution behaviour.",
    "update_modifier": "How to handle updates during install/update operations.",
    "sat_solver": "SAT solver backend to use (classic solver only).",
    "solver_ignore_timestamps": "Ignore package timestamps when solving.",
    "solver": (
        "A string to choose between the different solver logics implemented in\n"
        "conda. A solver logic takes care of turning your requested packages into a\n"
        "list of specs to add and/or remove from a given environment, based on their\n"
        "dependencies and specified constraints.\n"
    ),
    "force_remove": "Force removal of packages even if it would break dependencies.",
    "force_reinstall": (
        "Ensure that any user-requested package for the current operation is uninstalled\n"
        "and reinstalled, even if that package already exists in the environment.\n"
    ),
    "target_prefix_override": "Override the target prefix for operations.",
    "unsatisfiable_hints": (
        "A boolean to determine if conda should find conflicting packages in the case\n"
        "of a failed install.\n"
    ),
    "unsatisfiable_hints_check_depth": (
        "An integer that specifies how many levels deep to search for unsatisfiable\n"
        "dependencies. If this number is 1 it will complete the unsatisfiable hints\n"
        "fastest (but perhaps not the most complete). The higher this number, the\n"
        "longer the generation of the unsat hint will take. Defaults to 3.\n"
    ),
    "bld_path": (
        "The location where conda-build will put built packages. Same as 'croot', but\n"
        "'croot' takes precedence when both are defined. Also used in construction of the\n"
        "'local' multichannel.\n"
    ),
    "anaconda_upload": "Automatically upload packages built with conda build to anaconda.org.\n",
    "croot": (
        "The location where conda-build will put built packages. Same as 'bld_path', but\n"
        "'croot' takes precedence when both are defined. Also used in construction of the\n"
        "'local' multichannel.\n"
    ),
    "conda_build": "General configuration parameters for conda-build.\n",
    "override_virtual_packages": "Set override values for virtual packages.\n",
    "no_plugins": "Disable all currently-registered plugins, except built-in conda plugins.\n",
    "conda_context_backend": (
        "Validation backend to use for conda-context configuration loading.\n"
        "Valid values are 'pydantic' (default) and 'msgspec'.\n"
        "Can be set in .condarc or via CONTEXT_BACKEND environment variable.\n"
    ),
}


# ---------------------------------------------------------------------------
# Default factory helpers (match Pydantic schema exactly)
# ---------------------------------------------------------------------------

def _default_python_default() -> str:
    ver = sys.version_info
    return f"{ver.major}.{ver.minor}"


# ---------------------------------------------------------------------------
# CondaConfigMsgspec
# ---------------------------------------------------------------------------


class CondaConfigMsgspec(msgspec.Struct, forbid_unknown_fields=False):
    """msgspec.Struct for conda 26.5.3 configuration fields.

    Field names are canonical Python attribute names (no aliases).
    Use normalize_alias_keys() from _schema_backend before calling
    msgspec.convert() if the input dict may contain legacy alias keys.
    """

    # ------------------------------------------------------------------
    # General behaviour
    # ------------------------------------------------------------------

    add_pip_as_python_dependency: bool = True
    allow_conda_downgrades: bool = False
    allow_cycles: bool = True
    allow_softlinks: bool = False
    auto_update_conda: bool = True
    auto_activate: bool = True
    default_activation_env: str = ROOT_ENV_NAME
    auto_stack: int = 0
    notify_outdated_conda: bool = True
    clobber: bool = False
    changeps1: bool = True
    env_prompt: str = "({default_env}) "
    environment_specifier: str | None = None
    create_default_packages: tuple[str, ...] = ()
    register_envs: bool = True
    protect_frozen_envs: bool = True
    default_python: str | None = msgspec.field(default_factory=_default_python_default)
    download_only: bool = False
    enable_private_envs: bool = False
    force_32bit: bool = False
    non_admin_enabled: bool = True
    prefix_data_interoperability: bool = False

    # ------------------------------------------------------------------
    # Threading
    # ------------------------------------------------------------------

    default_threads: int = 0
    repodata_threads: int = 0
    fetch_threads: int = 0
    verify_threads: int = 0
    execute_threads: int = 0

    # ------------------------------------------------------------------
    # Safety & Security
    # ------------------------------------------------------------------

    aggressive_update_packages: tuple[str, ...] = msgspec.field(
        default_factory=lambda: tuple(DEFAULT_AGGRESSIVE_UPDATE_PACKAGES)
    )
    safety_checks: SafetyChecks = SafetyChecks.warn
    extra_safety_checks: bool = False
    signing_metadata_url_base: str | None = None
    path_conflict: PathConflict = PathConflict.clobber
    pinned_packages: tuple[str, ...] = ()
    disallowed_packages: tuple[str, ...] = ()
    rollback_enabled: bool = True
    track_features: tuple[str, ...] = ()
    use_index_cache: bool = False
    separate_format_cache: bool = False

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    root_prefix: str = ""
    envs_dirs: tuple[str, ...] = ()
    pkgs_dirs: tuple[str, ...] = ()
    subdir: str = ""
    subdirs: tuple[str, ...] = ()
    export_platforms: tuple[str, ...] = ()

    # ------------------------------------------------------------------
    # Repodata / caching
    # ------------------------------------------------------------------

    local_repodata_ttl: bool | int = 1

    # ------------------------------------------------------------------
    # Remote connection
    # ------------------------------------------------------------------

    ssl_verify: bool | str = True
    client_ssl_cert: str | None = None
    client_ssl_cert_key: str | None = None
    proxy_servers: dict[str, str | None] = msgspec.field(default_factory=dict)
    remote_connect_timeout_secs: float = 9.15
    remote_read_timeout_secs: float = 60.0
    remote_max_retries: int = 3
    remote_backoff_factor: int = 1
    add_anaconda_token: bool = True

    # ------------------------------------------------------------------
    # Channel configuration
    # ------------------------------------------------------------------

    allow_non_channel_urls: bool = False
    channel_alias: str = DEFAULT_CHANNEL_ALIAS
    channel_priority: ChannelPriority = ChannelPriority.FLEXIBLE
    channels: tuple[str, ...] = ()
    channel_settings: tuple[dict[str, str], ...] = ()
    custom_channels: dict[str, str] = msgspec.field(
        default_factory=lambda: dict(DEFAULT_CUSTOM_CHANNELS)
    )
    custom_multichannels: dict[str, list[str]] = msgspec.field(default_factory=dict)
    default_channels: tuple[str, ...] = msgspec.field(
        default_factory=lambda: tuple(DEFAULT_CHANNELS)
    )
    migrated_channel_aliases: tuple[str, ...] = ()
    migrated_custom_channels: dict[str, str] = msgspec.field(default_factory=dict)
    override_channels_enabled: bool = True
    show_channel_urls: bool | None = None
    use_local: bool = False
    allowlist_channels: tuple[str, ...] = ()
    denylist_channels: tuple[str, ...] = ()
    repodata_fns: tuple[str, ...] = msgspec.field(
        default_factory=lambda: ("current_repodata.json", REPODATA_FN)
    )
    use_only_tar_bz2: bool | None = None

    # ------------------------------------------------------------------
    # Installation behaviour
    # ------------------------------------------------------------------

    always_softlink: bool = False
    always_copy: bool = False
    always_yes: bool | None = None

    # ------------------------------------------------------------------
    # Output / UX
    # ------------------------------------------------------------------

    verbosity: int = 0
    debug: bool = False
    trace: bool = False
    dev: bool = False
    dry_run: bool = False
    error_upload_url: str = "https://conda.io/conda-post/unexpected-error"
    force: bool = False
    json_output: bool = False
    console: str = DEFAULT_CONSOLE_REPORTER_BACKEND
    list_fields: tuple[str, ...] = msgspec.field(
        default_factory=lambda: tuple(DEFAULT_CONDA_LIST_FIELDS)
    )
    offline: bool = False
    quiet: bool = False
    ignore_pinned: bool = False
    report_errors: bool | None = None
    shortcuts: bool = True
    number_channel_notices: int = 5
    shortcuts_only: tuple[str, ...] = ()
    experimental: tuple[str, ...] = ()
    preview: tuple[str, ...] = ()
    no_lock: bool = False
    repodata_use_zst: bool = True
    repodata_use_shards: bool = True
    envvars_force_uppercase: bool = True

    # ------------------------------------------------------------------
    # Solver configuration
    # ------------------------------------------------------------------

    deps_modifier: DepsModifier = DepsModifier.NOT_SET
    update_modifier: UpdateModifier = UpdateModifier.UPDATE_SPECS
    sat_solver: SatSolverChoice = SatSolverChoice.PYCOSAT
    solver_ignore_timestamps: bool = False
    solver: str = DEFAULT_SOLVER
    force_remove: bool = False
    force_reinstall: bool = False
    target_prefix_override: str = ""
    unsatisfiable_hints: bool = True
    unsatisfiable_hints_check_depth: int = 2

    # ------------------------------------------------------------------
    # conda-build
    # ------------------------------------------------------------------

    bld_path: str = ""
    anaconda_upload: bool | None = None
    croot: str = ""
    conda_build: dict[str, str] = msgspec.field(default_factory=dict)

    # ------------------------------------------------------------------
    # Virtual packages
    # ------------------------------------------------------------------

    override_virtual_packages: dict[str, str | None] = msgspec.field(default_factory=dict)

    # ------------------------------------------------------------------
    # Plugin configuration
    # ------------------------------------------------------------------

    no_plugins: bool = bool(NO_PLUGINS)

    # ------------------------------------------------------------------
    # Backend selection
    # ------------------------------------------------------------------

    conda_context_backend: str = "pydantic"

    # ------------------------------------------------------------------
    # Validators (equivalent to Pydantic field_validators + model_validator)
    # ------------------------------------------------------------------

    def __post_init__(self) -> None:  # type: ignore[override]
        """Run all field and cross-field validation after C-level construction."""
        errors: list[str] = []

        # 1. ssl_verify: normalize string booleans; validate path/truststore
        v = self.ssl_verify
        if isinstance(v, str):
            lo = v.strip().lower()
            if lo in ("true", "1", "yes"):
                msgspec.structs.force_setattr(self, "ssl_verify", True)
            elif lo in ("false", "0", "no"):
                msgspec.structs.force_setattr(self, "ssl_verify", False)
            else:
                # Keep as str — validate truststore or path
                if v == "truststore":
                    if sys.version_info < (3, 10):
                        errors.append(
                            "`ssl_verify: truststore` is only supported on Python 3.10 or later"
                        )
                elif not Path(v).exists():
                    errors.append(
                        f"ssl_verify value '{v}' must be a boolean, a path to a "
                        "certificate bundle file, a path to a directory containing "
                        "certificates of trusted CAs, or 'truststore' to use the "
                        "operating system certificate store."
                    )

        # 2. channel_alias: must have a scheme
        if self.channel_alias:
            from urllib.parse import urlparse

            parsed = urlparse(self.channel_alias)
            if not parsed.scheme:
                errors.append(
                    f"channel_alias value '{self.channel_alias}' must have scheme/protocol."
                )

        # 3. default_python: must match '[23].[0-9][0-9]?' or be empty/None
        dp = self.default_python
        if dp is not None and dp != "":
            valid = False
            if isinstance(dp, str) and len(dp) >= 3 and dp[1] == ".":
                try:
                    fv = float(dp)
                    valid = 2.0 <= fv < 4.0
                except ValueError:
                    pass
            if not valid:
                errors.append(
                    f"default_python value '{dp}' not of the form '[23].[0-9][0-9]?' or ''"
                )

        # 4. list_fields: all values must be valid conda list column names
        lf = self.list_fields
        if lf:
            invalid = set(lf).difference(CONDA_LIST_FIELDS)
            if invalid:
                errors.append(
                    f"Invalid value(s): {sorted(invalid)}. "
                    f"Valid values are: {sorted(CONDA_LIST_FIELDS)}"
                )

        # 5. Cross-field constraints
        if self.always_copy and self.always_softlink:
            errors.append(
                "'always_copy' and 'always_softlink' are mutually exclusive. "
                "Only one can be set to 'True'."
            )
        if self.client_ssl_cert_key and not self.client_ssl_cert:
            errors.append(
                "'client_ssl_cert' is required when 'client_ssl_cert_key' is defined"
            )

        if errors:
            raise ValueError("\n".join(errors))
