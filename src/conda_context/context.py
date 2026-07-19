"""
Context — drop-in replacement for conda.base.context.Context.

Structurally mirrors conda 26.5.3's Context class, exposing the same public
and private API surface required for plugin use and module-attribute
monkey-patching.

Architecture (from design.md D1):
  - ``CondaConfig`` (Pydantic) handles type coercion and validation.
  - ``MergeEngine`` resolves layered sources + builds ProvenanceMap.
  - ``Context`` wraps both, exposing conda's mutation protocol and all
    computed properties.
"""

from __future__ import annotations

import logging
import os
import platform
import struct
import sys
from argparse import Namespace
from collections.abc import Iterator
from contextlib import contextmanager
from functools import cached_property
from os.path import abspath, expanduser, isdir, isfile, join
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .constants import (
    APP_NAME,
    DEFAULT_CHANNELS_UNIX,
    DEFAULT_CHANNELS_WIN,
    ROOT_ENV_NAME,
)
from .constants import (
    SEARCH_PATH as _FALLBACK_SEARCH_PATH,
)
from .errors import CondaConfigError
from .merge import MergeEngine
from .provenance import ProvenanceMap
from .schemas._26_5_3 import CondaConfig

log = logging.getLogger(__name__)

# Try to get the actual search path from conda if available
try:
    from conda.base.constants import (
        SEARCH_PATH as _DEFAULT_SEARCH_PATH,  # type: ignore[import]
    )
except ImportError:
    _DEFAULT_SEARCH_PATH = _FALLBACK_SEARCH_PATH
_non_x86_machines = frozenset(
    (
        "armv6l",
        "armv7l",
        "aarch64",
        "arm64",
        "ppc64",
        "ppc64le",
        "riscv64",
        "s390x",
    )
)

_platform_map = {
    "linux2": "linux",
    "linux": "linux",
    "darwin": "osx",
    "win32": "win",
    "zos": "zos",
}

_arch_names = {32: "x86", 64: "x86_64"}

# Prefix magic file used to test root_writable
PREFIX_MAGIC_FILE = join("conda-meta", "history")

# KNOWN_SUBDIRS is large; we use a minimal set here
KNOWN_SUBDIRS = frozenset(
    (
        "noarch",
        "linux-32",
        "linux-64",
        "linux-aarch64",
        "linux-ppc64",
        "linux-ppc64le",
        "linux-s390x",
        "osx-64",
        "osx-arm64",
        "win-32",
        "win-64",
        "win-arm64",
        "zos-z",
    )
)

# Try to get the actual search path from conda if available
try:
    from conda.base.constants import (
        SEARCH_PATH as _DEFAULT_SEARCH_PATH,  # type: ignore[import]
    )
except ImportError:
    _DEFAULT_SEARCH_PATH = _FALLBACK_SEARCH_PATH


def _unique(iterable):
    """Yield unique items preserving order."""
    seen = set()
    for item in iterable:
        if item not in seen:
            seen.add(item)
            yield item


def _expand(path: str) -> str:
    """Expand user and environment variables in a path string."""
    return abspath(expanduser(os.path.expandvars(path)))


