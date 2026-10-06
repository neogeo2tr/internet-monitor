# Internet Monitor

A lightweight Linux-based Internet connectivity monitoring system that continuously records network measurements in SQLite and provides command-line analysis and PDF reporting.

The project is designed for long-running monitoring of an Internet connection. It combines several independent measurement methods so that connectivity problems can be observed from different angles rather than relying on a single ping test.

## Features

- ICMP monitoring of the local gateway and external Internet targets
- Packet-loss and latency measurements
- Direct DNS resolution tests against configured DNS resolvers
- HTTPS availability checks
- DNS-over-HTTPS (DoH) checks
- Automatic MTR diagnostics after relevant connectivity problems
- Periodic Speedtest measurements
- Internet and target state tracking
- Event recording and event correlation
- SQLite database storage
- Human-readable command-line analysis
- PDF reports with tables and graphs
- Optional automated report generation and e-mail delivery
- systemd service support for continuous monitoring

## Architecture

```text
                         +----------------------+
                         |     monitor.py       |
                         | Continuous monitoring|
                         +----------+-----------+
                                    |
                                    v
                         +----------------------+
                         |      SQLite DB        |
                         | measurements/events   |
                         +----+-------------+----+
                              |             |
                    +---------+             +----------+
                    v                                   v
             +-------------+                      +-------------+
             | analyze.py  |                      |  report.py  |
             | CLI analysis|                      |  PDF report |
             +-------------+                      +-------------+
                                                       |
                                                       v
                                                 PDF report
                                                       |
                                                       v
                                             emailreport.sh
```

## Main Components

| File | Purpose |
|---|---|
| `monitor.py` | Main monitoring daemon. Performs measurements and writes the SQLite database. |
| `analyze.py` | Reads a monitoring database and produces a detailed command-line analysis. |
| `report.py` | Generates an evidence-oriented PDF report from a monitoring database. |
| `emailreport.sh` | Finds the newest database, generates the report, runs the analysis and sends the PDF by e-mail. |
| `imlogo.svg` | SVG logo used by the PDF report. This file must be present beside `report.py` when reports are generated. |

## Requirements

The project is intended for Linux. The current configuration uses `/opt/internet-monitor` as its installation directory.

### Python

Python 3 is required.

Python packages used by the project:

```text
matplotlib
reportlab
svglib
```

SQLite is provided by Python's standard library.

### System utilities

`monitor.py` invokes the following external commands:

- `ping`
- `curl`
- `mtr`
- `speedtest`

These utilities must be installed and available in `PATH`.

The e-mail helper additionally requires:

- `sendmail`
- `base64`
- standard POSIX shell utilities such as `find`, `sort`, `head`, `cut`, `basename` and `du`

## Installation

See [`docs/INSTALLATION.md`](docs/INSTALLATION.md) for a complete installation example.

A typical installation directory is:

```text
/opt/internet-monitor/
├── monitor.py
├── analyze.py
├── report.py
├── emailreport.sh
├── imlogo.svg
└── reports/
```

The `reports/` directory is created automatically by `report.py` when needed.

## Quick Start

### 1. Start the monitor manually

```bash
cd /opt/internet-monitor
python3 monitor.py
```

The monitor creates a new SQLite database for the monitoring run and continuously records measurements.

### 2. Analyze a database

```bash
python3 analyze.py /opt/internet-monitor/monitor_YYYYMMDD_HHMMSS.db
```

The analyzer reports database contents, monitoring period, ICMP statistics, DNS and HTTPS/DoH results, Speedtest data, MTR information and correlated connectivity events.

### 3. Generate a PDF report

```bash
python3 report.py /opt/internet-monitor/monitor_YYYYMMDD_HHMMSS.db
```

The PDF is written to:

```text
/opt/internet-monitor/reports/monitor_YYYYMMDD_HHMMSS_report.pdf
```

For the extended Speedtest result table, use:

```bash
python3 report.py -v /opt/internet-monitor/monitor_YYYYMMDD_HHMMSS.db
```

### 4. Run as a systemd service

The supplied service file is configured for:

```text
User=your user name
WorkingDirectory=/opt/internet-monitor
ExecStart=/usr/bin/python3 /opt/internet-monitor/monitor.py
```

Adjust these values to match the target system before installing the service. See example: internet-monitor.service

