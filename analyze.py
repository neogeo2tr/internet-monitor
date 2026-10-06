#!/usr/bin/env python3

import os
import sys
import sqlite3
from datetime import datetime, timezone


VERSION = "v1.0"


# ============================================================
# Configuration
# ============================================================

#DB_PATH = sys.argv[1] if len(sys.argv) > 1 else None
VERBOSE = "-v" in sys.argv
DB_PATH = next(
    (arg for arg in sys.argv[1:] if arg != "-v"),
    None
)

# ============================================================
# Helpers
# ============================================================

def parse_timestamp(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def format_duration(seconds):
    if seconds is None:
        return "N/A"

    seconds = max(0, int(round(seconds)))

    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts = []

    if days:
        parts.append(f"{days}d")

    if hours:
        parts.append(f"{hours}h")

    if minutes:
        parts.append(f"{minutes}m")

    if seconds or not parts:
        parts.append(f"{seconds}s")

    return " ".join(parts)


def percent(value):
    if value is None:
        return "N/A"

    return f"{value:.3f}%"


def safe_float(value):
    try:
        return float(value)
    except Exception:
        return None


def table_exists(conn, table_name):
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (table_name,),
    ).fetchone()

    return row is not None


def table_columns(conn, table_name):
    if not table_exists(conn, table_name):
        return []

    rows = conn.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()

    return [row[1] for row in rows]


def first_existing_column(columns, candidates):
    for candidate in candidates:
        if candidate in columns:
            return candidate

    return None


# ============================================================
# Event parsing
# ============================================================

def classify_target_event(message):
    """
    Return one of:

        FULL_START
        FULL_END
        PARTIAL_START
        PARTIAL_END
        OK
        UNKNOWN

    IMPORTANT:
    '100% packet loss ended' is explicitly treated as FULL_END.
    The previous analyzer incorrectly classified this as PARTIAL.
    """

    if not message:
        return "UNKNOWN"

    msg = message.strip().lower()

    # --------------------------------------------------------
    # Explicit FULL LOSS start
    # --------------------------------------------------------

    if "100% packet loss" in msg:
        if (
            "problem started" in msg
            or "started" in msg
            or "begin" in msg
            or "began" in msg
        ):
            return "FULL_START"

        # ----------------------------------------------------
        # Explicit FULL LOSS end
        # ----------------------------------------------------

        if (
            "ended" in msg
            or "recovered" in msg
            or "resolved" in msg
            or "problem ended" in msg
        ):
            return "FULL_END"

        # A bare 100% packet loss message is considered FULL.
        return "FULL_START"

    # --------------------------------------------------------
    # Partial loss
    # --------------------------------------------------------

    if "partial packet loss" in msg:
        if (
            "recovered" in msg
            or "resolved" in msg
            or "ended" in msg
        ):
            return "PARTIAL_END"

        return "PARTIAL_START"

    # --------------------------------------------------------
    # Generic packet-loss recovery
    # --------------------------------------------------------

    if "packet loss" in msg:
        if (
            "recovered" in msg
            or "resolved" in msg
            or "ended" in msg
        ):
            return "PARTIAL_END"

    # --------------------------------------------------------
    # Generic OK
    # --------------------------------------------------------

    if msg.startswith("ok:"):
        return "OK"

    return "UNKNOWN"