class Context:
    """Pydantic-backed replacement for ``conda.base.context.Context``.

    Supports the same public and private API as conda 26.5.3's Context,
    including the mutation protocol (``_set_search_path``, ``_reset_cache``,
    ``_set_argparse_args``, ``_set_env_vars``) and all computed properties.

    Args:
        search_path: Sequence of file/directory paths to search for condarc
            files, in ascending priority order.
        argparse_args: Parsed CLI arguments (``argparse.Namespace``).
        **kwargs: Additional keyword arguments (ignored, for API compatibility).
    """

    def __init__(
        self,
        search_path: tuple[str | Path, ...] | None = None,
        argparse_args: Namespace | None = None,
        **kwargs: Any,
    ) -> None:
        self._cache_: dict[str, Any] = {}
        self._reset_callbacks: dict[Any, None] = {}
        self._validation_errors: list[Any] = []

        self._set_search_path(_DEFAULT_SEARCH_PATH if search_path is None else search_path)
        self._set_env_vars(APP_NAME)
        self._set_argparse_args(argparse_args)

    # ------------------------------------------------------------------
    # Mutation protocol (mirrors conda's Configuration base class)
    # ------------------------------------------------------------------

    def _set_search_path(
        self,
        search_path: tuple[str | Path, ...],
        **kwargs: Any,
    ) -> Context:
        self._search_path = tuple(search_path)
        self._rebuild()
        return self

    def _set_env_vars(self, app_name: str | None = None) -> Context:
        self._app_name = app_name
        self._rebuild()
        return self

    def _set_argparse_args(self, argparse_args: Namespace | None) -> Context:
        if hasattr(argparse_args, "__dict__"):
            items = vars(argparse_args).items()
        elif not argparse_args:
            items = ()
        else:
            items = argparse_args.items() if hasattr(argparse_args, "items") else ()

        # Filter out None values (conda uses NULL sentinel; we use None)
        self._argparse_args = {k: v for k, v in items if v is not None}
        self._rebuild()
        return self

    def _reset_cache(self) -> None:
        self._cache_ = {}
        # Invalidate cached_property values
        for key in list(self.__dict__.keys()):
            if key.startswith("_") and not key.startswith("__"):
                continue
            # Remove cached_property cache entries
            if key in type(self).__dict__ and isinstance(type(self).__dict__[key], cached_property):
                self.__dict__.pop(key, None)

    def _rebuild(self) -> None:
        """Re-run merge and validation after any source change."""
        self._reset_cache()
        engine = MergeEngine(
            search_path=self._search_path,
            argparse_args=Namespace(**self._argparse_args)
            if hasattr(self, "_argparse_args") and self._argparse_args
            else None,
        )
        merged, provenance = engine.resolve()
        self.raw_data = merged
        self._provenance: ProvenanceMap = provenance

        try:
            self._config = CondaConfig(**merged)
        except ValidationError as exc:
            raise CondaConfigError(exc, provenance) from exc

    # ------------------------------------------------------------------
    # Raw config field properties — delegate to CondaConfig
    # ------------------------------------------------------------------

    @property
    def add_pip_as_python_dependency(self) -> bool:
        return self._config.add_pip_as_python_dependency

    @property
    def allow_conda_downgrades(self) -> bool:
        return self._config.allow_conda_downgrades

    @property
    def allow_cycles(self) -> bool:
        return self._config.allow_cycles

    @property
    def allow_softlinks(self) -> bool:
        return self._config.allow_softlinks

    @property
    def auto_update_conda(self) -> bool:
        return self._config.auto_update_conda

    @property
    def auto_activate(self) -> bool:
        return self._config.auto_activate

    @property
    def _default_activation_env(self) -> str:
        return self._config.default_activation_env

    @property
    def auto_stack(self) -> int:
        return self._config.auto_stack

    @property
    def notify_outdated_conda(self) -> bool:
        return self._config.notify_outdated_conda

    @property
    def clobber(self) -> bool:
        return self._config.clobber

    @property
    def changeps1(self) -> bool:
        return self._config.changeps1

    @property
    def env_prompt(self) -> str:
        return self._config.env_prompt

    @property
    def environment_specifier(self) -> str | None:
        return self._config.environment_specifier

    @property
    def _create_default_packages(self) -> tuple[str, ...]:
        return self._config.create_default_packages

    @property
    def register_envs(self) -> bool:
        return self._config.register_envs

    @property
    def protect_frozen_envs(self) -> bool:
        return self._config.protect_frozen_envs

    @property
    def default_python(self) -> str | None:
        return self._config.default_python

    @property
    def download_only(self) -> bool:
        return self._config.download_only

    @property
    def enable_private_envs(self) -> bool:
        return self._config.enable_private_envs

    @property
    def force_32bit(self) -> bool:
        return self._config.force_32bit

    @property
    def non_admin_enabled(self) -> bool:
        return self._config.non_admin_enabled

    @property
    def prefix_data_interoperability(self) -> bool:
        return self._config.prefix_data_interoperability

    @property
    def _default_threads(self) -> int:
        return self._config.default_threads

    @property
    def _repodata_threads(self) -> int:
        return self._config.repodata_threads

    @property
    def _fetch_threads(self) -> int:
        return self._config.fetch_threads

    @property
    def _verify_threads(self) -> int:
        return self._config.verify_threads

    @property
    def _execute_threads(self) -> int:
        return self._config.execute_threads

    @property
    def _aggressive_update_packages(self) -> tuple[str, ...]:
        return self._config.aggressive_update_packages

    @property
    def safety_checks(self) -> str:
        return str(self._config.safety_checks)

    @property
    def extra_safety_checks(self) -> bool:
        return self._config.extra_safety_checks

    @property
    def _signing_metadata_url_base(self) -> str | None:
        return self._config.signing_metadata_url_base

    @property
    def path_conflict(self) -> str:
        return str(self._config.path_conflict)

    @property
    def pinned_packages(self) -> tuple[str, ...]:
        return self._config.pinned_packages

    @property
    def disallowed_packages(self) -> tuple[str, ...]:
        return self._config.disallowed_packages

    @property
    def rollback_enabled(self) -> bool:
        return self._config.rollback_enabled

    @property
    def track_features(self) -> tuple[str, ...]:
        return self._config.track_features

    @property
    def use_index_cache(self) -> bool:
        return self._config.use_index_cache

    @property
    def separate_format_cache(self) -> bool:
        return self._config.separate_format_cache

    @property
    def _root_prefix(self) -> str:
        return self._config.root_prefix

    @property
    def _envs_dirs(self) -> tuple[str, ...]:
        return self._config.envs_dirs

    @property
    def _pkgs_dirs(self) -> tuple[str, ...]:
        return self._config.pkgs_dirs

    @property
    def _subdir(self) -> str:
        return self._config.subdir

    @property
    def _subdirs(self) -> tuple[str, ...]:
        return self._config.subdirs

    @property
    def _export_platforms(self) -> tuple[str, ...]:
        return self._config.export_platforms

    @property
    def local_repodata_ttl(self) -> bool | int:
        return self._config.local_repodata_ttl

    @property
    def ssl_verify(self) -> bool | str:
        return self._config.ssl_verify

    @property
    def client_ssl_cert(self) -> str | None:
        return self._config.client_ssl_cert

    @property
    def client_ssl_cert_key(self) -> str | None:
        return self._config.client_ssl_cert_key

    @property
    def proxy_servers(self) -> dict[str, str | None]:
        return self._config.proxy_servers

    @property
    def remote_connect_timeout_secs(self) -> float:
        return self._config.remote_connect_timeout_secs

    @property
    def remote_read_timeout_secs(self) -> float:
        return self._config.remote_read_timeout_secs

    @property
    def remote_max_retries(self) -> int:
        return self._config.remote_max_retries

    @property
    def remote_backoff_factor(self) -> int:
        return self._config.remote_backoff_factor

    @property
    def add_anaconda_token(self) -> bool:
        return self._config.add_anaconda_token

    @property
    def allow_non_channel_urls(self) -> bool:
        return self._config.allow_non_channel_urls

    @property
    def _channel_alias(self) -> str:
        return self._config.channel_alias

    @property
    def channel_priority(self) -> str:
        return str(self._config.channel_priority)

    @property
    def _channels(self) -> tuple[str, ...]:
        return self._config.channels

    @property
    def channel_settings(self) -> tuple[dict[str, str], ...]:
        return self._config.channel_settings

    @property
    def _custom_channels(self) -> dict[str, str]:
        return self._config.custom_channels

    @property
    def _custom_multichannels(self) -> dict[str, list[str]]:
        return self._config.custom_multichannels

    @property
    def _default_channels(self) -> tuple[str, ...]:
        return self._config.default_channels

    @property
    def _migrated_channel_aliases(self) -> tuple[str, ...]:
        return self._config.migrated_channel_aliases

    @property
    def migrated_custom_channels(self) -> dict[str, str]:
        return self._config.migrated_custom_channels

    @property
    def override_channels_enabled(self) -> bool:
        return self._config.override_channels_enabled

    @property
    def show_channel_urls(self) -> bool | None:
        return self._config.show_channel_urls

    @property
    def use_local(self) -> bool:
        return self._config.use_local

    @property
    def allowlist_channels(self) -> tuple[str, ...]:
        return self._config.allowlist_channels

    @property
    def denylist_channels(self) -> tuple[str, ...]:
        return self._config.denylist_channels

    @property
    def repodata_fns(self) -> tuple[str, ...]:
        return self._config.repodata_fns

    @property
    def _use_only_tar_bz2(self) -> bool | None:
        return self._config.use_only_tar_bz2

    @property
    def always_softlink(self) -> bool:
        return self._config.always_softlink

    @property
    def always_copy(self) -> bool:
        return self._config.always_copy

    @property
    def always_yes(self) -> bool | None:
        return self._config.always_yes

    @property
    def _debug(self) -> bool:
        return self._config.debug

    @property
    def _trace(self) -> bool:
        return self._config.trace

    @property
    def dev(self) -> bool:
        return self._config.dev

    @property
    def dry_run(self) -> bool:
        return self._config.dry_run

    @property
    def _error_upload_url(self) -> str:
        return self._config.error_upload_url

    @property
    def force(self) -> bool:
        return self._config.force

    @property
    def json(self) -> bool:
        return self._config.json_output

    @property
    def _console(self) -> str:
        return self._config.console

    @property
    def list_fields(self) -> tuple[str, ...]:
        return self._config.list_fields

    @property
    def offline(self) -> bool:
        return self._config.offline

    @property
    def quiet(self) -> bool:
        return self._config.quiet

    @property
    def ignore_pinned(self) -> bool:
        return self._config.ignore_pinned

    @property
    def _report_errors(self) -> bool | None:
        return self._config.report_errors

    @property
    def shortcuts(self) -> bool:
        return self._config.shortcuts

    @property
    def number_channel_notices(self) -> int:
        return self._config.number_channel_notices

    @property
    def shortcuts_only(self) -> tuple[str, ...]:
        return self._config.shortcuts_only

    @property
    def _verbosity(self) -> int:
        return self._config.verbosity

    @property
    def experimental(self) -> tuple[str, ...]:
        return self._config.experimental

    @property
    def preview(self) -> tuple[str, ...]:
        return self._config.preview

    @property
    def no_lock(self) -> bool:
        return self._config.no_lock

    @property
    def repodata_use_zst(self) -> bool:
        return self._config.repodata_use_zst

    @property
    def repodata_use_shards(self) -> bool:
        return self._config.repodata_use_shards

    @property
    def envvars_force_uppercase(self) -> bool:
        return self._config.envvars_force_uppercase

    @property
    def deps_modifier(self) -> str:
        return str(self._config.deps_modifier)

    @property
    def update_modifier(self) -> str:
        return str(self._config.update_modifier)

    @property
    def sat_solver(self) -> str:
        return str(self._config.sat_solver)

    @property
    def solver_ignore_timestamps(self) -> bool:
        return self._config.solver_ignore_timestamps

    @property
    def solver(self) -> str:
        return self._config.solver

    @property
    def force_remove(self) -> bool:
        return self._config.force_remove

    @property
    def force_reinstall(self) -> bool:
        return self._config.force_reinstall

    @property
    def target_prefix_override(self) -> str:
        return self._config.target_prefix_override

    @property
    def unsatisfiable_hints(self) -> bool:
        return self._config.unsatisfiable_hints

    @property
    def unsatisfiable_hints_check_depth(self) -> int:
        return self._config.unsatisfiable_hints_check_depth

    @property
    def bld_path(self) -> str:
        return self._config.bld_path

    @property
    def anaconda_upload(self) -> bool | None:
        return self._config.anaconda_upload

    @property
    def _croot(self) -> str:
        return self._config.croot

    @property
    def _conda_build(self) -> dict[str, str]:
        return self._config.conda_build

    @property
    def _override_virtual_packages(self) -> dict[str, str | None]:
        return self._config.override_virtual_packages

    @property
    def no_plugins(self) -> bool:
        return self._config.no_plugins

    # ------------------------------------------------------------------
    # Tier 1: Pure computed properties
    # ------------------------------------------------------------------

    @property
    def platform(self) -> str:
        return _platform_map.get(sys.platform, "unknown")

    @property
    def arch_name(self) -> str:
        m = platform.machine().lower()
        if m in _non_x86_machines:
            return m
        return _arch_names[self.bits]

    @property
    def bits(self) -> int:
        if self.force_32bit:
            return 32
        return 8 * struct.calcsize("P")

    @property
    def subdir(self) -> str:
        if self._subdir:
            return self._subdir
        return self._native_subdir()

    def _native_subdir(self) -> str:
        m = platform.machine().lower()
        if m in _non_x86_machines:
            return f"{self.platform}-{m}"
        elif self.platform == "zos":
            return "zos-z"
        return f"{self.platform}-{self.bits}"

    @property
    def subdirs(self) -> tuple[str, str]:
        return self._subdirs or (self.subdir, "noarch")

    @cached_property
    def known_subdirs(self) -> frozenset[str]:
        return frozenset((*KNOWN_SUBDIRS, *self.subdirs))

    @property
    def export_platforms(self) -> tuple[str, ...]:
        argparse_args = self._argparse_args or {}
        if argparse_args.get("override_platforms"):
            platforms = argparse_args.get("export_platforms") or ()
        else:
            platforms = self._export_platforms
        return tuple(_unique(platforms)) or (self.subdir,)

    @property
    def default_threads(self) -> int | None:
        return self._default_threads or None

    @property
    def repodata_threads(self) -> int | None:
        return self._repodata_threads or self.default_threads

    @property
    def fetch_threads(self) -> int | None:
        if self._fetch_threads == 0 and self._default_threads == 0:
            return 5
        return self._fetch_threads or self.default_threads

    @property
    def verify_threads(self) -> int | None:
        return self._verify_threads or self.default_threads

    @property
    def execute_threads(self) -> int | None:
        return self._execute_threads or 1

    @property
    def verbosity(self) -> int:
        return self._verbosity

    @property
    def trace(self) -> bool:
        return self._trace

    @property
    def debug(self) -> bool:
        return self._debug

    @property
    def info(self) -> bool:
        return self.verbosity >= 1

    @property
    def verbose(self) -> bool:
        return self.verbosity >= 1

    @property
    def log_level(self) -> int:
        import logging as _logging

        if self.trace:
            return 5  # TRACE
        elif self.debug:
            return _logging.DEBUG
        elif self.info:
            return _logging.INFO
        return _logging.WARNING

    @property
    def console(self) -> str:
        return self._console

    @property
    def default_activation_env(self) -> str:
        return self._default_activation_env

    @property
    def create_default_packages(self) -> tuple[str, ...]:
        return tuple(
            pkg for pkg in self._create_default_packages if pkg not in self.pinned_packages
        )

    @property
    def signing_metadata_url_base(self) -> str | None:
        return self._signing_metadata_url_base or None

    @property
    def binstar_upload(self) -> bool | None:
        return self._config.anaconda_upload

    @property
    def conda_build(self) -> dict[str, Any]:
        return dict(self._conda_build)

    @property
    def override_virtual_packages(self) -> dict[str, str | None]:
        return dict(self._override_virtual_packages)

    @property
    def default_activation_prefix(self) -> Path:
        """Path to the default activation environment."""
        env_name = self.default_activation_env
        if not env_name or env_name == ROOT_ENV_NAME:
            return Path(self.root_prefix)
        for envs_dir in self.envs_dirs:
            candidate = Path(envs_dir) / env_name
            if candidate.is_dir():
                return candidate
        return Path(self.root_prefix)

    # Channel-related computed properties
    # NOTE: These require conda for full resolution (Channel model objects).
    # They raise ImportError with a clear message when conda is not installed.

    @property
    def channels(self) -> tuple[str, ...]:
        """Resolved channel list.

        Requires conda for full alias resolution and validation.
        Falls back to raw _channels when conda is unavailable.
        """
        try:
            from conda.base.context import validate_channels  # type: ignore[import]

            local_channels: tuple[str, ...] = ("local",) if self.use_local else ()
            return validate_channels((*local_channels, *self._channels))
        except ImportError:
            return self._channels

    @property
    def channel_alias(self):  # type: ignore[return]
        """Resolved channel alias (Channel object).

        Requires conda. Returns raw string when conda unavailable.
        """
        try:
            from conda.common.url import split_scheme_auth_token  # type: ignore[import]
            from conda.models.channel import Channel  # type: ignore[import]

            location, scheme, auth, token = split_scheme_auth_token(self._channel_alias)
            return Channel(scheme=scheme, auth=auth, location=location, token=token)
        except ImportError:
            return self._channel_alias

    @property
    def migrated_channel_aliases(self) -> tuple:
        """Requires conda for Channel objects. Returns raw strings otherwise."""
        try:
            from conda.common.url import split_scheme_auth_token  # type: ignore[import]
            from conda.models.channel import Channel  # type: ignore[import]

            return tuple(
                Channel(scheme=scheme, auth=auth, location=location, token=token)
                for location, scheme, auth, token in (
                    split_scheme_auth_token(c) for c in self._migrated_channel_aliases
                )
            )
        except ImportError:
            return self._migrated_channel_aliases

    @property
    def default_channels(self):  # type: ignore[return]
        """Requires conda for Channel model objects."""
        try:
            return self.custom_multichannels.get("defaults", ())
        except Exception:
            return self._default_channels

    @property
    def custom_multichannels(self) -> dict:
        """Requires conda for Channel model objects."""
        try:
            from conda.models.channel import Channel  # type: ignore[import]

            on_win = sys.platform == "win32"
            if (
                not on_win
                and self.subdir.startswith("win-")
                and set(self._default_channels) == set(DEFAULT_CHANNELS_UNIX)
            ):
                default_channels = list(DEFAULT_CHANNELS_WIN)
            else:
                default_channels = list(self._default_channels)

            channel_alias = self.channel_alias

            def _make_channel(url: str) -> Channel:
                return Channel.make_simple_channel(channel_alias, url)

            result = {}
            for name, urls in self._custom_multichannels.items():
                result[name] = tuple(_make_channel(u) for u in urls)
            if "defaults" not in self._custom_multichannels:
                result["defaults"] = tuple(_make_channel(u) for u in default_channels)
            result["local"] = self.conda_build_local_urls
            return result
        except ImportError:
            return {**self._custom_multichannels, "defaults": self._default_channels}

    @property
    def custom_channels(self) -> dict:
        """Requires conda for Channel model objects."""
        try:
            from itertools import chain

            from conda.models.channel import Channel  # type: ignore[import]

            channel_alias = self.channel_alias
            return {
                ch.name: ch
                for ch in (
                    *chain.from_iterable(self.custom_multichannels.values()),
                    *(
                        Channel.make_simple_channel(channel_alias, url, name)
                        for name, url in self._custom_channels.items()
                    ),
                )
                if hasattr(ch, "name")
            }
        except ImportError:
            return self._custom_channels

    @property
    def aggressive_update_packages(self) -> tuple:
        """Requires conda for MatchSpec objects. Returns raw strings otherwise."""
        try:
            from conda.models.match_spec import MatchSpec  # type: ignore[import]

            return tuple(MatchSpec(s) for s in self._aggressive_update_packages)
        except ImportError:
            return self._aggressive_update_packages

    @property
    def use_only_tar_bz2(self) -> bool:
        if self._use_only_tar_bz2 is not None:
            return self._use_only_tar_bz2
        try:
            import conda_package_handling.api  # type: ignore[import]

            return not conda_package_handling.api.libarchive_enabled
        except ImportError:
            return False

    @property
    def user_agent(self) -> str:
        """Construct the conda user-agent string."""
        try:
            import conda  # type: ignore[import]

            conda_version = conda.__version__
        except ImportError:
            conda_version = "unknown"
        python_version = ".".join(str(v) for v in sys.version_info[:3])
        plat = self.subdir
        return f"conda/{conda_version} requests/unknown Python/{python_version} {plat}"

    @property
    def conda_build_local_paths(self) -> tuple[str, ...]:
        candidates = [
            self._croot,
            self.bld_path,
            self._conda_build.get("root-dir", ""),
            join(self.root_prefix, "conda-bld"),
            "~/conda-bld",
        ]
        return tuple(_unique(_expand(d) for d in candidates if d and isdir(_expand(d))))

    @property
    def conda_build_local_urls(self) -> tuple[str, ...]:
        try:
            from conda.common.url import path_to_url  # type: ignore[import]

            return tuple(path_to_url(p) for p in self.conda_build_local_paths)
        except ImportError:
            return tuple(f"file://{p}" for p in self.conda_build_local_paths)

    # ------------------------------------------------------------------
    # Tier 2: Filesystem-interrogating computed properties
    # ------------------------------------------------------------------

    @cached_property
    def root_prefix(self) -> str:
        if self._root_prefix:
            return abspath(expanduser(self._root_prefix))
        return self.conda_prefix

    @property
    def conda_prefix(self) -> str:
        return abspath(sys.prefix)

    @property
    def av_data_dir(self) -> str:
        return join(self.conda_prefix, "etc", "conda")

    @property
    def root_writable(self) -> bool:
        path = join(self.root_prefix, PREFIX_MAGIC_FILE)
        if isfile(path):
            try:
                with open(path, "a+"):
                    pass
                return True
            except OSError as e:
                log.debug(e)
                return False
        return False

    @property
    def envs_dirs(self) -> tuple[str, ...]:
        on_win = sys.platform == "win32"
        if self.root_writable:
            fixed_dirs = [
                join(self.root_prefix, "envs"),
                join("~", ".conda", "envs"),
            ]
        else:
            fixed_dirs = [
                join("~", ".conda", "envs"),
                join(self.root_prefix, "envs"),
            ]
        if on_win:
            try:
                from platformdirs import user_data_dir  # type: ignore[import]

                fixed_dirs.append(join(user_data_dir(APP_NAME, APP_NAME), "envs"))
            except ImportError:
                pass
        return tuple(dict.fromkeys(_expand(p) for p in (*self._envs_dirs, *fixed_dirs)))

    @property
    def pkgs_dirs(self) -> tuple[str, ...]:
        on_win = sys.platform == "win32"
        if self._pkgs_dirs:
            return tuple(dict.fromkeys(_expand(p) for p in self._pkgs_dirs))
        cache_dir_name = "pkgs32" if self.force_32bit else "pkgs"
        fixed: list[str] = [self.root_prefix, join("~", ".conda")]
        if on_win:
            try:
                from platformdirs import user_data_dir  # type: ignore[import]

                fixed.append(user_data_dir(APP_NAME, APP_NAME))
            except ImportError:
                pass
        return tuple(dict.fromkeys(_expand(join(p, cache_dir_name)) for p in fixed))

    @property
    def trash_dir(self) -> str:
        """Best-effort: uses first pkgs_dir."""
        pkgs = self.pkgs_dirs
        if pkgs:
            trash = join(pkgs[0], ".trash")
            os.makedirs(trash, exist_ok=True)
            return trash
        trash = join(self.root_prefix, ".trash")
        os.makedirs(trash, exist_ok=True)
        return trash

    @property
    def active_prefix(self) -> str | None:
        return os.getenv("CONDA_PREFIX")

    @property
    def shlvl(self) -> int:
        return int(os.getenv("CONDA_SHLVL", -1))

    @property
    def default_prefix(self) -> str:
        if self.active_prefix:
            return self.active_prefix
        _default_env = os.getenv("CONDA_DEFAULT_ENV")
        if _default_env is None or _default_env == ROOT_ENV_NAME:
            return self.root_prefix
        elif os.sep in _default_env:
            return abspath(_default_env)
        for envs_dir in self.envs_dirs:
            candidate = join(envs_dir, _default_env)
            if isdir(candidate):
                return candidate
        return join(self.envs_dirs[0], _default_env) if self.envs_dirs else self.root_prefix

    @property
    def target_prefix(self) -> str:
        return self.default_prefix

    @property
    def config_files(self) -> tuple[str, ...]:
        """Paths to all condarc files that were successfully loaded."""
        engine = MergeEngine(search_path=self._search_path)
        return tuple(str(p) for p in engine._expand_search_path(self._search_path))

    @property
    def croot(self) -> str:
        if self._croot:
            return abspath(expanduser(self._croot))
        elif self.bld_path:
            return abspath(expanduser(self.bld_path))
        elif "root-dir" in self._conda_build:
            return abspath(expanduser(self._conda_build["root-dir"]))
        elif self.root_writable:
            return join(self.root_prefix, "conda-bld")
        return _expand("~/conda-bld")

    @property
    def local_build_root(self) -> str:
        return self.croot

    # ------------------------------------------------------------------
    # post_build_validation (API compat)
    # ------------------------------------------------------------------

    def post_build_validation(self) -> list[Any]:
        """Return validation errors list (API compatibility with conda's Configuration)."""
        errors = []
        if self.client_ssl_cert_key and not self.client_ssl_cert:
            errors.append({"field": "client_ssl_cert", "message": "'client_ssl_cert' is required"})
        if self.always_copy and self.always_softlink:
            errors.append(
                {
                    "field": "always_copy",
                    "message": "'always_copy' and 'always_softlink' are mutually exclusive.",
                }
            )
        return errors

    def __repr__(self) -> str:
        return f"Context(search_path={self._search_path!r})"


