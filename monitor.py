#!/usr/bin/env python3

import concurrent.futures
import datetime
import json
import os
import random
import re
import signal
import socket
import sqlite3
import subprocess
import tempfile
import threading
import time


# ============================================================
# INTERNET MONITOR V5.1
# ============================================================

VERSION = "V5.1"

BASE_DIR = "/opt/internet-monitor"

PING_INTERVAL = 5
PING_COUNT = 3
PING_TIMEOUT = 1

DNS_INTERVAL = 30
DNS_TIMEOUT = 3

HTTPS_INTERVAL = 30
HTTPS_TIMEOUT = 15

MTR_COUNT = 5
MTR_COOLDOWN = 300
MTR_TIMEOUT = 60

SPEEDTEST_INTERVAL = 300
SPEEDTEST_TIMEOUT = 180


# ============================================================
# PING TARGETS
# ============================================================

PING_TARGETS = {
    "gateway": "192.168.0.1",
    "cloudflare": "1.1.1.1",
    "google": "8.8.8.8",
    "quad9": "9.9.9.9",
}

INTERNET_TARGETS = [
    "cloudflare",
    "google",
    "quad9",
]


# ============================================================
# DIRECT DNS TARGETS
# ============================================================

DNS_TARGETS = {
    "cloudflare_dns": {
        "resolver_ip": "1.1.1.1",
        "hostname": "example.com",
    },

    "google_dns": {
        "resolver_ip": "8.8.8.8",
        "hostname": "example.com",
    },

    "quad9_dns": {
        "resolver_ip": "9.9.9.9",
        "hostname": "example.com",
    },
}


# ============================================================
# HTTPS TARGETS
# ============================================================

HTTPS_TARGETS = {
    "cloudflare_https": {
        "url": "https://www.cloudflare.com/",
        "type": "https",
    },

    "google_https": {
        "url": "https://www.google.com/",
        "type": "https",
    },

    "quad9_doh": {
        "url": "https://dns.quad9.net/dns-query",
        "type": "doh",
    },
}


# ============================================================
# GLOBAL STATE
# ============================================================

running = True

last_dns_check = 0.0
last_https_check = 0.0
last_mtr_time = 0.0

target_states = {
    name: "OK"
    for name in INTERNET_TARGETS
}

overall_state = "NORMAL"


# ============================================================
# TIME / LOGGING
# ============================================================

def utc_now():
    return datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat()


def local_now():
    return datetime.datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def log(message):
    print(
        f"[{local_now()}] {message}",
        flush=True
    )


def print_header(db_path):
    print()
    print("=" * 72)
    print(f" INTERNET MONITOR {VERSION}")
    print("=" * 72)
    print(f"Started:              {local_now()}")
    print(f"Database:             {db_path}")
    print(f"Ping interval:        {PING_INTERVAL} seconds")
    print(f"Ping count:           {PING_COUNT}")
    print(f"DNS interval:         {DNS_INTERVAL} seconds")
    print(f"HTTPS interval:       {HTTPS_INTERVAL} seconds")
    print(f"MTR cooldown:         {MTR_COOLDOWN} seconds")
    print(
        f"Speedtest interval:   "
        f"{SPEEDTEST_INTERVAL // 60} minutes"
    )
    print("=" * 72)
    print()


# ============================================================
# DATABASE
# ============================================================

def open_db(db_path):
    """
    Open a completely independent SQLite connection.

    IMPORTANT:
    Every worker thread gets its own connection.
    """

    return sqlite3.connect(
        db_path,
        timeout=30
    )