def parse_target_events(conn):
    """
    Parse TARGET_STATE_CHANGE events.

    Returns:

        {
            target_name: {
                "full": [intervals],
                "partial": [intervals],
                "open": [events]
            }
        }
    """

    result = {}

    if not table_exists(conn, "events"):
        return result

    rows = conn.execute(
        """
        SELECT
            id,
            timestamp_utc,
            event_type,
            severity,
            target_name,
            message
        FROM events
        WHERE event_type = 'TARGET_STATE_CHANGE'
        ORDER BY timestamp_utc ASC, id ASC
        """
    ).fetchall()

    active = {}

    for row in rows:
        (
            event_id,
            timestamp_utc,
            event_type,
            severity,
            target_name,
            message,
        ) = row

        if not target_name:
            continue

        timestamp = parse_timestamp(timestamp_utc)

        if timestamp is None:
            continue

        target = target_name

        if target not in result:
            result[target] = {
                "full": [],
                "partial": [],
                "open": [],
            }

        classification = classify_target_event(message)

        # ----------------------------------------------------
        # FULL LOSS START
        # ----------------------------------------------------

        if classification == "FULL_START":

            # Ignore duplicate START while already FULL.
            if target in active and active[target]["state"] == "FULL":
                continue

            # If PARTIAL was active, close it before starting FULL.
            if target in active and active[target]["state"] == "PARTIAL":
                start_event = active.pop(target)

                duration = (
                    timestamp - start_event["timestamp"]
                ).total_seconds()

                result[target]["partial"].append(
                    {
                        "start": start_event["timestamp"],
                        "end": timestamp,
                        "duration": duration,
                        "start_event_id": start_event["id"],
                        "end_event_id": event_id,
                    }
                )

            active[target] = {
                "state": "FULL",
                "timestamp": timestamp,
                "id": event_id,
                "severity": severity,
                "message": message,
            }

            continue

        # ----------------------------------------------------
        # FULL LOSS END
        # ----------------------------------------------------

        if classification == "FULL_END":

            # Correctly pair with an active FULL event.
            if (
                target in active
                and active[target]["state"] == "FULL"
            ):
                start_event = active.pop(target)

                duration = (
                    timestamp - start_event["timestamp"]
                ).total_seconds()

                result[target]["full"].append(
                    {
                        "start": start_event["timestamp"],
                        "end": timestamp,
                        "duration": duration,
                        "start_event_id": start_event["id"],
                        "end_event_id": event_id,
                    }
                )

            else:
                # An END without a matching START is retained
                # as an informational unmatched event.
                result[target]["open"].append(
                    {
                        "state": "FULL_END_WITHOUT_START",
                        "timestamp": timestamp,
                        "event_id": event_id,
                        "message": message,
                    }
                )

            continue

        # ----------------------------------------------------
        # PARTIAL LOSS START
        # ----------------------------------------------------

        if classification == "PARTIAL_START":

            # Don't create a new PARTIAL event while FULL is active.
            if target in active and active[target]["state"] == "FULL":
                continue

            if target in active and active[target]["state"] == "PARTIAL":
                continue

            active[target] = {
                "state": "PARTIAL",
                "timestamp": timestamp,
                "id": event_id,
                "severity": severity,
                "message": message,
            }

            continue

        # ----------------------------------------------------
        # PARTIAL LOSS END
        # ----------------------------------------------------

        if classification == "PARTIAL_END":

            if (
                target in active
                and active[target]["state"] == "PARTIAL"
            ):
                start_event = active.pop(target)

                duration = (
                    timestamp - start_event["timestamp"]
                ).total_seconds()

                result[target]["partial"].append(
                    {
                        "start": start_event["timestamp"],
                        "end": timestamp,
                        "duration": duration,
                        "start_event_id": start_event["id"],
                        "end_event_id": event_id,
                    }
                )

            continue

        # ----------------------------------------------------
        # Generic OK event
        # ----------------------------------------------------

        if classification == "OK":

            if target in active:

                start_event = active.pop(target)

                duration = (
                    timestamp - start_event["timestamp"]
                ).total_seconds()

                if start_event["state"] == "FULL":

                    result[target]["full"].append(
                        {
                            "start": start_event["timestamp"],
                            "end": timestamp,
                            "duration": duration,
                            "start_event_id": start_event["id"],
                            "end_event_id": event_id,
                        }
                    )

                elif start_event["state"] == "PARTIAL":

                    result[target]["partial"].append(
                        {
                            "start": start_event["timestamp"],
                            "end": timestamp,
                            "duration": duration,
                            "start_event_id": start_event["id"],
                            "end_event_id": event_id,
                        }
                    )

            continue

    # --------------------------------------------------------
    # Remaining active events are genuinely OPEN.
    # --------------------------------------------------------

    for target, event in active.items():

        result[target]["open"].append(
            {
                "state": event["state"],
                "timestamp": event["timestamp"],
                "event_id": event["id"],
                "message": event["message"],
            }
        )

    return result


# ============================================================
# Internet state event parsing
# ============================================================

