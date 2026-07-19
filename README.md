# conda-context

A Pydantic-backed replacement for `conda.base.context.Context` — with better validation errors, full source provenance, and a safe API for reading and writing `.condarc` files.

---

> **EXPERIMENTAL — DO NOT USE IN PRODUCTION**
>
> This library is in early development and makes no stability guarantees.
> The API may change without notice between releases. It has not been
> battle-tested against the full range of conda configurations in real
> environments. Use it for experimentation, tooling prototypes, and conda
> plugin development only.

---

## What it is

`conda-context` is a drop-in replacement for `conda.base.context.Context` targeting **conda 26.5.3 exactly**. It replaces conda's bespoke metaclass-based configuration system with:

- A **Pydantic v2 model** (`CondaConfig`) covering all 60+ configuration fields — typed, documented, and validated.
- A **layered merge engine** that resolves `.condarc` files, `CONDA_*` environment variables, and CLI args in the same priority order as conda, while tracking the exact file and line number (or env var name) for every resolved value.
- **Precise validation errors** that tell you *where* the bad value came from, not just that something went wrong.
- A **`.condarc` write API** (`CondarC`) that preserves comments and formatting and validates mutations against the full merged config before writing.
- **Monkey-patch helpers** for replacing `conda.base.context` in running conda processes (for plugin authors).

Each `conda-context` release is pinned to exactly one conda release. `conda-context==26.5.3` targets `conda==26.5.3`.

## Installation

Installation is currently not possible. You are advised to clone this repository and use it in a development environment.

## Requirements

- Python 3.11+
- `pydantic>=2.0`
- `ruamel.yaml>=0.18,<0.19`
- `conda==26.5.3` (optional — only required for monkey-patching and integration tests)

---

## Usage

### Reading configuration

```python
from conda_context.context import Context

# Instantiate with conda's default search path
ctx = Context()

print(ctx.ssl_verify)        # True
print(ctx.channels)          # ('defaults',)
print(ctx.subdir)            # 'linux-64'  (auto-detected)
print(ctx.offline)           # False
print(ctx.channel_priority)  # 'flexible'

# Override with a specific .condarc file
ctx = Context(search_path=("/path/to/my.condarc",))
print(ctx.ssl_verify)

# Override with CLI args (mirrors conda's own reset_context usage)
from argparse import Namespace
ctx = Context(argparse_args=Namespace(offline=True, quiet=True))
print(ctx.offline)   # True
```

### Validating a configuration

```python
from conda_context.schemas._26_5_3 import CondaConfig
from pydantic import ValidationError

try:
    cfg = CondaConfig(
        channel_priority="invalid",
        always_copy=True,
        always_softlink=True,   # conflicts with always_copy
    )
except ValidationError as e:
    print(e)
```

### Better validation errors with source provenance

When you instantiate `Context`, any validation errors are raised as `CondaConfigError` — an enriched exception that tells you exactly where in your configuration the bad value came from.

```python
from conda_context.context import Context
from conda_context.errors import CondaConfigError

try:
    # ~/.condarc contains:  ssl_verify: yess
    ctx = Context()
except CondaConfigError as e:
    print(e)
    # Configuration validation failed:
    #
    #   Field:   ssl_verify
    #   Value:   'yess'
    #   Error:   ssl_verify value 'yess' must be a boolean, a path to a
    #            certificate bundle file, ...
    #   Source:  /home/user/.condarc, line 4
    #   Hint:    Did you mean `ssl_verify: true`?

    # Machine-readable form
    errors = e.as_dict()
    # [
    #   {
    #     "field": "ssl_verify",
    #     "value": "yess",
    #     "message": "...",
    #     "hint": "Did you mean `ssl_verify: true`?",
    #     "source": {"type": "yaml_file", "path": "/home/user/.condarc", "line": 4}
    #   }
    # ]
```

### Writing .condarc files

`CondarC` provides a full CRUD API for `.condarc` files. It uses `ruamel.yaml` in round-trip mode, so your comments and key ordering survive every write.

