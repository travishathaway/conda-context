"""
Provenance tracking for conda configuration sources.

Records where each configuration value came from so that validation errors
can point the user to the exact file, line number, or environment variable
that produced the invalid value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class ProvenanceInfo:
    """Records the origin of a single resolved configuration value.

    Attributes:
        source_type: One of ``"yaml_file"``, ``"env_var"``, or ``"argparse"``.
        path: Absolute path to the YAML file (only for ``source_type="yaml_file"``).
        line: 1-based line number within the YAML file where the key was defined
            (only for ``source_type="yaml_file"``).
        env_var: Name of the environment variable (only for ``source_type="env_var"``).
    """

    source_type: Literal["yaml_file", "env_var", "argparse"]
    path: Path | None = field(default=None)
    line: int | None = field(default=None)
    env_var: str | None = field(default=None)

    def describe(self) -> str:
        """Return a short human-readable description of the source location."""
        if self.source_type == "yaml_file":
            loc = str(self.path) if self.path is not None else ""
            if self.line is not None:
                loc = f"{loc}, line {self.line}"
            return loc
        elif self.source_type == "env_var":
            return f"environment variable {self.env_var}"
        else:
            return "command-line argument"


# Mapping from field name to its winning ProvenanceInfo.
# Fields that take their compiled-in default are absent from the map.
ProvenanceMap = dict[str, ProvenanceInfo]