def parse_internet_state_message(message):
    """
    Parse messages such as:

        Internet state changed: NORMAL -> DEGRADED
        Internet state recovered: DEGRADED -> NORMAL

    Returns:

        (old_state, new_state)
    """

    if not message:
        return None, None

    msg = message.strip()

    marker = "Internet state changed:"

    if marker in msg:
        value = msg.split(marker, 1)[1].strip()

        if "->" in value:
            old_state, new_state = value.split("->", 1)
            return old_state.strip().upper(), new_state.strip().upper()

    marker = "Internet state recovered:"

    if marker in msg:
        value = msg.split(marker, 1)[1].strip()

        if "->" in value:
            old_state, new_state = value.split("->", 1)
            return old_state.strip().upper(), new_state.strip().upper()

    return None, None


def parse_internet_events(conn):
    """
    Parse INTERNET_STATE_CHANGE events.

    The parser is state based rather than relying on event
    severity. This is important because a later NORMAL event
    must close the immediately preceding DEGRADED event.
    """

    result = {
        "intervals": [],
        "open": [],
    }

    if not table_exists(conn, "events"):
        return result

    rows = conn.execute(
        """
        SELECT
            id,
            timestamp_utc,
            event_type,
            severity,
            target_name,
            message
        FROM events
        WHERE event_type = 'INTERNET_STATE_CHANGE'
        ORDER BY timestamp_utc ASC, id ASC
        """
    ).fetchall()

    active_state = None

    for row in rows:

        (
            event_id,
            timestamp_utc,
            event_type,
            severity,
            target_name,
            message,
        ) = row

        timestamp = parse_timestamp(timestamp_utc)

        if timestamp is None:
            continue

        old_state, new_state = parse_internet_state_message(message)

        if old_state is None or new_state is None:
            continue

        # ----------------------------------------------------
        # A non-NORMAL state starts an interval.
        # ----------------------------------------------------

        if new_state != "NORMAL":

            # If an identical state is already active, ignore
            # duplicate state-change messages.
            if (
                active_state is not None
                and active_state["state"] == new_state
            ):
                continue

            # If another non-normal state was active, close it
            # at this timestamp before opening the new one.
            if active_state is not None:

                duration = (
                    timestamp - active_state["timestamp"]
                ).total_seconds()

                result["intervals"].append(
                    {
                        "state": active_state["state"],
                        "start": active_state["timestamp"],
                        "end": timestamp,
                        "duration": duration,
                        "start_event_id": active_state["id"],
                        "end_event_id": event_id,
                    }
                )

            active_state = {
                "state": new_state,
                "timestamp": timestamp,
                "id": event_id,
                "severity": severity,
                "message": message,
            }

            continue

        # ----------------------------------------------------
        # NORMAL closes the currently active non-normal state.
        # ----------------------------------------------------

        if new_state == "NORMAL":

            if active_state is not None:

                duration = (
                    timestamp - active_state["timestamp"]
                ).total_seconds()

                result["intervals"].append(
                    {
                        "state": active_state["state"],
                        "start": active_state["timestamp"],
                        "end": timestamp,
                        "duration": duration,
                        "start_event_id": active_state["id"],
                        "end_event_id": event_id,
                    }
                )

                active_state = None

            continue

    # --------------------------------------------------------
    # Only an actually unmatched state remains OPEN.
    # --------------------------------------------------------

    if active_state is not None:

        result["open"].append(
            {
                "state": active_state["state"],
                "timestamp": active_state["timestamp"],
                "event_id": active_state["id"],
                "message": active_state["message"],
            }
        )

    return result


# ============================================================
# Database overview
# ============================================================

def print_database_overview(conn, db_path):

    print()
    print("=" * 72)
    print(f"INTERNET MONITOR ANALYZER {VERSION}")
    print("=" * 72)

    print()
    print("DATABASE")
    print("-" * 72)

    try:
        size_bytes = os.path.getsize(db_path)
        size_mb = size_bytes / (1024 * 1024)
        print(f"File: {db_path}")
        print(f"Size: {size_mb:.2f} MB")
    except Exception:
        print(f"File: {db_path}")

    tables = [
        "ping_measurements",
        "dns_measurements",
        "https_measurements",
        "events",
        "speedtest_measurements",
        "mtr_measurements",
    ]

    for table in tables:

        if table_exists(conn, table):

            try:
                count = conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]

                print(f"{table}: {count}")

            except Exception:
                print(f"{table}: ERROR")

        else:
            print(f"{table}: not present")