# ---------------------------------------------------------------------------
# Module-level singleton and mutation protocol
# ---------------------------------------------------------------------------


class _ContextStack:
    """Manages a stack of (search_path, argparse_args) for test isolation."""

    def __init__(self) -> None:
        self._stack: list[tuple[tuple, Namespace | None]] = []

    def push(
        self,
        search_path: tuple,
        argparse_args: Namespace | None,
    ) -> None:
        self._stack.append((context._search_path, Namespace(**context._argparse_args)))
        context._set_search_path(search_path)
        context._set_argparse_args(argparse_args)

    def pop(self) -> None:
        if self._stack:
            saved_path, saved_args = self._stack.pop()
            context._set_search_path(saved_path)
            context._set_argparse_args(saved_args)

    def replace(
        self,
        search_path: tuple,
        argparse_args: Namespace | None,
    ) -> None:
        context._set_search_path(search_path)
        context._set_argparse_args(argparse_args)

    def apply(self) -> None:
        pass


context_stack = _ContextStack()

try:
    context = Context((), None)
except CondaConfigError as e:
    import sys as _sys

    print(repr(e), file=_sys.stderr)
    _sys.exit(1)


def reset_context(
    search_path: tuple | None = None,
    argparse_args: Namespace | None = None,
) -> None:
    """Reset the global context singleton."""
    context._set_search_path(_DEFAULT_SEARCH_PATH if search_path is None else search_path)
    context._set_argparse_args(argparse_args)


@contextmanager
def stack_context(
    search_path: tuple,
    argparse_args: Namespace | None = None,
) -> Iterator[None]:
    """Temporarily push a new context onto the stack."""
    context_stack.push(search_path, argparse_args)
    try:
        yield
    finally:
        context_stack.pop()


@contextmanager
def fresh_context(argparse_args: Namespace | None = None) -> Iterator[None]:
    """Temporarily replace context with empty search path (all defaults)."""
    context_stack.push((), argparse_args)
    try:
        yield
    finally:
        context_stack.pop()


def replace_context(
    pushing: bool | None = None,
    search_path: tuple | None = None,
    argparse_args: Namespace | None = None,
) -> None:
    context_stack.replace(
        search_path=search_path or (),
        argparse_args=argparse_args,
    )


def stack_context_default(
    pushing: bool | None = None,
    argparse_args: Namespace | None = None,
) -> None:
    context_stack.push(_DEFAULT_SEARCH_PATH, argparse_args)


def replace_context_default(
    pushing: bool | None = None,
    argparse_args: Namespace | None = None,
) -> None:
    context_stack.replace(search_path=(), argparse_args=argparse_args)


# Alias for conda's test policy
conda_tests_ctxt_mgmt_def_pol = replace_context_default
