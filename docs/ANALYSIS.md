# Analysis

`analyze.py` reads a monitoring SQLite database and produces a command-line report intended for technical review.

## Usage

```bash
python3 analyze.py /path/to/monitor_YYYYMMDD_HHMMSS.db
```

The script also recognizes `-v`:

```bash
python3 analyze.py -v /path/to/monitor_YYYYMMDD_HHMMSS.db
```

## Reported information

The analyzer covers the following areas:

### Database overview

- Database path
- Database size
- Available monitoring tables
- Record counts

### Monitoring period

- Start timestamp
- End timestamp
- Total duration

### ICMP summary

For configured targets, the analyzer reports packet counts, successful probes, packet loss, availability and latency-related values.

It also calculates an aggregate Internet ICMP view that excludes the local gateway.

### DNS summary

The analyzer summarizes the configured direct DNS checks and reports successful and failed tests.

### HTTPS / DoH summary

HTTPS and DNS-over-HTTPS results are summarized separately from direct DNS measurements.

### Speedtest

The analyzer reports recorded Speedtest runs and aggregate values for successful measurements.

### MTR

Recorded MTR diagnostic information is included where available.

### Event analysis

The analyzer reads the `events` table and identifies target-level and Internet-level state changes.

It correlates start and recovery events into intervals where possible.

This is important when interpreting the end of a monitoring database: an event may still be open because the monitoring run ended while the problem was active.

## Evidence-oriented interpretation

The analyzer deliberately treats measurements as observations rather than proof of root cause.

For example:

- packet loss proves that monitored probes were lost;
- DNS failures show that the monitored DNS test failed;
- HTTPS failures show that the monitored HTTP(S) request failed;
- Speedtest results show the performance measured by the selected Speedtest run;
- MTR shows the path information observed during the diagnostic.

None of these observations alone identifies the responsible network component or proves that an ISP caused an outage.