# ============================================================
# Monitoring time range
# ============================================================

def get_monitor_time_range(conn):

    timestamps = []

    for table in [
        "ping_measurements",
        "dns_measurements",
        "https_measurements",
        "events",
        "speedtest_measurements",
        "mtr_measurements",
    ]:

        if not table_exists(conn, table):
            continue

        columns = table_columns(conn, table)

        if "timestamp_utc" not in columns:
            continue

        row = conn.execute(
            f"""
            SELECT
                MIN(timestamp_utc),
                MAX(timestamp_utc)
            FROM {table}
            """
        ).fetchone()

        if row and row[0]:
            timestamps.append(row[0])

        if row and row[1]:
            timestamps.append(row[1])

    if not timestamps:
        return None, None, None

    parsed = [
        parse_timestamp(value)
        for value in timestamps
        if parse_timestamp(value) is not None
    ]

    if not parsed:
        return None, None, None

    start = min(parsed)
    end = max(parsed)
    duration = (end - start).total_seconds()

    return start, end, duration


def print_monitor_time(conn):

    start, end, duration = get_monitor_time_range(conn)

    print()
    print("MONITORING PERIOD")
    print("-" * 72)

    if start is None:
        print("No monitoring data found.")
        return

    print(f"Start:    {start.isoformat()}")
    print(f"End:      {end.isoformat()}")
    print(f"Duration: {format_duration(duration)}")


# ============================================================
# Ping analysis
# ============================================================

def analyze_ping(conn):

    print()
    print("PING SUMMARY")
    print("-" * 72)

    if not table_exists(conn, "ping_measurements"):
        print("ping_measurements table not present.")
        return

    rows = conn.execute(
        """
        SELECT
            target_name,
            SUM(ping_count),
            SUM(success_count),
            SUM(ping_count - success_count),
            AVG(loss_percent),
            AVG(avg_ms)
        FROM ping_measurements
        GROUP BY target_name
        ORDER BY
            CASE
                WHEN LOWER(target_name) = 'gateway' THEN 0
                ELSE 1
            END,
            target_name
        """
    ).fetchall()

    if not rows:
        print("No ping data.")
        return

    for row in rows:

        (
            target_name,
            total,
            success,
            lost,
            avg_loss,
            avg_latency,
        ) = row

        availability = (
            (success / total) * 100
            if total
            else 0
        )

        print()
        print(f"{target_name}")
        print(
            f"  Packets:     {success}/{total} successful"
        )
        print(
            f"  Lost:        {lost}"
        )
        print(
            f"  Loss:        {avg_loss:.3f}%"
        )
        print(
            f"  Availability:{availability:.3f}%"
        )

        if avg_latency is not None:
            print(
                f"  Avg latency: {avg_latency:.2f} ms"
            )


def analyze_internet_ping_aggregate(conn):

    print()
    print("INTERNET ICMP AGGREGATE")
    print("-" * 72)

    if not table_exists(conn, "ping_measurements"):
        return

    rows = conn.execute(
        """
        SELECT
            SUM(ping_count),
            SUM(success_count)
        FROM ping_measurements
        WHERE LOWER(target_name) != 'gateway'
        """
    ).fetchone()

    if not rows or rows[0] is None:
        print("No internet ping data.")
        return

    total = rows[0]
    success = rows[1] or 0
    lost = total - success

    loss = (
        (lost / total) * 100
        if total
        else 0
    )

    availability = (
        (success / total) * 100
        if total
        else 0
    )

    print(f"Total packets: {total}")
    print(f"Successful:    {success}")
    print(f"Lost:          {lost}")
    print(f"Packet loss:   {loss:.3f}%")
    print(f"Availability:  {availability:.3f}%")


# ============================================================
# DNS analysis
# ============================================================

