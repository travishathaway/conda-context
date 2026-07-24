#!/usr/bin/env python3
"""
Generate a self-contained HTML benchmark report from pytest-benchmark JSON output.

Usage
-----
  python scripts/generate_benchmark_report.py benchmark_output.json
  python scripts/generate_benchmark_report.py benchmark_output.json --output my_report.html
  python scripts/generate_benchmark_report.py benchmark_output.json --title "Sprint 42 Perf Report"

The report includes:
  1. A grouped bar chart comparing conda-context vs conda (mean ± 1 stddev).
  2. Box plots showing per-round timing distributions.
  3. A sortable summary table with ratios.
  4. A prose interpretation section with key findings.

The output HTML is self-contained: all JavaScript (Plotly) is inlined so the
file can be shared and opened without internet access.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Plotly availability check
# ---------------------------------------------------------------------------

try:
    import plotly.graph_objects as go
    import plotly.io as pio
except ImportError:
    print(
        "ERROR: 'plotly' is not installed.\n"
        "Install it with:\n"
        "  pip install conda-context[report]\n"
        "or:\n"
        "  pip install plotly>=5",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Benchmarks whose names start with this prefix are treated as conda reference
# data; all others are labelled as conda-context.
_CONDA_PREFIX = "test_bench_conda_"

# Human-readable labels for the known benchmark scenarios.
_SCENARIO_LABELS: dict[str, str] = {
    "test_bench_context_init_empty": "Context init (empty)",
    "test_bench_context_init_with_file": "Context init (with file)",
    "test_bench_single_rebuild_empty": "Single _rebuild()",
    "test_bench_merge_engine_empty": "MergeEngine (empty)",
    "test_bench_merge_engine_with_file": "MergeEngine (with file)",
    "test_bench_merge_engine_with_env_vars": "MergeEngine (env vars)",
    "test_bench_pydantic_empty": "Pydantic model (empty)",
    "test_bench_pydantic_full_merged": "Pydantic model (full)",
    "test_bench_warm_property_read": "Warm: property read",
    "test_bench_warm_cached_property_first": "Warm: cached_property 1st",
    "test_bench_warm_cached_property_second": "Warm: cached_property 2nd",
    "test_bench_conda_init": "conda init (with file)",
    "test_bench_conda_field_first_access": "conda: field 1st access",
    "test_bench_conda_field_second_access": "conda: field 2nd access",
}

# Colour scheme
_COLOR_CONDA_CONTEXT = "#4C78A8"  # steel blue
_COLOR_CONDA_REF = "#F58518"  # orange
_COLOR_CONDA_CONTEXT_BOX = "rgba(76,120,168,0.6)"
_COLOR_CONDA_REF_BOX = "rgba(245,133,24,0.6)"

# ---------------------------------------------------------------------------
# Data loading and parsing
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict[str, Any]:
    """Load and validate the pytest-benchmark JSON file."""
    try:
        with path.open() as fh:
            data = json.load(fh)
    except FileNotFoundError:
        print(f"ERROR: File not found: {path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(f"ERROR: Invalid JSON in {path}: {exc}", file=sys.stderr)
        sys.exit(1)

    if "benchmarks" not in data:
        print(
            f"ERROR: {path} does not look like a pytest-benchmark JSON file "
            "(missing 'benchmarks' key).",
            file=sys.stderr,
        )
        sys.exit(1)
    return data


def _strip_node_id(name: str) -> str:
    """Strip pytest node-id prefix if present (e.g. 'tests/test_benchmarks.py::')."""
    if "::" in name:
        name = name.split("::")[-1]
    return name


def _parse_benchmarks(data: dict) -> tuple[dict, dict]:
    """
    Split benchmarks into conda-context and conda-reference groups.

    Returns
    -------
    cc_benchmarks : dict[scenario_key, benchmark_entry]
        conda-context benchmarks, keyed by the bare function name.
    conda_benchmarks : dict[scenario_key, benchmark_entry]
        conda reference benchmarks, keyed by the bare function name.
        The keys are mapped so that "test_bench_conda_init" → "test_bench_conda_init"
        (kept as-is for matching logic in the narrative).
    """
    cc: dict[str, Any] = {}
    conda_ref: dict[str, Any] = {}

    for entry in data["benchmarks"]:
        raw_name = entry.get("name", "")
        name = _strip_node_id(raw_name)
        if name.startswith(_CONDA_PREFIX):
            conda_ref[name] = entry
        else:
            cc[name] = entry

    return cc, conda_ref


def _us(seconds: float) -> float:
    """Convert seconds to microseconds."""
    return seconds * 1_000_000


def _mean_us(entry: dict) -> float:
    return _us(entry["stats"]["mean"])


def _stddev_us(entry: dict) -> float:
    return _us(entry["stats"]["stddev"])


def _rounds(entry: dict) -> list[float]:
    """Per-round times in microseconds."""
    return [_us(t) for t in entry["stats"]["data"]]


def _label(name: str) -> str:
    return _SCENARIO_LABELS.get(name, name)


# ---------------------------------------------------------------------------
# Figure 1: Grouped bar chart (mean ± stddev)
# ---------------------------------------------------------------------------


def _make_bar_chart(cc: dict, conda_ref: dict) -> go.Figure:
    """Grouped bar chart: conda-context and conda side-by-side per scenario."""
    # Collect all scenarios that appear in at least one group, in a stable order.
    all_keys = list(dict.fromkeys(list(cc.keys()) + list(conda_ref.keys())))
    labels = [_label(k) for k in all_keys]

    cc_means = [_mean_us(cc[k]) if k in cc else None for k in all_keys]
    cc_errs = [_stddev_us(cc[k]) if k in cc else None for k in all_keys]

    conda_means = [_mean_us(conda_ref[k]) if k in conda_ref else None for k in all_keys]
    conda_errs = [_stddev_us(conda_ref[k]) if k in conda_ref else None for k in all_keys]

    traces = [
        go.Bar(
            name="conda-context (this impl)",
            x=labels,
            y=cc_means,
            error_y=dict(type="data", array=cc_errs, visible=True),
            marker_color=_COLOR_CONDA_CONTEXT,
            text=[f"{v:.1f} µs" if v is not None else "" for v in cc_means],
            textposition="outside",
        ),
    ]
    if any(v is not None for v in conda_means):
        traces.append(
            go.Bar(
                name="conda (reference)",
                x=labels,
                y=conda_means,
                error_y=dict(type="data", array=conda_errs, visible=True),
                marker_color=_COLOR_CONDA_REF,
                text=[f"{v:.1f} µs" if v is not None else "" for v in conda_means],
                textposition="outside",
            )
        )

    fig = go.Figure(data=traces)
    fig.update_layout(
        barmode="group",
        title="Mean Execution Time by Scenario (lower is better)",
        xaxis_title="Benchmark Scenario",
        yaxis_title="Mean time (µs)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        template="plotly_white",
        height=520,
        margin=dict(t=80, b=160),
        xaxis=dict(tickangle=-35),
    )
    if not any(v is not None for v in conda_means):
        fig.add_annotation(
            text="conda reference data not available (conda not installed during benchmark run)",
            xref="paper",
            yref="paper",
            x=0.5,
            y=-0.28,
            showarrow=False,
            font=dict(size=11, color="grey"),
        )
    return fig


# ---------------------------------------------------------------------------
# Figure 2: Box plots (per-round distributions)
# ---------------------------------------------------------------------------


def _make_box_plots(cc: dict, conda_ref: dict) -> go.Figure:
    """Side-by-side box plots showing per-round timing distributions."""
    all_keys = list(dict.fromkeys(list(cc.keys()) + list(conda_ref.keys())))
    labels = [_label(k) for k in all_keys]

    traces = []
    for k, lbl in zip(all_keys, labels, strict=False):
        if k in cc:
            traces.append(
                go.Box(
                    y=_rounds(cc[k]),
                    name=lbl,
                    legendgroup="conda-context",
                    legendgrouptitle_text="conda-context",
                    showlegend=(k == list(cc.keys())[0]),
                    marker_color=_COLOR_CONDA_CONTEXT_BOX,
                    line_color=_COLOR_CONDA_CONTEXT,
                    boxmean="sd",
                    offsetgroup="conda-context",
                    alignmentgroup=lbl,
                )
            )
        if k in conda_ref:
            traces.append(
                go.Box(
                    y=_rounds(conda_ref[k]),
                    name=lbl,
                    legendgroup="conda-ref",
                    legendgrouptitle_text="conda (reference)",
                    showlegend=(k == list(conda_ref.keys())[0]),
                    marker_color=_COLOR_CONDA_REF_BOX,
                    line_color=_COLOR_CONDA_REF,
                    boxmean="sd",
                    offsetgroup="conda-ref",
                    alignmentgroup=lbl,
                )
            )

    fig = go.Figure(data=traces)
    fig.update_layout(
        title="Per-Round Timing Distribution by Scenario",
        xaxis_title="Benchmark Scenario",
        yaxis_title="Time per round (µs)",
        boxmode="group",
        template="plotly_white",
        height=520,
        margin=dict(t=80, b=160),
        xaxis=dict(tickangle=-35),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


# ---------------------------------------------------------------------------
# Figure 3: Summary table
# ---------------------------------------------------------------------------


def _make_summary_table(cc: dict, conda_ref: dict) -> go.Figure:
    """Sortable Plotly table with mean, stddev, and ratio columns."""
    all_keys = list(dict.fromkeys(list(cc.keys()) + list(conda_ref.keys())))

    rows: list[tuple] = []
    for k in all_keys:
        lbl = _label(k)
        cc_mean = _mean_us(cc[k]) if k in cc else None
        cc_std = _stddev_us(cc[k]) if k in cc else None
        ref_mean = _mean_us(conda_ref[k]) if k in conda_ref else None
        ref_std = _stddev_us(conda_ref[k]) if k in conda_ref else None

        if cc_mean is not None and ref_mean is not None:
            ratio = ref_mean / cc_mean
            ratio_str = f"{ratio:.2f}×"
            if ratio > 1:
                ratio_str += " (conda slower)"
            elif ratio < 1:
                ratio_str += " (conda faster)"
            else:
                ratio_str += " (equal)"
        else:
            ratio_str = "N/A"

        rows.append(
            (
                lbl,
                f"{cc_mean:.2f}" if cc_mean is not None else "N/A",
                f"{cc_std:.2f}" if cc_std is not None else "N/A",
                f"{ref_mean:.2f}" if ref_mean is not None else "N/A",
                f"{ref_std:.2f}" if ref_std is not None else "N/A",
                ratio_str,
            )
        )

    cols = list(zip(*rows, strict=False)) if rows else [[], [], [], [], [], []]

    fig = go.Figure(
        data=[
            go.Table(
                header=dict(
                    values=[
                        "<b>Scenario</b>",
                        "<b>cc mean (µs)</b>",
                        "<b>cc stddev (µs)</b>",
                        "<b>conda mean (µs)</b>",
                        "<b>conda stddev (µs)</b>",
                        "<b>Ratio (conda/cc)</b>",
                    ],
                    fill_color="#4C78A8",
                    font=dict(color="white", size=12),
                    align="left",
                    height=32,
                ),
                cells=dict(
                    values=list(cols),
                    fill_color=[["#f0f4fa" if i % 2 == 0 else "white" for i in range(len(rows))]]
                    * 6,
                    align="left",
                    height=28,
                    font=dict(size=11),
                ),
            )
        ]
    )
    fig.update_layout(
        title="Summary: Mean Execution Times and Ratios",
        template="plotly_white",
        height=max(300, 60 + 30 * len(rows)),
        margin=dict(t=60, b=20),
    )
    return fig


# ---------------------------------------------------------------------------
# Narrative interpretation
# ---------------------------------------------------------------------------


def _make_narrative(cc: dict, conda_ref: dict, title: str) -> str:
    """Generate HTML prose section with key findings derived from the data."""
    lines: list[str] = []

    def _h3(text: str) -> None:
        lines.append(f"<h3>{text}</h3>")

    def _p(text: str) -> None:
        lines.append(f"<p>{text}</p>")

    def _fmt(us: float) -> str:
        if us >= 1000:
            return f"{us / 1000:.2f} ms"
        return f"{us:.1f} µs"

    _h3("Key Findings")

    # 1. Largest absolute cost scenario (conda-context)
    if cc:
        worst_key = max(cc, key=lambda k: _mean_us(cc[k]))
        worst_mean = _mean_us(cc[worst_key])
        _p(
            f"<strong>Most expensive scenario (conda-context):</strong> "
            f"<code>{_label(worst_key)}</code> at <strong>{_fmt(worst_mean)}</strong> mean."
        )

    # 2. Triple-rebuild overhead
    init_key = "test_bench_context_init_empty"
    rebuild_key = "test_bench_single_rebuild_empty"
    if init_key in cc and rebuild_key in cc:
        init_mean = _mean_us(cc[init_key])
        rebuild_mean = _mean_us(cc[rebuild_key])
        expected_triple = rebuild_mean * 3
        overhead_pct = (
            ((init_mean - expected_triple) / expected_triple * 100) if expected_triple > 0 else 0
        )
        ratio = init_mean / rebuild_mean if rebuild_mean > 0 else 0
        _p(
            f"<strong>Triple-rebuild overhead:</strong> "
            f"<code>Context.__init__</code> takes <strong>{_fmt(init_mean)}</strong> "
            f"({ratio:.1f}× a single <code>_rebuild()</code> at {_fmt(rebuild_mean)}). "
            f"Since <code>__init__</code> calls <code>_rebuild()</code> three times, the "
            f"theoretical minimum is 3× = {_fmt(expected_triple)}; "
            f"observed overhead above that is {overhead_pct:+.0f}%."
        )

    # 3. Cold init comparison (conda-context vs conda)
    conda_init_key = "test_bench_conda_init"
    cc_init_key = "test_bench_context_init_with_file"
    if cc_init_key in cc and conda_init_key in conda_ref:
        cc_val = _mean_us(cc[cc_init_key])
        conda_val = _mean_us(conda_ref[conda_init_key])
        ratio = conda_val / cc_val if cc_val > 0 else 0
        if ratio >= 1:
            comparison = (
                f"conda's init is <strong>{ratio:.2f}×</strong> slower than conda-context's"
            )
        else:
            comparison = (
                f"conda's init is <strong>{1 / ratio:.2f}×</strong> faster than conda-context's"
            )
        _p(
            f"<strong>Cold init comparison:</strong> conda-context init (with file) = "
            f"{_fmt(cc_val)}; conda init (with file) = {_fmt(conda_val)}. "
            f"{comparison}."
        )

    # 4. Warm vs cold access ratio (conda-context)
    warm_key = "test_bench_warm_property_read"
    cold_key = "test_bench_context_init_empty"
    if warm_key in cc and cold_key in cc:
        warm_val = _mean_us(cc[warm_key])
        cold_val = _mean_us(cc[cold_key])
        speedup = cold_val / warm_val if warm_val > 0 else 0
        _p(
            f"<strong>Warm vs cold access (conda-context):</strong> "
            f"A plain property read (<code>ctx.ssl_verify</code>) costs {_fmt(warm_val)}, "
            f"which is <strong>{speedup:.0f}×</strong> faster than a full cold init "
            f"({_fmt(cold_val)}). The eager-load cost is paid once at construction time."
        )

    # 5. Conda lazy vs cached field access
    conda_first_key = "test_bench_conda_field_first_access"
    conda_second_key = "test_bench_conda_field_second_access"
    if conda_first_key in conda_ref and conda_second_key in conda_ref:
        first_val = _mean_us(conda_ref[conda_first_key])
        second_val = _mean_us(conda_ref[conda_second_key])
        speedup = first_val / second_val if second_val > 0 else 0
        _p(
            f"<strong>conda lazy-load cost:</strong> First access to "
            f"<code>ssl_verify</code> on a conda Context costs {_fmt(first_val)} "
            f"(field parse + cache write); the second access costs {_fmt(second_val)} "
            f"({speedup:.0f}× faster, direct <code>_cache_</code> dict lookup)."
        )

    # 6. Pydantic cost breakdown
    pyd_empty_key = "test_bench_pydantic_empty"
    pyd_full_key = "test_bench_pydantic_full_merged"
    if pyd_empty_key in cc and pyd_full_key in cc:
        empty_val = _mean_us(cc[pyd_empty_key])
        full_val = _mean_us(cc[pyd_full_key])
        _p(
            f"<strong>Pydantic model construction:</strong> "
            f"<code>CondaConfig()</code> with defaults costs {_fmt(empty_val)}; "
            f"with a full merged dict it costs {_fmt(full_val)}. "
            f"This cost is paid on every <code>_rebuild()</code> call."
        )

    if not lines:
        _p("No benchmark data found to interpret.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML assembly
# ---------------------------------------------------------------------------

_SORTABLE_JS = """
<script>
function sortTable(table, col, asc) {
  const tbody = table.querySelector('tbody');
  const rows = Array.from(tbody.querySelectorAll('tr'));
  rows.sort((a, b) => {
    const av = a.cells[col].textContent.trim();
    const bv = b.cells[col].textContent.trim();
    const an = parseFloat(av), bn = parseFloat(bv);
    if (!isNaN(an) && !isNaN(bn)) return asc ? an - bn : bn - an;
    return asc ? av.localeCompare(bv) : bv.localeCompare(av);
  });
  rows.forEach(r => tbody.appendChild(r));
}
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('table.sortable thead th').forEach((th, i) => {
    let asc = true;
    th.style.cursor = 'pointer';
    th.title = 'Click to sort';
    th.addEventListener('click', () => {
      sortTable(th.closest('table'), i, asc);
      asc = !asc;
    });
  });
});
</script>
"""

_HTML_STYLE = """
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         max-width: 1200px; margin: 0 auto; padding: 2rem; color: #222; }
  h1 { color: #2c3e50; border-bottom: 2px solid #4C78A8; padding-bottom: .4rem; }
  h2 { color: #34495e; margin-top: 2.5rem; }
  h3 { color: #4C78A8; }
  p  { line-height: 1.65; max-width: 85ch; }
  .narrative { background: #f8f9fa; border-left: 4px solid #4C78A8;
               padding: 1rem 1.5rem; border-radius: 0 6px 6px 0; margin: 1.5rem 0; }
  .meta { font-size: .85rem; color: #666; margin-bottom: 2rem; }
  code { background: #eef2f7; padding: .1em .35em; border-radius: 3px; font-size: .9em; }
  footer { margin-top: 3rem; font-size: .8rem; color: #999; text-align: center; }
</style>
"""


def _assemble_html(
    fig_bar: go.Figure,
    fig_box: go.Figure,
    fig_table: go.Figure,
    narrative_html: str,
    title: str,
    source_file: str,
) -> str:
    """Render all figures + narrative into a single self-contained HTML string."""

    def _fig_html(fig: go.Figure, div_id: str) -> str:
        # full=False → we get just the div + inline script, no outer HTML wrapper.
        # include_plotlyjs handled once at the top level.
        return pio.to_html(
            fig,
            full_html=False,
            include_plotlyjs=False,
            div_id=div_id,
        )

    # Render Plotly JS bundle once (this is the self-contained blob, ~3 MB).
    # pio.to_html with include_plotlyjs=True embeds the full minified bundle as
    # inline <script> blocks.  We extract the config block + library bundle
    # (the first two <script> tags) so they can be placed in <head> once.
    plotly_js_tag = pio.to_html(
        go.Figure(),
        full_html=False,
        include_plotlyjs=True,
    )
    import re as _re

    scripts = _re.findall(r"(<script\b[^>]*>.*?</script>)", plotly_js_tag, _re.DOTALL)
    # scripts[0]: PlotlyConfig block  (~64 bytes)
    # scripts[1]: plotly.js bundle    (~4.8 MB)
    # scripts[2]: figure-specific JS  (skip — it references the dummy figure div)
    if len(scripts) >= 2:
        plotly_bundle = scripts[0] + "\n" + scripts[1]
    elif scripts:
        plotly_bundle = scripts[0]
    else:
        # Should not happen with any modern Plotly version, but keep as a
        # safety net so the output remains functional (just requires internet).
        plotly_bundle = '<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>'

    bar_html = _fig_html(fig_bar, "fig-bar")
    box_html = _fig_html(fig_box, "fig-box")
    table_html = _fig_html(fig_table, "fig-table")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  {_HTML_STYLE}
  {plotly_bundle}
  {_SORTABLE_JS}
</head>
<body>
  <h1>{title}</h1>
  <p class="meta">Generated from: <code>{source_file}</code></p>

  <h2>Interpretation</h2>
  <div class="narrative">
    {narrative_html}
  </div>

  <h2>Mean Execution Time (Grouped Bar Chart)</h2>
  <p>
    Each bar shows the <strong>mean</strong> execution time in microseconds (µs) over all
    benchmark rounds. Error bars represent ±1 standard deviation. Lower is better.
  </p>
  {bar_html}

  <h2>Per-Round Distribution (Box Plots)</h2>
  <p>
    Box plots show the spread of individual round times. The box spans the
    interquartile range (25th–75th percentile); the line inside is the median;
    whiskers extend to 1.5×IQR; dots are outliers. The diamond marker shows the mean.
  </p>
  {box_html}

  <h2>Summary Table</h2>
  <p>
    All times in microseconds (µs). The <em>Ratio</em> column is
    <code>conda mean / conda-context mean</code>: values above 1.0 mean conda is slower.
  </p>
  {table_html}

  <footer>
    Generated by <code>scripts/generate_benchmark_report.py</code> &mdash;
    conda-context benchmarking suite
  </footer>
</body>
</html>"""


# ---------------------------------------------------------------------------
# URL safety check
# ---------------------------------------------------------------------------


def _check_no_external_urls(html: str) -> list[str]:
    """Return any external http/https URLs found in resource-loading attributes.

    Only checks HTML markup (outside <script> and <style> blocks) for src= and
    href= attributes that would trigger a network request.  URLs embedded as
    plain text inside the inlined Plotly JS bundle are intentionally ignored —
    they are attribution strings in map-tile providers and are never fetched.
    """
    # Strip all <script>...</script> and <style>...</style> blocks before
    # scanning for resource-loading attributes.
    stripped = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    stripped = re.sub(r"<style\b[^>]*>.*?</style>", "", stripped, flags=re.DOTALL)

    external: list[str] = []
    for match in re.finditer(r'\b(?:src|href)=["\']?(https?://[^"\'>\s]+)', stripped):
        url = match.group(1)
        external.append(url)
    return external


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "json_path",
        metavar="JSON_FILE",
        type=Path,
        help="Path to the pytest-benchmark JSON output file.",
    )
    parser.add_argument(
        "--output",
        "-o",
        metavar="HTML_FILE",
        type=Path,
        default=Path("benchmark_report.html"),
        help="Path for the generated HTML report (default: benchmark_report.html).",
    )
    parser.add_argument(
        "--title",
        metavar="TITLE",
        default="conda-context Benchmark Report",
        help="Report title shown in the browser tab and page heading.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    print(f"Loading benchmark data from: {args.json_path}")
    data = _load_json(args.json_path)

    n = len(data["benchmarks"])
    print(f"Found {n} benchmark(s).")

    cc, conda_ref = _parse_benchmarks(data)
    print(f"  conda-context benchmarks : {len(cc)}\n  conda reference benchmarks: {len(conda_ref)}")

    if not cc and not conda_ref:
        print("ERROR: No recognisable benchmark entries found.", file=sys.stderr)
        return 1

    print("Building figures...")
    fig_bar = _make_bar_chart(cc, conda_ref)
    fig_box = _make_box_plots(cc, conda_ref)
    fig_table = _make_summary_table(cc, conda_ref)

    print("Writing narrative...")
    narrative = _make_narrative(cc, conda_ref, args.title)

    print("Assembling HTML...")
    html = _assemble_html(
        fig_bar,
        fig_box,
        fig_table,
        narrative,
        title=args.title,
        source_file=str(args.json_path),
    )

    # Safety check: no external URLs
    external = _check_no_external_urls(html)
    if external:
        print(
            "WARNING: The following external URLs were found in the output HTML.\n"
            "The report may not render offline:\n" + "\n".join(f"  {u}" for u in external),
            file=sys.stderr,
        )

    args.output.write_text(html, encoding="utf-8")
    size_kb = args.output.stat().st_size / 1024
    print(f"Report written to: {args.output}  ({size_kb:.0f} KB)")
