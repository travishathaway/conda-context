## ADDED Requirements

### Requirement: Report generator script exists and accepts CLI arguments
A script `scripts/generate_benchmark_report.py` SHALL exist and be runnable directly with `python scripts/generate_benchmark_report.py`.
The script SHALL accept:
- A positional argument: path to a pytest-benchmark JSON output file.
- `--output` / `-o`: path for the generated HTML file (default: `benchmark_report.html`).
- `--title`: optional report title string (default: `"conda-context Benchmark Report"`).

#### Scenario: Script prints usage on --help
- **WHEN** the user runs `python scripts/generate_benchmark_report.py --help`
- **THEN** usage information is printed including the positional argument and all optional flags

#### Scenario: Script errors with missing input file
- **WHEN** the user runs the script with a path that does not exist
- **THEN** the script exits with a non-zero exit code and a human-readable error message

### Requirement: Report generator produces a self-contained HTML file
The generated HTML file SHALL be self-contained: it SHALL NOT reference any external URLs (no CDN links, no external fonts, no external images).
All JavaScript (Plotly) SHALL be inlined into the HTML.

#### Scenario: Output file has no external references
- **WHEN** the HTML report is generated
- **THEN** the file contains no `src=` or `href=` attributes pointing to external URLs

#### Scenario: Output file renders without internet access
- **WHEN** the HTML file is opened in a browser with no internet connection
- **THEN** all charts render correctly

### Requirement: Report contains grouped bar chart comparing scenarios
The report SHALL include a grouped bar chart where:
- The x-axis shows benchmark scenario names (e.g., "context_init_empty", "merge_engine_with_file").
- Each bar group has two bars: one for `conda-context` (this implementation) and one for `conda` (the reference).
- The y-axis shows mean execution time in microseconds (µs).
- Each bar SHALL display an error bar representing one standard deviation.
- Conda reference bars SHALL be visually distinguished (different color).
- The chart title SHALL clearly label the comparison.

#### Scenario: Chart renders with only conda-context data
- **WHEN** the JSON file contains no conda reference benchmarks (e.g., conda was not available)
- **THEN** the chart renders with only the conda-context bars, with a note that conda reference data was unavailable

#### Scenario: Chart includes error bars
- **WHEN** benchmark JSON contains stddev values
- **THEN** error bars representing ±1 stddev are displayed on each bar

### Requirement: Report contains box plots for distribution visualization
The report SHALL include box plots showing the timing distribution for each benchmark scenario.
Each box plot SHALL show: median, IQR (25th–75th percentile), whiskers, and outlier points.
Box plots for `conda-context` and `conda` reference SHALL appear as side-by-side boxes within each scenario group.

#### Scenario: Box plots show timing distribution
- **WHEN** pytest-benchmark JSON contains per-round timing data
- **THEN** box plots display the spread of individual round times, not just the mean

### Requirement: Report contains a summary table
The report SHALL include an HTML table with one row per benchmark scenario containing:
- Scenario name
- conda-context mean (µs)
- conda-context stddev (µs)
- conda reference mean (µs) or "N/A" if not available
- Ratio (conda mean / conda-context mean) — "faster" if <1, "slower" if >1

#### Scenario: Summary table is sortable
- **WHEN** the HTML report is opened in a browser
- **THEN** clicking a column header sorts the table by that column

### Requirement: Report has a narrative interpretation section
The report SHALL include a human-readable prose section (generated from the benchmark data) that:
- Identifies which scenario has the largest absolute cost in this implementation.
- States the triple-rebuild overhead in `Context.__init__` (derived from comparing `bench_context_init_empty` to `3 × bench_single_rebuild_empty`).
- Compares cold init cost between the two implementations.
- Compares warm vs cold access costs.

#### Scenario: Interpretation section cites actual numbers
- **WHEN** the report is generated
- **THEN** the interpretation section contains numeric values derived from the benchmark data, not placeholder text

### Requirement: plotly declared as optional report dependency
`plotly>=5` SHALL be declared in `pyproject.toml` as an optional `[report]` extra.
The report script SHALL produce a clear error message if `plotly` is not installed, pointing the user to `pip install conda-context[report]`.

#### Scenario: Script fails gracefully without plotly
- **WHEN** `plotly` is not installed and the user runs the report script
- **THEN** the script prints a human-readable installation hint and exits with a non-zero code