def analyze_dns(conn):

    print()
    print("DNS SUMMARY")
    print("-" * 72)

    if not table_exists(conn, "dns_measurements"):
        print("dns_measurements table not present.")
        return

    rows = conn.execute(
        """
        SELECT
            target_name,
            COUNT(*),
            SUM(success)
        FROM dns_measurements
        GROUP BY target_name
        ORDER BY target_name
        """
    ).fetchall()

    if not rows:
        print("No DNS data.")
        return

    total_all = 0
    success_all = 0

    for row in rows:

        target_name, total, success = row

        success = success or 0
        failed = total - success

        rate = (
            (success / total) * 100
            if total
            else 0
        )

        total_all += total
        success_all += success

        print(
            f"{target_name}: "
            f"{success}/{total} successful "
            f"({rate:.1f}%)"
        )

    if total_all:
        rate = (
            success_all / total_all
        ) * 100

        print()
        print(
            f"Total DNS: "
            f"{success_all}/{total_all} successful "
            f"({rate:.1f}%)"
        )


# ============================================================
# HTTPS analysis
# ============================================================

def analyze_https(conn):

    print()
    print("HTTPS / DoH SUMMARY")
    print("-" * 72)

    if not table_exists(conn, "https_measurements"):
        print("https_measurements table not present.")
        return

    rows = conn.execute(
        """
        SELECT
            target_name,
            COUNT(*),
            SUM(success),
            AVG(time_total_ms),
            MIN(time_total_ms),
            MAX(time_total_ms)
        FROM https_measurements
        GROUP BY target_name
        ORDER BY target_name
        """
    ).fetchall()

    if not rows:
        print("No HTTPS data.")
        return

    for row in rows:

        (
            target_name,
            total,
            success,
            avg_ms,
            min_ms,
            max_ms,
        ) = row

        success = success or 0

        rate = (
            (success / total) * 100
            if total
            else 0
        )

        print()
        print(f"{target_name}")
        print(
            f"  Success: {success}/{total} ({rate:.1f}%)"
        )

        if avg_ms is not None:
            print(
                f"  Avg:     {avg_ms:.2f} ms"
            )

        if min_ms is not None:
            print(
                f"  Min:     {min_ms:.2f} ms"
            )

        if max_ms is not None:
            print(
                f"  Max:     {max_ms:.2f} ms"
            )


# ============================================================
# Speedtest analysis
# ============================================================

def analyze_speedtest(conn):

    print()
    print("SPEEDTEST SUMMARY")
    print("-" * 72)

    if not table_exists(conn, "speedtest_measurements"):
        print("speedtest_measurements table not present.")
        return

    columns = table_columns(
        conn,
        "speedtest_measurements",
    )

    required = [
        "timestamp_utc",
        "download_mbps",
        "upload_mbps",
        "success",
    ]

    missing = [
        column
        for column in required
        if column not in columns
    ]

    if missing:
        print(
            "Missing columns:",
            ", ".join(missing),
        )
        return

    rows = conn.execute(
        """
        SELECT
            timestamp_utc,
            server_name,
            server_location,
            isp,
            idle_latency_ms,
            idle_jitter_ms,
            download_mbps,
            upload_mbps,
            packet_loss_percent,
            success,
            error
        FROM speedtest_measurements
        ORDER BY timestamp_utc ASC
        """
    ).fetchall()

    if not rows:
        print("No speedtest data.")
        return

    successful = [
        row for row in rows
        if row[9]
    ]

    print(
        f"Tests: {len(successful)}/{len(rows)} successful"
    )

    if VERBOSE:
      for row in successful:

        (
            timestamp,
            server_name,
            server_location,
            isp,
            idle_latency,
            idle_jitter,
            download,
            upload,
            packet_loss,
            success,
            error,
        ) = row

        print()
        print(timestamp)

        if server_name:
            location = (
                f", {server_location}"
                if server_location
                else ""
            )

            print(
                f"  Server:      {server_name}{location}"
            )

        if isp:
            print(
                f"  ISP:         {isp}"
            )

        if idle_latency is not None:
            print(
                f"  Idle latency:{idle_latency:.2f} ms"
            )

        if idle_jitter is not None:
            print(
                f"  Idle jitter: {idle_jitter:.2f} ms"
            )

        if download is not None:
            print(
                f"  Download:    {download:.2f} Mbps"
            )

        if upload is not None:
            print(
                f"  Upload:      {upload:.2f} Mbps"
            )

        if packet_loss is not None:
            print(
                f"  Packet loss: {packet_loss:.2f}%"
            )

    if successful:

        downloads = [
            row[6]
            for row in successful
            if row[6] is not None
        ]

        uploads = [
            row[7]
            for row in successful
            if row[7] is not None
        ]

        idle = [
            row[4]
            for row in successful
            if row[4] is not None
        ]

        jitter = [
            row[5]
            for row in successful
            if row[5] is not None
        ]

        losses = [
            row[8]
            for row in successful
            if row[8] is not None
        ]

        print()
        print("Averages:")

        if downloads:
            print(
                f"  Download:    "
                f"{sum(downloads) / len(downloads):.2f} Mbps"
            )

        if uploads:
            print(
                f"  Upload:      "
                f"{sum(uploads) / len(uploads):.2f} Mbps"
            )

        if idle:
            print(
                f"  Idle latency:"
                f"{sum(idle) / len(idle):.2f} ms"
            )

        if jitter:
            print(
                f"  Idle jitter: "
                f"{sum(jitter) / len(jitter):.2f} ms"
            )

        if losses:
            print(
                f"  Packet loss: "
                f"{sum(losses) / len(losses):.2f}%"
            )


