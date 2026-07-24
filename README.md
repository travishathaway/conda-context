# conda-context

A Pydantic-backed replacement for `conda.base.context.Context` — with better validation errors and full source provenance.

```[!WARNING]

This library is in early development and makes no stability guarantees.
The API may change without notice between releases. It has not been
battle-tested against the full range of conda configurations in real
environments. Use it for experimentation, tooling prototypes, and conda
plugin development only.

```

## What it is

`conda-context` is a drop-in replacement for `conda.base.context.Context` targeting **conda 26.5.3 exactly**. It replaces conda's bespoke metaclass-based configuration system with:

- A **Pydantic v2 model** (`CondaConfig`) covering all 60+ configuration fields — typed, documented, and validated.
- A **layered merge engine** that resolves `.condarc` files, `CONDA_*` environment variables, and CLI args in the same priority order as conda, while tracking the exact file and line number (or env var name) for every resolved value.
- **Precise validation errors** that tell you *where* the bad value came from, not just that something went wrong.
- **Monkey-patch helpers** for replacing `conda.base.context` in running conda processes (for plugin authors).

Each `conda-context` release is pinned to exactly one conda release. `conda-context==26.5.3` targets `conda==26.5.3`.

## Installation

Clone the repository and enter the development environment with [pixi](https://pixi.sh):

```bash
git clone https://github.com/anomalyco/conda-context
cd conda-context
pixi shell -e dev
```

That installs conda 26.5.3, all dependencies, and the `condactx` command into the pixi dev environment shell. No other setup is required.

### Trying it out with `condactx`

`condactx` is a drop-in wrapper around the `conda` CLI. It monkey-patches `conda.base.context` with the Pydantic-backed replacement before handing off to conda's own command dispatcher. Every `conda` subcommand works as normal:

```bash
condactx info
condactx config --show ssl_verify
condactx config --show channel_priority
```

#### Better error messages for misconfigured `.condarc` files

The main benefit over plain `conda` is what happens when your `.condarc` contains a bad value. Create a test file to see the difference:

```bash
cat > /tmp/bad_condarc.yaml << 'EOF'
channels:
  - defaults
ssl_verify: yess
channel_priority: turbo
EOF
```

**With plain conda:**

```bash
CONDARC=/tmp/bad_condarc.yaml conda info
```

conda either silently ignores the bad value, coerces it without warning, or
raises a generic traceback with no indication of which file or line caused the
problem.

**With `condactx`:**

```bash
$ CONDARC=/tmp/bad_condarc.yaml condactx info

Configuration validation failed:

  Field:   ssl_verify
  Value:   'yess'
  Error:   Value error, ssl_verify value 'yess' must be a boolean, a path to a
           certificate bundle file, a path to a directory containing
           certificates of trusted CAs, or 'truststore' to use the operating
           system certificate store.
  Source:  /tmp/bad_condarc.yaml, line 3
  Hint:    Did you mean `ssl_verify: true`?

  Field:   channel_priority
  Value:   'turbo'
  Error:   Input should be 'strict', 'flexible' or 'disabled'
  Source:  /tmp/bad_condarc.yaml, line 4
  Hint:    Valid values are: "flexible", "strict", "disabled".
```

Each error includes:

- **Field** — the exact configuration key that failed.
- **Value** — the raw value that was rejected.
- **Error** — what was wrong with it.
- **Source** — the file path and line number (or `environment variable CONDA_*`) where the value came from.
- **Hint** — an actionable suggestion for how to fix it.

Environment variable errors are identified the same way:

```bash
$ CONDA_SSL_VERIFY=yess condactx info

Configuration validation failed:

  Field:   ssl_verify
  Value:   'yess'
  Error:   ...
  Source:  environment variable CONDA_SSL_VERIFY
  Hint:    Did you mean `ssl_verify: true`?
```

## Requirements

- Python 3.10+
- `pydantic>=2.0`
- `ruamel.yaml>=0.18,<0.19`
- `conda==26.5.3` (optional — only required for `condactx` and integration tests)

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
