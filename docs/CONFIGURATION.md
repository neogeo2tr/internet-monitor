# Configuration

The current project keeps its monitoring configuration directly in `monitor.py`. There is no separate configuration file in the supplied version.

## Application directory

```python
BASE_DIR = "/opt/internet-monitor"
```

This directory is used for the monitoring database and is also referenced by the supplied systemd service and e-mail helper.

## ICMP monitoring

Default settings:

```python
PING_INTERVAL = 5
PING_COUNT = 3
PING_TIMEOUT = 1
```

Default targets:

```text
192.168.0.1  Local gateway
1.1.1.1     Cloudflare
8.8.8.8     Google
9.9.9.9     Quad9
```

The gateway is tracked separately from the external Internet targets. The aggregate Internet ICMP statistics exclude the gateway.

## DNS monitoring

Default interval and timeout:

```python
DNS_INTERVAL = 30
DNS_TIMEOUT = 3
```

Configured resolvers:

| Name | Resolver | Test hostname |
|---|---|---|
| Cloudflare | `1.1.1.1` | `example.com` |
| Google | `8.8.8.8` | `example.com` |
| Quad9 | `9.9.9.9` | `example.com` |

These checks test direct DNS resolution rather than relying on the operating system's normal resolver path.

## HTTPS and DoH monitoring

Default settings:

```python
HTTPS_INTERVAL = 30
HTTPS_TIMEOUT = 15
```

Configured endpoints include:

- Cloudflare HTTPS
- Google HTTPS
- Quad9 DNS-over-HTTPS

The monitor records the result and response timing information where available.

## MTR diagnostics

Default settings:

```python
MTR_COUNT = 5
MTR_COOLDOWN = 300
MTR_TIMEOUT = 60
```

MTR is used as a diagnostic measurement rather than as a continuous high-frequency test. The cooldown prevents repeated diagnostics from being launched too frequently during persistent problems.

## Speedtest

Default settings:

```python
SPEEDTEST_INTERVAL = 300
SPEEDTEST_TIMEOUT = 180
```

A successful Speedtest records throughput and latency-related values in the SQLite database. Failed runs are retained as measurement records where applicable.

## State handling

The monitor maintains target-level states and an overall Internet state. The normal overall state is:

```text
NORMAL
```

Other state values are used internally to represent degraded or failed conditions. These values are part of the program's logic and should not be renamed casually because the analyzer and report generator interpret them.

## Changing targets

Targets are defined in `monitor.py`. If you change them, also consider whether the corresponding entries should remain part of the Internet aggregate and whether the new endpoints are suitable for long-term monitoring.

For public or production deployments, avoid using endpoints that prohibit automated monitoring.

## systemd configuration

The supplied service assumes:

```text
User=your user name
WorkingDirectory=/opt/internet-monitor
ExecStart=/usr/bin/python3 /opt/internet-monitor/monitor.py
```

These values are deployment-specific and should be changed when installing on another machine.

## E-mail configuration

`emailreport.sh` currently contains a hard-coded recipient:

```bash
MAIL_TO="..."
```

For a public repository, replace this with a configurable mechanism before publishing the script.