# ============================================================
# MTR analysis
# ============================================================

def analyze_mtr(conn):

    print()
    print("MTR SUMMARY")
    print("-" * 72)

    if not table_exists(conn, "mtr_measurements"):
        print("No MTR measurements recorded.")
        return

    columns = table_columns(
        conn,
        "mtr_measurements",
    )

    count = conn.execute(
        "SELECT COUNT(*) FROM mtr_measurements"
    ).fetchone()[0]

    print(f"MTR measurements: {count}")

    if count == 0:
        return

    # MTR schema may differ between analyzer generations.
    # Print basic information without assuming every column.

    timestamp_col = first_existing_column(
        columns,
        ["timestamp_utc", "timestamp"],
    )

    target_col = first_existing_column(
        columns,
        ["target_name", "target"],
    )

    if timestamp_col and target_col:

        rows = conn.execute(
            f"""
            SELECT
                {timestamp_col},
                {target_col}
            FROM mtr_measurements
            ORDER BY {timestamp_col} ASC
            """
        ).fetchall()

        for timestamp, target in rows:
            print(
                f"  {timestamp} - {target}"
            )


# ============================================================
# Event reporting
# ============================================================

def print_target_events(conn):

    print()
    print("TARGET LOSS EVENTS")
    print("-" * 72)

    parsed = parse_target_events(conn)

    if not parsed:
        print("No target state-change events.")
        return parsed

    total_full = 0
    total_partial = 0
    total_open = 0

    # Gateway first, then alphabetical.
    targets = sorted(
        parsed.keys(),
        key=lambda name: (
            0 if name.lower() == "gateway" else 1,
            name.lower(),
        ),
    )

    for target in targets:

        data = parsed[target]

        print()
        print(target)

        # ----------------------------------------------------
        # FULL LOSS
        # ----------------------------------------------------

        full_events = data["full"]

        print(
            f"  FULL LOSS EVENTS: {len(full_events)}"
        )

        for index, event in enumerate(full_events, 1):

            print(
                f"    #{index}: "
                f"{event['start'].isoformat()} -> "
                f"{event['end'].isoformat()} "
                f"({format_duration(event['duration'])})"
            )

        total_full += len(full_events)

        # ----------------------------------------------------
        # PARTIAL LOSS
        # ----------------------------------------------------

        partial_events = data["partial"]

        print(
            f"  PARTIAL LOSS EVENTS: "
            f"{len(partial_events)}"
        )

        for index, event in enumerate(partial_events, 1):

            print(
                f"    #{index}: "
                f"{event['start'].isoformat()} -> "
                f"{event['end'].isoformat()} "
                f"({format_duration(event['duration'])})"
            )

        total_partial += len(partial_events)

        # ----------------------------------------------------
        # OPEN EVENTS
        # ----------------------------------------------------

        real_open = [
            event
            for event in data["open"]
            if event["state"] in ("FULL", "PARTIAL")
        ]

        unmatched_end = [
            event
            for event in data["open"]
            if event["state"] == "FULL_END_WITHOUT_START"
        ]

        if real_open:

            print(
                f"  OPEN EVENT AT END: "
                f"{len(real_open)}"
            )

            for event in real_open:

                print(
                    f"    state={event['state']}, "
                    f"started={event['timestamp'].isoformat()}"
                )

        else:

            print(
                "  OPEN EVENT AT END: none"
            )

        if unmatched_end:

            print(
                f"  UNMATCHED END EVENTS: "
                f"{len(unmatched_end)}"
            )

        total_open += len(real_open)

    print()
    print("TARGET EVENT TOTALS")
    print("-" * 72)
    print(f"Confirmed FULL loss events:    {total_full}")
    print(f"Confirmed PARTIAL loss events: {total_partial}")
    print(f"Open target events at end:     {total_open}")

    return parsed