#### Load and modify an existing file

```python
from conda_context.condarc import CondarC

c = CondarC.load("/home/user/.condarc")

# Set a scalar value
c.set("ssl_verify", False)

# Prepend a channel (adds to front)
c.prepend_channel("conda-forge")

# Append a channel (adds to back)
c.append_channel("my-local-channel")

# Remove a channel
c.remove_from("channels", "defaults")

# See what changed before writing
print(c.diff())
# {'ssl_verify': (True, False), 'channels': (['defaults'], ['conda-forge', 'my-local-channel'])}

# Write back — validates full merged config first, then writes atomically
c.save()
```

#### Create a new file from scratch

```python
from pathlib import Path
from conda_context.condarc import CondarC

c = CondarC.create(Path("/etc/conda/condarc"))

c.set("ssl_verify", True)
c.set("channel_priority", "strict")
c.set("channels", ["conda-forge", "defaults"])
c.set("offline", False)

# File is not written until .save() is called
c.save()
```

#### Remove a key (fall back to lower-priority source)

```python
c = CondarC.load("/home/user/.condarc")
c.unset("ssl_verify")   # removes key; falls back to system .condarc or default
c.save()
```

#### Skip cross-field validation on save

If an existing condarc layer already has a conflicting setting, you can save your isolated changes without full-context validation:

```python
c = CondarC.load("/home/user/.condarc")
c.set("offline", True)
c.save(strict=False)   # only validates fields in this file
```

#### Read all keys set in a file

```python
c = CondarC.load("/home/user/.condarc")
print(c.get_all())
# {'channels': ['conda-forge', 'defaults'], 'ssl_verify': False}
```

### Monkey-patching conda (plugin authors)

> **Warning:** This replaces the global `conda.base.context.context` singleton
> in the current process. It must be called **before any other `conda.*` module
> is imported**. Use only at the entry point of a conda plugin.

```python
# In your plugin's entry point — before any other conda imports
from conda_context.patch import patch_module

patch_module()

# All subsequent conda code uses conda-context's Context
import conda.base.context
print(type(conda.base.context.context))
# <class 'conda_context.context.Context'>
```

An import hook is also available for cases where you need to intercept the import itself:

```python
from conda_context.patch import install_import_hook

hook = install_import_hook()   # must be called before `import conda`

import conda.base.context      # resolves to conda_context.context

# Later, to restore:
hook.uninstall()
```

### Schema introspection

```python
import conda_context

# Get the CondaConfig model for a specific conda version
CondaConfig = conda_context.get_schema_for_version("26.5.3")

# Full JSON Schema (useful for config editors, documentation, etc.)
import json
schema = CondaConfig.model_json_schema()
print(json.dumps(schema, indent=2))
```

### Generating a schema for a new conda release

```bash
# Fetches conda/base/context.py at the given tag and emits a schema module
python -m conda_context.generator extract --conda-tag 26.7.0

# Preview without writing
python -m conda_context.generator extract --conda-tag 26.7.0 --dry-run
```

---

## Provenance map

The merge engine tracks every resolved value back to its source. You can access this directly:

```python
from conda_context.context import Context

ctx = Context()

# ctx._provenance is a dict[str, ProvenanceInfo]
for field, info in ctx._provenance.items():
    print(f"{field}: {info.describe()}")
# ssl_verify: /etc/conda/condarc, line 3
# channels: /home/user/.condarc, line 7
# offline: environment variable CONDA_OFFLINE
```

---

## Running tests

```bash
# With pixi (installs conda 26.5.3 automatically)
pixi run test

# With plain pytest (conda-dependent tests will be skipped)
pytest tests/ -v
```

---

## Version compatibility

| conda-context | conda  |
|---------------|--------|
| 26.5.3        | 26.5.3 |

Each release of `conda-context` targets exactly one conda release. When conda 26.7.0 ships, a corresponding `conda-context==26.7.0` will be released with an updated schema generated from that tag.

---

## License

MIT. See [LICENSE](LICENSE).
