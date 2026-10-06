# Installation

This document describes a typical Linux installation for Internet Monitor.

## 1. System packages

Install Python 3 and the external utilities required by `monitor.py`.

On Debian/Ubuntu-based systems, package names can vary by distribution. At minimum, the system needs working versions of:

- Python 3
- `ping`
- `curl`
- `mtr`
- `speedtest`
- `sendmail` (only for e-mail reporting)

Verify the commands after installation:

```bash
python3 --version
ping -V
curl --version
mtr --version
speedtest --version
```

The exact Speedtest package depends on the Speedtest client installed on the system.

## 2. Python packages

Install the Python dependencies:

```bash
python3 -m pip install matplotlib reportlab svglib
```

For a production installation, using a Python virtual environment is recommended.

## 3. Create the application directory

The supplied configuration uses:

```bash
sudo mkdir -p /opt/internet-monitor
```

Copy the project files into that directory:

```text
/opt/internet-monitor/
├── monitor.py
├── analyze.py
├── report.py
├── emailreport.sh
├── internet-monitor.service
├── imlogo.svg
└── reports/
```

`imlogo.svg` is required by `report.py`.

Make the scripts executable where appropriate:

```bash
sudo chmod +x /opt/internet-monitor/monitor.py
sudo chmod +x /opt/internet-monitor/analyze.py
sudo chmod +x /opt/internet-monitor/report.py
sudo chmod +x /opt/internet-monitor/emailreport.sh
```

## 4. Test the monitor manually

Before configuring systemd, run the monitor directly:

```bash
cd /opt/internet-monitor
python3 monitor.py
```

Verify that measurements are being produced and that a `monitor_*.db` file appears in the application directory.

Stop the monitor with `Ctrl+C`.

## 5. Test analysis

Use the database created by the monitor:

```bash
python3 analyze.py monitor_YYYYMMDD_HHMMSS.db
```

The analyzer should print the database overview, monitoring period and measurement summaries.

## 6. Test PDF generation

Generate a normal report:

```bash
python3 report.py monitor_YYYYMMDD_HHMMSS.db
```

Generate the extended report:

```bash
python3 report.py -v monitor_YYYYMMDD_HHMMSS.db
```

The resulting PDF is placed in `reports/`.

If PDF generation fails because of the logo, verify that `imlogo.svg` exists beside `report.py`.

## 7. Install the systemd service

Review `internet-monitor.service` before installing it. The supplied file contains the following system-specific settings:

```ini
User=roland
WorkingDirectory=/opt/internet-monitor
ExecStart=/usr/bin/python3 /opt/internet-monitor/monitor.py
```

Change them if the target username or installation directory is different.

Install the service:

```bash
sudo cp internet-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now internet-monitor.service
```

Check its status:

```bash
systemctl status internet-monitor.service
```

View logs:

```bash
journalctl -u internet-monitor.service
```

Follow the log live:

```bash
journalctl -u internet-monitor.service -f
```

## 8. E-mail reporting

Before using `emailreport.sh`, configure a working `sendmail` installation and review the recipient configuration in the script.

The script expects the application directory to be `/opt/internet-monitor` and searches that directory for the newest `monitor_*.db` database.

Do not publish a personal or production e-mail address in a public repository. Make the recipient configurable before committing the script publicly.