def print_internet_events(conn):

    print()
    print("INTERNET STATE EVENTS")
    print("-" * 72)

    parsed = parse_internet_events(conn)

    intervals = parsed["intervals"]
    open_events = parsed["open"]

    if not intervals and not open_events:
        print("No internet state-change events.")
        return parsed

    grouped = {}

    for event in intervals:
        state = event["state"]

        if state not in grouped:
            grouped[state] = []

        grouped[state].append(event)

    for state in sorted(grouped.keys()):

        print()
        print(state)

        events = grouped[state]

        for index, event in enumerate(events, 1):

            print(
                f"  #{index}: "
                f"{event['start'].isoformat()} -> "
                f"{event['end'].isoformat()} "
                f"({format_duration(event['duration'])})"
            )

    # --------------------------------------------------------
    # Open events
    # --------------------------------------------------------

    print()

    if open_events:

        print(
            f"OPEN INTERNET EVENT: "
            f"{len(open_events)}"
        )

        for event in open_events:

            print(
                f"  state={event['state']}, "
                f"started={event['timestamp'].isoformat()}"
            )

    else:

        print(
            "OPEN INTERNET EVENT: none"
        )

    # --------------------------------------------------------
    # Totals
    # --------------------------------------------------------

    print()
    print("INTERNET EVENT TOTALS")
    print("-" * 72)

    total_duration = 0

    for event in intervals:
        total_duration += event["duration"]

    print(
        f"Confirmed state intervals: "
        f"{len(intervals)}"
    )

    print(
        f"Total non-NORMAL duration: "
        f"{format_duration(total_duration)}"
    )

    print(
        f"Open internet events: "
        f"{len(open_events)}"
    )

    return parsed


# ============================================================
# Event correlation
# ============================================================

def print_event_correlation(target_events, internet_events):

    print()
    print("EVENT CORRELATION")
    print("-" * 72)

    print(
        "Target and internet-state events are shown separately."
    )

    print(
        "No ISP/outage conclusion is inferred from ICMP loss alone."
    )

    # --------------------------------------------------------
    # Gateway status
    # --------------------------------------------------------

    gateway = target_events.get("gateway")

    if gateway:

        gateway_full = len(gateway["full"])
        gateway_partial = len(gateway["partial"])
        gateway_open = len(
            [
                event
                for event in gateway["open"]
                if event["state"] in ("FULL", "PARTIAL")
            ]
        )

        print()
        print("Gateway:")
        print(
            f"  FULL events:    {gateway_full}"
        )
        print(
            f"  PARTIAL events: {gateway_partial}"
        )
        print(
            f"  Open events:    {gateway_open}"
        )

    # --------------------------------------------------------
    # Internet state summary
    # --------------------------------------------------------

    intervals = internet_events["intervals"]

    print()
    print("Internet state:")
    print(
        f"  Non-NORMAL intervals: {len(intervals)}"
    )

    for event in intervals:

        print(
            f"  {event['state']}: "
            f"{format_duration(event['duration'])}"
        )

    # --------------------------------------------------------
    # Interpretive factual observations only.
    # --------------------------------------------------------

    internet_loss_intervals = [
        event
        for event in intervals
        if event["state"] != "NORMAL"
    ]

    if gateway:

        gateway_problem_events = (
            gateway["full"]
            + gateway["partial"]
        )

        if not gateway_problem_events:
            print()
            print(
                "Observation: no gateway loss event was "
                "recorded during the monitored event log."
            )

        elif internet_loss_intervals:

            print()
            print(
                "Observation: gateway loss events and "
                "internet state events both exist; timing "
                "correlation should be examined before "
                "attributing the cause."
            )