def create_database(db_path):

    conn = open_db(db_path)

    cur = conn.cursor()

    # --------------------------------------------------------
    # Ping
    # --------------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ping_measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle_id INTEGER NOT NULL,
            timestamp_utc TEXT NOT NULL,
            target_name TEXT NOT NULL,
            target_ip TEXT NOT NULL,
            ping_count INTEGER NOT NULL,
            success_count INTEGER NOT NULL,
            loss_percent REAL NOT NULL,
            min_ms REAL,
            avg_ms REAL,
            max_ms REAL,
            error TEXT
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_ping_timestamp
        ON ping_measurements(timestamp_utc)
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_ping_target
        ON ping_measurements(target_name)
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_ping_cycle
        ON ping_measurements(cycle_id)
    """)

    # --------------------------------------------------------
    # DNS
    # --------------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS dns_measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_utc TEXT NOT NULL,
            target_name TEXT NOT NULL,
            hostname TEXT NOT NULL,
            success INTEGER NOT NULL,
            resolved_ips TEXT,
            error TEXT
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_dns_timestamp
        ON dns_measurements(timestamp_utc)
    """)

    # --------------------------------------------------------
    # HTTPS / DoH
    # --------------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS https_measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_utc TEXT NOT NULL,
            target_name TEXT NOT NULL,
            url TEXT NOT NULL,
            success INTEGER NOT NULL,
            http_code INTEGER,
            time_total_ms REAL,
            error TEXT
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_https_timestamp
        ON https_measurements(timestamp_utc)
    """)

    # --------------------------------------------------------
    # Speedtest
    # --------------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS speedtest_measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_utc TEXT NOT NULL,

            server_id TEXT,
            server_name TEXT,
            server_location TEXT,
            server_country TEXT,

            isp TEXT,

            idle_latency_ms REAL,
            idle_jitter_ms REAL,
            idle_low_ms REAL,
            idle_high_ms REAL,

            download_mbps REAL,
            download_latency_ms REAL,
            download_jitter_ms REAL,
            download_low_ms REAL,
            download_high_ms REAL,

            upload_mbps REAL,
            upload_latency_ms REAL,
            upload_jitter_ms REAL,
            upload_low_ms REAL,
            upload_high_ms REAL,

            packet_loss_percent REAL,

            result_url TEXT,

            success INTEGER NOT NULL,
            error TEXT,

            raw_json TEXT
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_speedtest_timestamp
        ON speedtest_measurements(timestamp_utc)
    """)

    # --------------------------------------------------------
    # Events
    # --------------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_utc TEXT NOT NULL,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            target_name TEXT,
            message TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_timestamp
        ON events(timestamp_utc)
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_target
        ON events(target_name)
    """)

    conn.commit()

    return conn


# ============================================================
# DATABASE SAVE FUNCTIONS
# ============================================================

def save_ping(conn, cycle_id, result):

    conn.execute("""
        INSERT INTO ping_measurements (
            cycle_id,
            timestamp_utc,
            target_name,
            target_ip,
            ping_count,
            success_count,
            loss_percent,
            min_ms,
            avg_ms,
            max_ms,
            error
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        cycle_id,
        utc_now(),
        result["target_name"],
        result["target_ip"],
        result["ping_count"],
        result["success_count"],
        result["loss_percent"],
        result["min_ms"],
        result["avg_ms"],
        result["max_ms"],
        result["error"],
    ))

    conn.commit()


def save_dns(conn, result):

    conn.execute("""
        INSERT INTO dns_measurements (
            timestamp_utc,
            target_name,
            hostname,
            success,
            resolved_ips,
            error
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        utc_now(),
        result["target_name"],
        result["hostname"],
        1 if result["success"] else 0,
        json.dumps(
            result["resolved_ips"]
        ),
        result["error"],
    ))

    conn.commit()


def save_https(conn, result):

    conn.execute("""
        INSERT INTO https_measurements (
            timestamp_utc,
            target_name,
            url,
            success,
            http_code,
            time_total_ms,
            error
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        utc_now(),
        result["target_name"],
        result["url"],
        1 if result["success"] else 0,
        result["http_code"],
        result["time_total_ms"],
        result["error"],
    ))

    conn.commit()


def save_speedtest(conn, result):

    conn.execute("""
        INSERT INTO speedtest_measurements (
            timestamp_utc,

            server_id,
            server_name,
            server_location,
            server_country,

            isp,

            idle_latency_ms,
            idle_jitter_ms,
            idle_low_ms,
            idle_high_ms,

            download_mbps,
            download_latency_ms,
            download_jitter_ms,
            download_low_ms,
            download_high_ms,

            upload_mbps,
            upload_latency_ms,
            upload_jitter_ms,
            upload_low_ms,
            upload_high_ms,

            packet_loss_percent,

            result_url,

            success,
            error,

            raw_json
        )
        VALUES (
            ?,
            ?, ?, ?, ?,
            ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?,
            ?,
            ?,
            ?,
            ?
        )
    """, (
        utc_now(),

        result.get("server_id"),
        result.get("server_name"),
        result.get("server_location"),
        result.get("server_country"),

        result.get("isp"),

        result.get("idle_latency_ms"),
        result.get("idle_jitter_ms"),
        result.get("idle_low_ms"),
        result.get("idle_high_ms"),

        result.get("download_mbps"),
        result.get("download_latency_ms"),
        result.get("download_jitter_ms"),
        result.get("download_low_ms"),
        result.get("download_high_ms"),

        result.get("upload_mbps"),
        result.get("upload_latency_ms"),
        result.get("upload_jitter_ms"),
        result.get("upload_low_ms"),
        result.get("upload_high_ms"),

        result.get("packet_loss_percent"),

        result.get("result_url"),

        1 if result.get("success") else 0,

        result.get("error"),

        result.get("raw_json"),
    ))

    conn.commit()