Typical commands are:

```bash
sudo cp internet-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now internet-monitor.service
```

Check the service with:

```bash
systemctl status internet-monitor.service
```

Follow the live log with:

```bash
journalctl -u internet-monitor.service -f
```

## Monitoring Configuration

The main configuration is currently located directly in `monitor.py`.

Default measurement intervals are:

| Measurement | Default |
|---|---:|
| ICMP interval | 5 seconds |
| ICMP probes per cycle | 3 |
| ICMP timeout | 1 second |
| DNS interval | 30 seconds |
| DNS timeout | 3 seconds |
| HTTPS / DoH interval | 30 seconds |
| HTTPS / DoH timeout | 15 seconds |
| MTR probes | 5 |
| MTR cooldown | 300 seconds |
| MTR timeout | 60 seconds |
| Speedtest interval | 300 seconds |
| Speedtest timeout | 180 seconds |

The default ICMP targets are:

- Local gateway: `192.168.0.1`
- Cloudflare: `1.1.1.1`
- Google: `8.8.8.8`
- Quad9: `9.9.9.9`

Direct DNS checks use Cloudflare, Google and Quad9 resolvers. HTTPS checks use Cloudflare and Google, while Quad9 is tested through its DNS-over-HTTPS endpoint.

See [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) for details.

## Database

Each monitoring run uses a SQLite database. The database contains separate tables for the principal measurement types and recorded events.

Current measurement tables include:

- `ping_measurements`
- `dns_measurements`
- `https_measurements`
- `speedtest_measurements`
- `events`

The database is the primary source for both `analyze.py` and `report.py`.

## Event Interpretation

The monitor maintains state for Internet targets and the overall Internet connection. Events are recorded when monitored states change.

The analysis and report tools distinguish between confirmed closed intervals and events that are still open when the database ends. Open events are not included in confirmed duration totals.

This distinction is intentional: a database may represent an active monitoring run, so the latest problem can still be in progress.

## Reports

The PDF report contains, depending on available data:

- monitoring period
- database identification
- executive summary
- aggregate Internet ICMP loss and availability
- target-level ICMP statistics
- ICMP latency graph
- confirmed target connectivity events
- confirmed Internet-state events
- DNS summary
- HTTPS / DoH summary
- Speedtest analysis
- Speedtest throughput graph
- Speedtest latency/jitter graph
- optional full Speedtest results table with `-v`
- technical observations
- data-source statement

See [`docs/REPORTS.md`](docs/REPORTS.md) for details.

## Automated Reporting

`emailreport.sh` automates the reporting workflow:

1. Find the newest `monitor_*.db` file.
2. Generate the PDF report.
3. Verify that the PDF was created.
4. Run `analyze.py` for the selected database.
5. Send the analysis and PDF as an e-mail.
6. Report whether `sendmail` accepted the message.

The script currently contains a local e-mail address and should therefore be reviewed before committing it to a public repository. The recipient should be made configurable for a public deployment.

## Data and Evidence

The project is intended to provide measurements and evidence about observed connectivity behavior. It does not attempt to prove the root cause of an outage.

For example, packet loss to Internet targets can demonstrate that probes failed during a period, but that observation alone cannot determine whether the cause was the local network, an upstream network, routing, the destination, or an Internet service provider.

The same principle applies to DNS, HTTPS/DoH and Speedtest results.

## Version Information

Current component versions in the supplied source are:

- Monitor: `v1.0`
- Analyzer: `v1.0`
- Report generator: `v1.0`

## Status

This project is a practical monitoring system developed for real-world continuous Internet connectivity observation. Configuration values and external dependencies are intentionally straightforward and can be adapted to the target Linux environment.

## License

Internet Monitor is released under the MIT License.

See the LICENSE file for the complete license text.

In short, the MIT License permits:

private use
commercial use
modification
distribution
sublicensing

provided that the original copyright and license notice are retained.

## Contributing

Contributions, bug reports and suggestions are welcome.

When reporting a problem, please provide where possible:

Linux distribution and version
Python version
monitor version
report generator version
relevant error message
relevant log output
steps required to reproduce the problem

Please do not publish private network information, credentials, email addresses or other sensitive data in public issue reports.


## Author

Internet Monitor

Copyright (c) 2026 Roland Tokaji

Licensed under the MIT License.