# ============================================================
# Final summary
# ============================================================

def print_final_summary(
    conn,
    target_events,
    internet_events,
):

    print()
    print("=" * 72)
    print("FINAL SUMMARY")
    print("=" * 72)

    # --------------------------------------------------------
    # Target totals
    # --------------------------------------------------------

    full_count = 0
    partial_count = 0
    open_target_count = 0

    for target, data in target_events.items():

        full_count += len(data["full"])
        partial_count += len(data["partial"])

        open_target_count += len(
            [
                event
                for event in data["open"]
                if event["state"] in ("FULL", "PARTIAL")
            ]
        )

    # --------------------------------------------------------
    # Internet totals
    # --------------------------------------------------------

    internet_intervals = internet_events["intervals"]

    internet_open = len(
        internet_events["open"]
    )

    total_non_normal_duration = sum(
        event["duration"]
        for event in internet_intervals
    )

    print(
        f"Confirmed target FULL loss events: "
        f"{full_count}"
    )

    print(
        f"Confirmed target PARTIAL loss events: "
        f"{partial_count}"
    )

    print(
        f"Open target events at DB end: "
        f"{open_target_count}"
    )

    print(
        f"Confirmed internet state intervals: "
        f"{len(internet_intervals)}"
    )

    print(
        f"Total confirmed non-NORMAL duration: "
        f"{format_duration(total_non_normal_duration)}"
    )

    print(
        f"Open internet state at DB end: "
        f"{internet_open}"
    )

    # --------------------------------------------------------
    # Database integrity observation
    # --------------------------------------------------------

    print()

    if (
        open_target_count == 0
        and internet_open == 0
    ):

        print(
            "Event pairing status: "
            "all recorded problem events are closed."
        )

    else:

        print(
            "Event pairing status: "
            "one or more events remain open at DB end."
        )

    # --------------------------------------------------------
    # Important qualification
    # --------------------------------------------------------

    print()
    print(
        "Note: ICMP packet loss and internet-state changes "
        "are measurements recorded by this monitor. "
        "They do not by themselves establish the root cause "
        "of an outage or identify the ISP as the cause."
    )


# ============================================================
# Main
# ============================================================

def main():

    if not DB_PATH:

        print(
            f"Internet Monitor Analyzer {VERSION}"
        )

        print()
        print(
            "Usage:"
        )

        print(
            "  python3 analyze.py "
            "/path/to/monitor_YYYYMMDD_HHMMSS.db"
        )

        sys.exit(1)

    if not os.path.exists(DB_PATH):

        print(
            f"ERROR: database not found: {DB_PATH}"
        )

        sys.exit(1)

    try:

        conn = sqlite3.connect(
            DB_PATH
        )

    except Exception as exc:

        print(
            f"ERROR: cannot open database: {exc}"
        )

        sys.exit(1)

    try:

        print_database_overview(
            conn,
            DB_PATH,
        )

        print_monitor_time(
            conn
        )

        analyze_ping(
            conn
        )

        analyze_internet_ping_aggregate(
            conn
        )

        analyze_dns(
            conn
        )

        analyze_https(
            conn
        )

        analyze_speedtest(
            conn
        )

        analyze_mtr(
            conn
        )

        target_events = print_target_events(
            conn
        )

        internet_events = print_internet_events(
            conn
        )

        print_event_correlation(
            target_events,
            internet_events,
        )

        print_final_summary(
            conn,
            target_events,
            internet_events,
        )

    except KeyboardInterrupt:

        print()
        print(
            "Analysis interrupted."
        )

        sys.exit(130)

    except Exception as exc:

        print()
        print(
            "ERROR during analysis:"
        )
        print(
            f"  {type(exc).__name__}: {exc}"
        )

        raise

    finally:

        conn.close()


if __name__ == "__main__":
    main()