def save_event(
    conn,
    event_type,
    severity,
    message,
    target_name=None
):

    conn.execute("""
        INSERT INTO events (
            timestamp_utc,
            event_type,
            severity,
            target_name,
            message
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        utc_now(),
        event_type,
        severity,
        target_name,
        message,
    ))

    conn.commit()


# ============================================================
# PING
# ============================================================

def ping_target(
    target_name,
    target_ip
):

    result = {
        "target_name": target_name,
        "target_ip": target_ip,
        "ping_count": PING_COUNT,
        "success_count": 0,
        "loss_percent": 100.0,
        "min_ms": None,
        "avg_ms": None,
        "max_ms": None,
        "error": None,
    }

    cmd = [
        "ping",
        "-n",
        "-c",
        str(PING_COUNT),
        "-W",
        str(PING_TIMEOUT),
        target_ip,
    ]

    try:

        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=(
                PING_COUNT
                * (PING_TIMEOUT + 1)
                + 2
            ),
        )

        output = (
            completed.stdout
            + "\n"
            + completed.stderr
        )

        times = []

        for line in completed.stdout.splitlines():

            match = re.search(
                r"time[=<]([0-9.]+)\s*ms",
                line
            )

            if match:

                try:
                    times.append(
                        float(match.group(1))
                    )

                except ValueError:
                    pass

        success_count = len(times)

        result["success_count"] = (
            success_count
        )

        result["loss_percent"] = (
            (
                PING_COUNT
                - success_count
            )
            / PING_COUNT
            * 100.0
        )

        if times:

            result["min_ms"] = min(times)

            result["avg_ms"] = (
                sum(times)
                / len(times)
            )

            result["max_ms"] = max(times)

        if success_count == 0:

            result["error"] = (
                output.strip()[-500:]
                if output.strip()
                else "Ping failed"
            )

    except subprocess.TimeoutExpired:

        result["error"] = (
            "Ping timeout"
        )

    except Exception as exc:

        result["error"] = str(exc)

    return result


# ============================================================
# TARGET STATE
# ============================================================

def target_state(loss_percent):

    if loss_percent >= 100.0:
        return "FULL"

    if loss_percent > 0.0:
        return "PARTIAL"

    return "OK"


def calculate_overall_state(results):

    problematic = []

    for result in results:

        if (
            result["target_name"]
            not in INTERNET_TARGETS
        ):
            continue

        state = target_state(
            result["loss_percent"]
        )

        if state != "OK":
            problematic.append(state)

    full_count = problematic.count(
        "FULL"
    )

    partial_count = problematic.count(
        "PARTIAL"
    )

    if full_count >= 3:
        return "OUTAGE"

    if full_count >= 2:
        return "DEGRADED"

    if full_count >= 1:
        return "DEGRADED"

    if partial_count >= 1:
        return "PARTIAL"

    return "NORMAL"


# ============================================================
# DNS PACKET FUNCTIONS
# ============================================================

def encode_dns_name(hostname):

    parts = hostname.rstrip(".").split(".")

    encoded = bytearray()

    for part in parts:

        encoded.append(
            len(part)
        )

        encoded.extend(
            part.encode("ascii")
        )

    encoded.append(0)

    return bytes(encoded)


def build_dns_query(hostname):

    query_id = random.randint(
        0,
        65535
    )

    header = (
        query_id.to_bytes(
            2,
            "big"
        )
        + b"\x01\x00"
        + b"\x00\x01"
        + b"\x00\x00"
        + b"\x00\x00"
        + b"\x00\x00"
    )

    question = (
        encode_dns_name(hostname)
        + b"\x00\x01"
        + b"\x00\x01"
    )

    return (
        query_id,
        header + question
    )


def skip_dns_name(
    data,
    offset
):

    length = len(data)

    while offset < length:

        value = data[offset]

        if value == 0:
            return offset + 1

        if (value & 0xC0) == 0xC0:
            return offset + 2

        offset += (
            1 + value
        )

    raise ValueError(
        "Invalid DNS name"
    )


def parse_dns_response(
    data,
    query_id
):

    if len(data) < 12:

        raise ValueError(
            "DNS response too short"
        )

    response_id = int.from_bytes(
        data[0:2],
        "big"
    )

    if response_id != query_id:

        raise ValueError(
            "DNS transaction ID mismatch"
        )

    flags = int.from_bytes(
        data[2:4],
        "big"
    )

    if not (
        flags & 0x8000
    ):

        raise ValueError(
            "Not a DNS response"
        )

    rcode = (
        flags
        & 0x000F
    )

    if rcode != 0:

        raise ValueError(
            f"DNS server returned RCODE {rcode}"
        )

    qdcount = int.from_bytes(
        data[4:6],
        "big"
    )

    ancount = int.from_bytes(
        data[6:8],
        "big"
    )

    offset = 12

    for _ in range(qdcount):

        offset = skip_dns_name(
            data,
            offset
        )

        if offset + 4 > len(data):

            raise ValueError(
                "Invalid DNS question section"
            )

        offset += 4

    addresses = []

    for _ in range(ancount):

        offset = skip_dns_name(
            data,
            offset
        )

        if offset + 10 > len(data):

            raise ValueError(
                "Invalid DNS answer section"
            )

        qtype = int.from_bytes(
            data[offset:offset + 2],
            "big"
        )

        qclass = int.from_bytes(
            data[offset + 2:offset + 4],
            "big"
        )

        rdlength = int.from_bytes(
            data[offset + 8:offset + 10],
            "big"
        )

        offset += 10

        if (
            offset + rdlength
            > len(data)
        ):

            raise ValueError(
                "Invalid DNS RDATA"
            )

        rdata = data[
            offset:
            offset + rdlength
        ]

        if (
            qclass == 1
            and qtype == 1
            and rdlength == 4
        ):

            addresses.append(
                socket.inet_ntoa(
                    rdata
                )
            )

        elif (
            qclass == 1
            and qtype == 28
            and rdlength == 16
        ):

            try:

                addresses.append(
                    socket.inet_ntop(
                        socket.AF_INET6,
                        rdata
                    )
                )

            except Exception:
                pass

        offset += rdlength

    return addresses


# ============================================================
# DIRECT DNS CHECK
# ============================================================

def direct_dns_check(
    target_name,
    resolver_ip,
    hostname
):

    result = {
        "target_name": target_name,
        "hostname": hostname,
        "success": False,
        "resolved_ips": [],
        "error": None,
    }

    try:

        query_id, packet = (
            build_dns_query(
                hostname
            )
        )

        sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM
        )

        sock.settimeout(
            DNS_TIMEOUT
        )

        try:

            sock.sendto(
                packet,
                (
                    resolver_ip,
                    53
                )
            )

            response, _ = (
                sock.recvfrom(4096)
            )

        finally:

            sock.close()

        addresses = (
            parse_dns_response(
                response,
                query_id
            )
        )

        result["resolved_ips"] = (
            addresses
        )

        if addresses:

            result["success"] = True

        else:

            result["error"] = (
                "DNS response contained "
                "no A/AAAA records"
            )

    except socket.timeout:

        result["error"] = (
            f"DNS timeout querying "
            f"{resolver_ip}"
        )

    except Exception as exc:

        result["error"] = str(exc)

    return result


# ============================================================
# DNS WORKER
# ============================================================

def dns_worker(
    db_path
):

    conn = None

    try:

        conn = open_db(
            db_path
        )

        log(
            "Running direct DNS checks..."
        )

        with (
            concurrent.futures
            .ThreadPoolExecutor(
                max_workers=3
            )
        ) as executor:

            futures = []

            for (
                target_name,
                config
            ) in DNS_TARGETS.items():

                futures.append(
                    executor.submit(
                        direct_dns_check,
                        target_name,
                        config["resolver_ip"],
                        config["hostname"],
                    )
                )

            for future in futures:

                try:

                    result = future.result()

                    save_dns(
                        conn,
                        result
                    )

                    if result["success"]:

                        ips = ", ".join(
                            result[
                                "resolved_ips"
                            ]
                        )

                        log(
                            f"DNS OK: "
                            f"{result['target_name']} "
                            f"-> {ips}"
                        )

                    else:

                        log(
                            f"DNS FAILED: "
                            f"{result['target_name']} "
                            f"- {result['error']}"
                        )

                except Exception as exc:

                    log(
                        f"DNS result error: "
                        f"{exc}"
                    )

    except Exception as exc:

        log(
            f"DNS worker database error: "
            f"{exc}"
        )

    finally:

        if conn is not None:

            try:
                conn.close()
            except Exception:
                pass


# ============================================================
# HTTPS CHECK
# ============================================================

def https_check(
    target_name,
    url
):

    result = {
        "target_name": target_name,
        "url": url,
        "success": False,
        "http_code": None,
        "time_total_ms": None,
        "error": None,
    }

    cmd = [
        "curl",
        "--silent",
        "--show-error",
        "--location",

        "--max-time",
        str(HTTPS_TIMEOUT),

        "--output",
        "/dev/null",

        "--write-out",
        "%{http_code}|%{time_total}",

        url,
    ]

    try:

        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=(
                HTTPS_TIMEOUT + 5
            ),
        )

        if completed.returncode != 0:

            result["error"] = (
                completed.stderr.strip()
                or
                f"curl exit code "
                f"{completed.returncode}"
            )

            return result

        output = (
            completed.stdout.strip()
        )

        if "|" not in output:

            result["error"] = (
                f"Unexpected curl output: "
                f"{output}"
            )

            return result

        http_code, time_total = (
            output.split(
                "|",
                1
            )
        )

        try:

            result["http_code"] = (
                int(http_code)
            )

        except ValueError:

            result["http_code"] = None

        try:

            result["time_total_ms"] = (
                float(time_total)
                * 1000.0
            )

        except ValueError:

            result["time_total_ms"] = None

        if (
            result["http_code"]
            is not None
            and
            200
            <= result["http_code"]
            < 400
        ):

            result["success"] = True

        else:

            result["error"] = (
                f"HTTP status "
                f"{result['http_code']}"
            )

    except subprocess.TimeoutExpired:

        result["error"] = (
            "HTTPS timeout"
        )

    except FileNotFoundError:

        result["error"] = (
            "curl command not found"
        )

    except Exception as exc:

        result["error"] = str(exc)

    return result


# ============================================================
# DOH CHECK
# ============================================================

def doh_check(
    target_name,
    url
):

    result = {
        "target_name": target_name,
        "url": url,
        "success": False,
        "http_code": None,
        "time_total_ms": None,
        "error": None,
    }

    response_file = None

    try:

        query_hostname = (
            "example.com"
        )

        query_id, packet = (
            build_dns_query(
                query_hostname
            )
        )

        with tempfile.NamedTemporaryFile(
            prefix="doh_response_",
            delete=False
        ) as tmp:

            response_file = (
                tmp.name
            )

        cmd = [
            "curl",

            # Quad9 DoH requires HTTP/2.
            "--http2",

            "--silent",
            "--show-error",

            "--max-time",
            str(HTTPS_TIMEOUT),

            "--output",
            response_file,

            "--write-out",
            "%{http_code}|%{time_total}",

            "--header",
            "Accept: application/dns-message",

            "--header",
            "Content-Type: application/dns-message",

            "--data-binary",
            "@-",

            url,
        ]

        completed = subprocess.run(
            cmd,
            input=packet,
            capture_output=True,
            timeout=(
                HTTPS_TIMEOUT + 5
            ),
        )

        if completed.returncode != 0:

            stderr = (
                completed.stderr.decode(
                    "utf-8",
                    errors="replace"
                ).strip()
            )

            result["error"] = (
                stderr
                or
                f"curl exit code "
                f"{completed.returncode}"
            )

            return result

        output = (
            completed.stdout.decode(
                "utf-8",
                errors="replace"
            ).strip()
        )

        if "|" not in output:

            result["error"] = (
                f"Unexpected curl output: "
                f"{output}"
            )

            return result

        http_code, time_total = (
            output.split(
                "|",
                1
            )
        )

        try:

            result["http_code"] = (
                int(http_code)
            )

        except ValueError:

            result["http_code"] = None

        try:

            result["time_total_ms"] = (
                float(time_total)
                * 1000.0
            )

        except ValueError:

            result["time_total_ms"] = None

        if result["http_code"] != 200:

            result["error"] = (
                f"DoH HTTP status "
                f"{result['http_code']}"
            )

            return result

        with open(
            response_file,
            "rb"
        ) as response_handle:

            response_data = (
                response_handle.read()
            )

        addresses = (
            parse_dns_response(
                response_data,
                query_id
            )
        )

        if not addresses:

            result["error"] = (
                "DoH returned no "
                "A/AAAA records"
            )

            return result

        result["success"] = True

    except subprocess.TimeoutExpired:

        result["error"] = (
            "DoH timeout"
        )

    except FileNotFoundError:

        result["error"] = (
            "curl command not found"
        )

    except Exception as exc:

        result["error"] = str(exc)

    finally:

        if response_file:

            try:
                os.unlink(
                    response_file
                )
            except Exception:
                pass

    return result


# ============================================================
# HTTPS / DOH WORKER
# ============================================================

def https_worker(
    db_path
):

    conn = None

    try:

        conn = open_db(
            db_path
        )

        log(
            "Running HTTPS checks..."
        )

        with (
            concurrent.futures
            .ThreadPoolExecutor(
                max_workers=3
            )
        ) as executor:

            futures = []

            for (
                target_name,
                config
            ) in HTTPS_TARGETS.items():

                if (
                    config["type"]
                    == "doh"
                ):

                    futures.append(
                        executor.submit(
                            doh_check,
                            target_name,
                            config["url"],
                        )
                    )

                else:

                    futures.append(
                        executor.submit(
                            https_check,
                            target_name,
                            config["url"],
                        )
                    )

            for future in futures:

                try:

                    result = (
                        future.result()
                    )

                    save_https(
                        conn,
                        result
                    )

                    if result["success"]:

                        if (
                            result[
                                "target_name"
                            ]
                            == "quad9_doh"
                        ):

                            log(
                                f"DoH OK: "
                                f"{result['target_name']} "
                                f"HTTP "
                                f"{result['http_code']} "
                                f"{result['time_total_ms']:.1f} ms"
                            )

                        else:

                            log(
                                f"HTTPS OK: "
                                f"{result['target_name']} "
                                f"HTTP "
                                f"{result['http_code']} "
                                f"{result['time_total_ms']:.1f} ms"
                            )

                    else:

                        log(
                            f"HTTPS FAILED: "
                            f"{result['target_name']} "
                            f"- {result['error']}"
                        )

                except Exception as exc:

                    log(
                        f"HTTPS result error: "
                        f"{exc}"
                    )

    except Exception as exc:

        log(
            f"HTTPS worker database error: "
            f"{exc}"
        )

    finally:

        if conn is not None:

            try:
                conn.close()
            except Exception:
                pass


# ============================================================
# MTR
# ============================================================

def run_mtr(
    target_name,
    target_ip
):

    log(
        f"MTR diagnostic started for "
        f"{target_name} ({target_ip})"
    )

    cmd = [
        "mtr",
        "--report",
        "--report-cycles",
        str(MTR_COUNT),
        "--no-dns",
        target_ip,
    ]

    try:

        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=MTR_TIMEOUT,
        )

        output = (
            completed.stdout.strip()
            if completed.stdout.strip()
            else completed.stderr.strip()
        )

        if completed.returncode == 0:

            log(
                f"MTR completed for "
                f"{target_name}"
            )

            if output:

                for line in (
                    output.splitlines()
                ):

                    print(
                        f"    {line}",
                        flush=True
                    )

        else:

            if (
                "Permission denied"
                in output
                or
                "Operation not permitted"
                in output
            ):

                log(
                    f"MTR permission denied "
                    f"for {target_name}. "
                    f"This does not change "
                    f"Internet State."
                )

            else:

                log(
                    f"MTR failed for "
                    f"{target_name}: "
                    f"{output[-500:]}"
                )

    except subprocess.TimeoutExpired:

        log(
            f"MTR timeout for "
            f"{target_name}"
        )

    except FileNotFoundError:

        log(
            "MTR command not found"
        )

    except Exception as exc:

        log(
            f"MTR error for "
            f"{target_name}: {exc}"
        )


def maybe_run_mtr(
    results
):

    global last_mtr_time

    now = time.monotonic()

    if (
        now - last_mtr_time
        < MTR_COOLDOWN
    ):
        return

    full_targets = []

    for result in results:

        if (
            result["target_name"]
            not in INTERNET_TARGETS
        ):
            continue

        if (
            result["loss_percent"]
            >= 100.0
        ):

            full_targets.append(
                result
            )

    if len(full_targets) < 2:
        return

    selected = full_targets[0]

    last_mtr_time = now

    thread = threading.Thread(
        target=run_mtr,
        args=(
            selected["target_name"],
            selected["target_ip"],
        ),
        daemon=True,
    )

    thread.start()


# ============================================================
# SPEEDTEST
# ============================================================

def run_speedtest(
    db_path
):

    conn = None

    result = {
        "success": False,
        "error": None,
        "raw_json": None,

        "server_id": None,
        "server_name": None,
        "server_location": None,
        "server_country": None,

        "isp": None,

        "idle_latency_ms": None,
        "idle_jitter_ms": None,
        "idle_low_ms": None,
        "idle_high_ms": None,

        "download_mbps": None,
        "download_latency_ms": None,
        "download_jitter_ms": None,
        "download_low_ms": None,
        "download_high_ms": None,

        "upload_mbps": None,
        "upload_latency_ms": None,
        "upload_jitter_ms": None,
        "upload_low_ms": None,
        "upload_high_ms": None,

        "packet_loss_percent": None,

        "result_url": None,
    }

    try:

        conn = open_db(
            db_path
        )

        log(
            "Starting Speedtest "
            "in background..."
        )

        cmd = [
            "speedtest",
            "--accept-license",
            "--accept-gdpr",
            "--format=json",
        ]

        try:

            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=SPEEDTEST_TIMEOUT,
            )

        except subprocess.TimeoutExpired:

            result["error"] = (
                "Speedtest timeout"
            )

            save_speedtest(
                conn,
                result
            )

            log(
                "Speedtest timed out."
            )

            return

        except FileNotFoundError:

            result["error"] = (
                "speedtest command not found"
            )

            save_speedtest(
                conn,
                result
            )

            log(
                "Speedtest command not found."
            )

            return

        if completed.returncode != 0:

            result["error"] = (
                completed.stderr.strip()
                or
                f"Speedtest exit code "
                f"{completed.returncode}"
            )

            save_speedtest(
                conn,
                result
            )

            log(
                f"Speedtest failed: "
                f"{result['error']}"
            )

            return

        raw = (
            completed.stdout.strip()
        )

        result["raw_json"] = raw

        data = json.loads(
            raw
        )

        # ----------------------------------------------------
        # Server
        # ----------------------------------------------------

        server = data.get(
            "server",
            {}
        )

        if server.get("id") is not None:

            result["server_id"] = str(
                server.get("id")
            )

        result["server_name"] = (
            server.get("name")
        )

        result["server_location"] = (
            server.get("location")
        )

        result["server_country"] = (
            server.get("country")
        )

        # ----------------------------------------------------
        # ISP
        # ----------------------------------------------------

        result["isp"] = data.get(
            "isp"
        )

        # ----------------------------------------------------
        # Idle ping
        # ----------------------------------------------------

        ping = data.get(
            "ping",
            {}
        )

        result["idle_latency_ms"] = (
            ping.get("latency")
        )

        result["idle_jitter_ms"] = (
            ping.get("jitter")
        )

        result["idle_low_ms"] = (
            ping.get("low")
        )

        result["idle_high_ms"] = (
            ping.get("high")
        )

        # ----------------------------------------------------
        # Download
        # ----------------------------------------------------

        download = data.get(
            "download",
            {}
        )

        bandwidth = download.get(
            "bandwidth"
        )

        if bandwidth is not None:

            result["download_mbps"] = (
                bandwidth
                * 8
                / 1_000_000
            )

        download_latency = (
            download.get(
                "latency",
                {}
            )
        )

        if isinstance(
            download_latency,
            dict
        ):

            result[
                "download_latency_ms"
            ] = download_latency.get(
                "latency"
            )

            result[
                "download_jitter_ms"
            ] = download_latency.get(
                "jitter"
            )

            result[
                "download_low_ms"
            ] = download_latency.get(
                "low"
            )

            result[
                "download_high_ms"
            ] = download_latency.get(
                "high"
            )

        # ----------------------------------------------------
        # Upload
        # ----------------------------------------------------

        upload = data.get(
            "upload",
            {}
        )

        bandwidth = upload.get(
            "bandwidth"
        )

        if bandwidth is not None:

            result["upload_mbps"] = (
                bandwidth
                * 8
                / 1_000_000
            )

        upload_latency = (
            upload.get(
                "latency",
                {}
            )
        )

        if isinstance(
            upload_latency,
            dict
        ):

            result[
                "upload_latency_ms"
            ] = upload_latency.get(
                "latency"
            )

            result[
                "upload_jitter_ms"
            ] = upload_latency.get(
                "jitter"
            )

            result[
                "upload_low_ms"
            ] = upload_latency.get(
                "low"
            )

            result[
                "upload_high_ms"
            ] = upload_latency.get(
                "high"
            )

        # ----------------------------------------------------
        # Packet loss / result URL
        # ----------------------------------------------------

        result["packet_loss_percent"] = (
            data.get(
                "packetLoss"
            )
        )

        result["result_url"] = (
            data.get(
                "result",
                {}
            ).get(
                "url"
            )
        )

        result["success"] = True

        save_speedtest(
            conn,
            result
        )

        download_text = (
            f"{result['download_mbps']:.2f} Mbps"
            if result["download_mbps"]
            is not None
            else "N/A"
        )

        upload_text = (
            f"{result['upload_mbps']:.2f} Mbps"
            if result["upload_mbps"]
            is not None
            else "N/A"
        )

        loss_text = (
            f"{result['packet_loss_percent']:.2f}%"
            if result[
                "packet_loss_percent"
            ] is not None
            else "N/A"
        )

        log(
            "Speedtest completed: "
            f"download={download_text}, "
            f"upload={upload_text}, "
            f"packet loss={loss_text}"
        )

    except Exception as exc:

        result["error"] = str(exc)

        if conn is not None:

            try:

                save_speedtest(
                    conn,
                    result
                )

            except Exception as db_exc:

                log(
                    f"Speedtest database error: "
                    f"{db_exc}"
                )

        log(
            f"Speedtest error: "
            f"{exc}"
        )

    finally:

        if conn is not None:

            try:
                conn.close()
            except Exception:
                pass


def speedtest_worker(
    db_path
):

    first_run = True

    while running:

        if first_run:

            first_run = False

        else:

            for _ in range(
                SPEEDTEST_INTERVAL
            ):

                if not running:
                    return

                time.sleep(1)

        if not running:
            return

        thread = threading.Thread(
            target=run_speedtest,
            args=(db_path,),
            daemon=True,
        )

        thread.start()


# ============================================================
# STATE EVENTS
# ============================================================

def process_target_state_changes(
    conn,
    results
):

    global target_states

    for result in results:

        target_name = (
            result["target_name"]
        )

        if (
            target_name
            not in INTERNET_TARGETS
        ):
            continue

        new_state = target_state(
            result["loss_percent"]
        )

        old_state = target_states.get(
            target_name,
            "OK"
        )

        if new_state == old_state:
            continue

        target_states[
            target_name
        ] = new_state

        loss = result[
            "loss_percent"
        ]

        if new_state == "OK":

            if old_state == "FULL":

                message = (
                    f"OK: {target_name} "
                    f"100% packet loss ended"
                )

            elif old_state == "PARTIAL":

                message = (
                    f"OK: {target_name} "
                    f"packet loss ended"
                )

            else:

                message = (
                    f"OK: {target_name} "
                    f"state returned to normal"
                )

            severity = "INFO"

        elif new_state == "PARTIAL":

            message = (
                f"WARNING: {target_name} "
                f"partial packet loss: "
                f"{loss:.1f}%"
            )

            severity = "WARNING"

        else:

            message = (
                f"WARNING: {target_name} "
                f"100% packet loss - "
                f"PROBLEM STARTED"
            )

            severity = "CRITICAL"

        save_event(
            conn,
            "TARGET_STATE_CHANGE",
            severity,
            message,
            target_name,
        )

        log(
            message
        )


def process_overall_state_change(
    conn,
    new_state
):

    global overall_state

    if new_state == overall_state:
        return

    old_state = overall_state

    overall_state = new_state

    if new_state == "NORMAL":

        severity = "INFO"

        message = (
            f"Internet state recovered: "
            f"{old_state} -> NORMAL"
        )

    elif new_state == "PARTIAL":

        severity = "WARNING"

        message = (
            f"Internet state changed: "
            f"{old_state} -> PARTIAL"
        )

    elif new_state == "DEGRADED":

        severity = "CRITICAL"

        message = (
            f"Internet state changed: "
            f"{old_state} -> DEGRADED"
        )

    elif new_state == "OUTAGE":

        severity = "CRITICAL"

        message = (
            f"Internet state changed: "
            f"{old_state} -> OUTAGE"
        )

    else:

        severity = "WARNING"

        message = (
            f"Internet state changed: "
            f"{old_state} -> {new_state}"
        )

    save_event(
        conn,
        "INTERNET_STATE_CHANGE",
        severity,
        message,
        None,
    )

    log(
        message
    )


# ============================================================
# DISPLAY
# ============================================================

def print_ping_result(
    result
):

    target = result[
        "target_name"
    ]

    loss = result[
        "loss_percent"
    ]

    if (
        result["success_count"]
        > 0
    ):

        avg = result[
            "avg_ms"
        ]

        print(
            f"    {target:<12} "
            f"loss={loss:6.1f}% "
            f"avg={avg:8.2f} ms",
            flush=True
        )

    else:

        print(
            f"    {target:<12} "
            f"loss={loss:6.1f}% "
            f"NO RESPONSE",
            flush=True
        )


# ============================================================
# SIGNAL HANDLER
# ============================================================

def signal_handler(
    signum,
    frame
):

    global running

    log(
        f"Received signal {signum}. "
        f"Stopping monitor..."
    )

    running = False


signal.signal(
    signal.SIGINT,
    signal_handler
)

signal.signal(
    signal.SIGTERM,
    signal_handler
)


# ============================================================
# MAIN
# ============================================================

def main():

    global running
    global last_dns_check
    global last_https_check

    os.makedirs(
        BASE_DIR,
        exist_ok=True
    )

    timestamp = (
        datetime.datetime.now()
        .strftime(
            "%Y%m%d_%H%M%S"
        )
    )

    db_path = os.path.join(
        BASE_DIR,
        f"monitor_{timestamp}.db"
    )

    conn = create_database(
        db_path
    )

    print_header(
        db_path
    )

    log(
        "Monitor started."
    )

    # --------------------------------------------------------
    # Speedtest background worker
    # --------------------------------------------------------

    speedtest_thread = threading.Thread(
        target=speedtest_worker,
        args=(db_path,),
        daemon=True,
    )

    speedtest_thread.start()

    # --------------------------------------------------------
    # Main ping cycle
    # --------------------------------------------------------

    cycle_id = 0

    next_cycle = (
        time.monotonic()
    )

    try:

        while running:

            now = time.monotonic()

            if now < next_cycle:

                time.sleep(
                    min(
                        0.2,
                        next_cycle - now
                    )
                )

                continue

            while next_cycle <= now:

                next_cycle += (
                    PING_INTERVAL
                )

            cycle_id += 1

            cycle_start = (
                time.monotonic()
            )

            print(
                f"[{local_now()}] "
                f"Cycle {cycle_id}",
                flush=True
            )

            # ------------------------------------------------
            # PING
            # ------------------------------------------------

            results = []

            with (
                concurrent.futures
                .ThreadPoolExecutor(
                    max_workers=len(
                        PING_TARGETS
                    )
                )
            ) as executor:

                futures = []

                for (
                    target_name,
                    target_ip
                ) in PING_TARGETS.items():

                    futures.append(
                        executor.submit(
                            ping_target,
                            target_name,
                            target_ip,
                        )
                    )

                for future in futures:

                    try:

                        result = (
                            future.result()
                        )

                        results.append(
                            result
                        )

                        save_ping(
                            conn,
                            cycle_id,
                            result
                        )

                    except Exception as exc:

                        log(
                            f"Ping worker error: "
                            f"{exc}"
                        )

            # ------------------------------------------------
            # Sort: gateway first
            # ------------------------------------------------

            order = {
                "gateway": 0,
                "cloudflare": 1,
                "google": 2,
                "quad9": 3,
            }

            results.sort(
                key=lambda r:
                order.get(
                    r["target_name"],
                    99
                )
            )

            for result in results:

                print_ping_result(
                    result
                )

            # ------------------------------------------------
            # Target state
            # ------------------------------------------------

            process_target_state_changes(
                conn,
                results
            )

            # ------------------------------------------------
            # Overall state
            # ------------------------------------------------

            new_overall_state = (
                calculate_overall_state(
                    results
                )
            )

            process_overall_state_change(
                conn,
                new_overall_state
            )

            # ------------------------------------------------
            # MTR
            # ------------------------------------------------

            maybe_run_mtr(
                results
            )

            # ------------------------------------------------
            # DNS background worker
            # ------------------------------------------------

            current = (
                time.monotonic()
            )

            if (
                current
                - last_dns_check
                >= DNS_INTERVAL
            ):

                last_dns_check = current

                threading.Thread(
                    target=dns_worker,
                    args=(db_path,),
                    daemon=True,
                ).start()

            # ------------------------------------------------
            # HTTPS / DoH background worker
            # ------------------------------------------------

            current = (
                time.monotonic()
            )

            if (
                current
                - last_https_check
                >= HTTPS_INTERVAL
            ):

                last_https_check = current

                threading.Thread(
                    target=https_worker,
                    args=(db_path,),
                    daemon=True,
                ).start()

            # ------------------------------------------------
            # Cycle timing
            # ------------------------------------------------

            elapsed = (
                time.monotonic()
                - cycle_start
            )

            print(
                f"    Overall state: "
                f"{overall_state} "
                f"(cycle {elapsed:.2f}s)",
                flush=True
            )

            print()

    finally:

        log(
            "Stopping background workers..."
        )

        running = False

        try:

            speedtest_thread.join(
                timeout=3
            )

        except Exception:
            pass

        try:

            conn.commit()
            conn.close()

        except Exception:
            pass

        log(
            f"Monitor stopped. "
            f"Database: {db_path}"
        )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    main()

