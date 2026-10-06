# PDF Reports

`report.py` creates an evidence-oriented PDF report directly from an Internet Monitor SQLite database.

## Usage

Standard report:

```bash
python3 report.py /path/to/monitor_YYYYMMDD_HHMMSS.db
```

Extended report:

```bash
python3 report.py -v /path/to/monitor_YYYYMMDD_HHMMSS.db
```

The `-v` option adds the full Speedtest result table.

## Output location

Reports are written to a `reports` directory beside the input database:

```text
<database-directory>/reports/<database-name>_report.pdf
```

For example:

```text
/opt/internet-monitor/reports/monitor_20261005_153301_report.pdf
```

## Report contents

The report is divided into several sections.

### Cover and Executive Summary

The first page contains:

- Internet Monitor branding
- monitoring period
- database name
- executive summary
- aggregate ICMP statistics
- confirmed event counts
- DNS success information
- HTTPS / DoH success information
- Speedtest summary

### ICMP Connectivity

This section contains a target-level table and, when sufficient data is available, an average latency graph.

### Confirmed Connectivity Events

Target connectivity-loss intervals and non-NORMAL Internet-state intervals are presented separately.

Only closed intervals are treated as confirmed duration intervals. Events that remain open at database end are explicitly excluded from confirmed duration totals.

### DNS Monitoring

The report summarizes configured DNS checks by target and includes success rates.

### HTTPS / DoH Monitoring

The report summarizes HTTPS and DoH checks, including success rate and recorded response timing where available.

### Speedtest Analysis

The report includes successful Speedtest counts, throughput ranges and graphs for:

- download/upload throughput
- idle latency/jitter

The complete Speedtest table is included only when `-v` is used.

### Technical Observations

The final section provides a concise interpretation of the measured data and explicitly states the limitations of causal inference.

## SVG logo

`report.py` expects the SVG logo at:

```text
<directory containing report.py>/imlogo.svg
```

The logo is rendered as vector graphics on the report cover and in page footers.

If the logo is missing, PDF generation stops with an error.

## UTC handling

The report labels measurement timestamps as UTC. The report does not attempt to reinterpret the stored measurement clock time as another timezone.

## Temporary graph files

Charts are generated as temporary PNG files during report creation. They are stored in a temporary directory and removed automatically when report generation finishes.
