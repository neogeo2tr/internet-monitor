"""
Usage:
    python3 report.py /opt/internet-monitor/monitor_YYYYMMDD_HHMMSS.db
    python3 report.py -v /opt/internet-monitor/monitor_YYYYMMDD_HHMMSS.db
"""

import os
import sys
import sqlite3
import tempfile
from datetime import datetime
from statistics import mean

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    Image,
    Flowable,
)
from reportlab.graphics import renderPDF
from svglib.svglib import svg2rlg


VERSION = "v1.0"

LOGO_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "imlogo.svg",
)


# ----------------------------------------------------------------------
# Design colors
# ----------------------------------------------------------------------

BLUE_DARK = colors.HexColor("#1F4E79")
BLUE = colors.HexColor("#2F75B5")
BLUE_LIGHT = colors.HexColor("#DCEAF7")
BLUE_PALE = colors.HexColor("#EEF5FB")

TEXT_DARK = colors.HexColor("#263238")
TEXT_GREY = colors.HexColor("#6B7280")

GRID_GREY = colors.HexColor("#B8C2CC")
BORDER_GREY = colors.HexColor("#CBD5E1")


# ----------------------------------------------------------------------
# Formatting helpers
# ----------------------------------------------------------------------

def utc_display(ts):
    """
    Display timestamp explicitly as UTC.

    The monitor stores timestamps with timezone information.
    The report does not convert the clock time; it simply labels
    the stored timestamp as UTC.
    """

    if not ts:
        return "-"

    try:
        dt = datetime.fromisoformat(
            ts.replace("Z", "+00:00")
        )

        return dt.strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )

    except Exception:
        return f"{ts} UTC"


def time_display(ts):
    """
    Display time-of-day explicitly as UTC.
    """

    if not ts:
        return "-"

    try:
        dt = datetime.fromisoformat(
            ts.replace("Z", "+00:00")
        )

        return dt.strftime(
            "%H:%M:%S UTC"
        )

    except Exception:
        return f"{ts} UTC"


def fmt_duration(seconds):

    if seconds is None:
        return "-"

    seconds = int(round(seconds))

    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)

    parts = []

    if days:
        parts.append(f"{days}d")

    if hours or days:
        parts.append(f"{hours}h")

    if minutes or hours or days:
        parts.append(f"{minutes}m")

    parts.append(f"{secs}s")

    return " ".join(parts)


# ----------------------------------------------------------------------
# Logo
# ----------------------------------------------------------------------

def load_logo():
    """Load the user-supplied SVG logo as a ReportLab drawing."""

    if not os.path.isfile(LOGO_PATH):
        raise FileNotFoundError(
            f"SVG logo not found: {LOGO_PATH}"
        )

    drawing = svg2rlg(LOGO_PATH)

    if drawing is None:
        raise RuntimeError(
            f"Could not load SVG logo: {LOGO_PATH}"
        )

    return drawing


class LogoFlowable(Flowable):
    """
    Flowable version of the user-supplied SVG logo.

    The SVG is rendered as vector graphics in the PDF and scaled
    proportionally to the requested width.
    """

    def __init__(
        self,
        width=70 * mm,
    ):

        Flowable.__init__(self)

        self.drawing = load_logo()

        if not self.drawing.width or not self.drawing.height:
            raise RuntimeError(
                "SVG logo has invalid dimensions."
            )

        self.width = width
        self.scale = (
            self.width
            /
            self.drawing.width
        )
        self.height = (
            self.drawing.height
            *
            self.scale
        )

        self.hAlign = "CENTER"

    def draw(self):

        self.canv.saveState()

        self.canv.scale(
            self.scale,
            self.scale,
        )

        renderPDF.draw(
            self.drawing,
            self.canv,
            0,
            0,
        )

        self.canv.restoreState()


def draw_footer_logo(canvas_obj):
    """Draw the small centered SVG logo in the page footer."""

    drawing = load_logo()

    if not drawing.width or not drawing.height:
        return

    width = 12 * mm
    scale = width / drawing.width
    height = drawing.height * scale

    x = 105 * mm - width / 2
    y = 8.7 * mm - height / 2

    canvas_obj.saveState()

    canvas_obj.translate(
        x,
        y,
    )

    canvas_obj.scale(
        scale,
        scale,
    )

    renderPDF.draw(
        drawing,
        canvas_obj,
        0,
        0,
    )

    canvas_obj.restoreState()


# ----------------------------------------------------------------------
# PDF table helper
# ----------------------------------------------------------------------

def make_table(
    data,
    widths=None,
    header=True,
    font_size=7.2,
):

    table = Table(
        data,
        colWidths=widths,
        repeatRows=1 if header else 0,
        hAlign="LEFT",
    )

    commands = [
        (
            "FONTNAME",
            (0, 0),
            (-1, 0),
            "Helvetica-Bold"
            if header
            else "Helvetica",
        ),
        (
            "TEXTCOLOR",
            (0, 0),
            (-1, -1),
            TEXT_DARK,
        ),
        (
            "FONTSIZE",
            (0, 0),
            (-1, -1),
            font_size,
        ),
        (
            "VALIGN",
            (0, 0),
            (-1, -1),
            "TOP",
        ),
        (
            "GRID",
            (0, 0),
            (-1, -1),
            0.25,
            GRID_GREY,
        ),
        (
            "LEFTPADDING",
            (0, 0),
            (-1, -1),
            3,
        ),
        (
            "RIGHTPADDING",
            (0, 0),
            (-1, -1),
            3,
        ),
        (
            "TOPPADDING",
            (0, 0),
            (-1, -1),
            3,
        ),
        (
            "BOTTOMPADDING",
            (0, 0),
            (-1, -1),
            3,
        ),
    ]

    if header:

        commands.extend(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    BLUE_LIGHT,
                ),
                (
                    "TEXTCOLOR",
                    (0, 0),
                    (-1, 0),
                    BLUE_DARK,
                ),
                (
                    "LINEBELOW",
                    (0, 0),
                    (-1, 0),
                    0.7,
                    BLUE,
                ),
            ]
        )

    table.setStyle(
        TableStyle(commands)
    )

    return table


# ----------------------------------------------------------------------
# "Page X of Y" canvas
# ----------------------------------------------------------------------

class NumberedCanvas(canvas.Canvas):

    def __init__(self, *args, **kwargs):

        canvas.Canvas.__init__(
            self,
            *args,
            **kwargs,
        )

        self._saved_page_states = []

    def showPage(self):

        self._saved_page_states.append(
            dict(self.__dict__)
        )

        self._startPage()

    def save(self):

        page_count = len(
            self._saved_page_states
        )

        for state in self._saved_page_states:

            self.__dict__.update(state)

            self.draw_page_number(
                page_count
            )

            canvas.Canvas.showPage(
                self
            )

        canvas.Canvas.save(
            self
        )

    def draw_page_number(
        self,
        page_count,
    ):

        self.saveState()

        # Footer separator
        self.setStrokeColor(
            BORDER_GREY
        )

        self.setLineWidth(
            0.35
        )

        self.line(
            15 * mm,
            13 * mm,
            195 * mm,
            13 * mm,
        )

        # Footer text
        self.setFont(
            "Helvetica",
            7,
        )

        self.setFillColor(
            TEXT_GREY
        )

        self.drawString(
            15 * mm,
            9 * mm,
            f"Internet Monitor Report {VERSION}",
        )

        self.drawRightString(
            195 * mm,
            9 * mm,
            f"Page {self._pageNumber} of {page_count}",
        )

        # Very small centered SVG logo on non-cover pages
        if self._pageNumber > 1:
            draw_footer_logo(self)

        self.restoreState()


# ----------------------------------------------------------------------
# Database helpers
# ----------------------------------------------------------------------

def get_tables(conn):

    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table'
        """
    ).fetchall()

    return {
        row[0]
        for row in rows
    }


def monitoring_period(
    conn,
    tables,
):

    timestamps = []

    for name in [
        "ping_measurements",
        "dns_measurements",
        "https_measurements",
        "speedtest_measurements",
        "events",
    ]:

        if name not in tables:
            continue

        row = conn.execute(
            f"""
            SELECT
                MIN(timestamp_utc),
                MAX(timestamp_utc)
            FROM {name}
            """
        ).fetchone()

        if row:

            if row[0]:
                timestamps.append(
                    row[0]
                )

            if row[1]:
                timestamps.append(
                    row[1]
                )

    if not timestamps:
        return None, None, None

    parsed = []

    for value in timestamps:

        try:

            parsed.append(
                datetime.fromisoformat(
                    value.replace(
                        "Z",
                        "+00:00",
                    )
                )
            )

        except Exception:
            pass

    if not parsed:
        return None, None, None

    start = min(parsed)
    end = max(parsed)

    duration = (
        end - start
    ).total_seconds()

    return (
        start.isoformat(),
        end.isoformat(),
        duration,
    )


# ----------------------------------------------------------------------
# Load measurements
# ----------------------------------------------------------------------

def load_ping(conn):

    return conn.execute(
        """
        SELECT
            timestamp_utc,
            target_name,
            success_count,
            ping_count,
            loss_percent,
            min_ms,
            avg_ms,
            max_ms
        FROM ping_measurements
        ORDER BY timestamp_utc, id
        """
    ).fetchall()


def load_speedtests(conn):

    return conn.execute(
        """
        SELECT
            timestamp_utc,
            server_name,
            download_mbps,
            upload_mbps,
            idle_latency_ms,
            idle_jitter_ms,
            packet_loss_percent,
            success,
            error
        FROM speedtest_measurements
        ORDER BY timestamp_utc, id
        """
    ).fetchall()


def load_dns(conn):

    return conn.execute(
        """
        SELECT
            target_name,
            COUNT(*),
            SUM(success),
            COUNT(*) - SUM(success)
        FROM dns_measurements
        GROUP BY target_name
        ORDER BY target_name
        """
    ).fetchall()


def load_https(conn):

    return conn.execute(
        """
        SELECT
            target_name,
            COUNT(*),
            SUM(success),
            COUNT(*) - SUM(success),
            AVG(time_total_ms),
            MIN(time_total_ms),
            MAX(time_total_ms)
        FROM https_measurements
        GROUP BY target_name
        ORDER BY target_name
        """
    ).fetchall()


def load_events(
    conn,
    tables,
):

    if "events" not in tables:
        return []

    return conn.execute(
        """
        SELECT
            timestamp_utc,
            event_type,
            severity,
            target_name,
            message
        FROM events
        ORDER BY timestamp_utc, id
        """
    ).fetchall()


# ----------------------------------------------------------------------
# Ping summary
# ----------------------------------------------------------------------

def build_ping_summary(rows):

    result = {}

    for row in rows:

        (
            timestamp,
            target,
            success,
            count,
            loss,
            minimum,
            average,
            maximum,
        ) = row

        item = result.setdefault(
            target,
            {
                "packets": 0,
                "success": 0,
                "avg_values": [],
                "min_values": [],
                "max_values": [],
            },
        )

        item["packets"] += count
        item["success"] += success

        if average is not None:
            item["avg_values"].append(
                average
            )

        if minimum is not None:
            item["min_values"].append(
                minimum
            )

        if maximum is not None:
            item["max_values"].append(
                maximum
            )

    for item in result.values():

        item["lost"] = (
            item["packets"]
            -
            item["success"]
        )

        if item["packets"]:

            item["loss"] = (
                item["lost"]
                /
                item["packets"]
                *
                100
            )

        else:

            item["loss"] = 0

        item["availability"] = (
            100
            -
            item["loss"]
        )

        item["avg"] = (
            mean(
                item["avg_values"]
            )
            if item["avg_values"]
            else None
        )

        item["min"] = (
            min(
                item["min_values"]
            )
            if item["min_values"]
            else None
        )

        item["max"] = (
            max(
                item["max_values"]
            )
            if item["max_values"]
            else None
        )

    return result


# ----------------------------------------------------------------------
# Event correlation
# ----------------------------------------------------------------------

def event_intervals(events):

    target_open = {}
    internet_open = {}

    target_intervals = []
    internet_intervals = []

    for (
        timestamp,
        event_type,
        severity,
        target,
        message,
    ) in events:

        message_lower = (
            message or ""
        ).lower()

        # --------------------------------------------------------------
        # Target events
        # --------------------------------------------------------------

        if (
            event_type ==
            "TARGET_STATE_CHANGE"
            and target
        ):

            if (
                "100% packet loss"
                in message_lower
                and (
                    "started"
                    in message_lower
                    or
                    "problem started"
                    in message_lower
                )
            ):

                target_open[target] = (
                    timestamp,
                    "FULL",
                )

            elif (
                "100% packet loss"
                in message_lower
                and (
                    "ended"
                    in message_lower
                    or
                    "recovered"
                    in message_lower
                )
            ):

                if target in target_open:

                    start, state = (
                        target_open.pop(
                            target
                        )
                    )

                    target_intervals.append(
                        (
                            target,
                            state,
                            start,
                            timestamp,
                        )
                    )

            elif (
                "partial packet loss"
                in message_lower
                and (
                    "started"
                    in message_lower
                    or
                    "warning"
                    in message_lower
                )
            ):

                target_open[target] = (
                    timestamp,
                    "PARTIAL",
                )

            elif (
                "packet loss"
                in message_lower
                and any(
                    keyword in message_lower
                    for keyword in [
                        "recovered",
                        "resolved",
                        "ended",
                    ]
                )
            ):

                if target in target_open:

                    start, state = (
                        target_open.pop(
                            target
                        )
                    )

                    target_intervals.append(
                        (
                            target,
                            state,
                            start,
                            timestamp,
                        )
                    )

        # --------------------------------------------------------------
        # Internet state events
        # --------------------------------------------------------------

        elif (
            event_type ==
            "INTERNET_STATE_CHANGE"
        ):

            if "->" not in message:
                continue

            try:

                new_state = (
                    message
                    .split(
                        "->",
                        1
                    )[1]
                    .strip()
                )

                if new_state != "NORMAL":

                    internet_open = {
                        "state": new_state,
                        "start": timestamp,
                    }

                else:

                    if internet_open:

                        internet_intervals.append(
                            (
                                internet_open[
                                    "state"
                                ],
                                internet_open[
                                    "start"
                                ],
                                timestamp,
                            )
                        )

                        internet_open = {}

            except Exception:
                pass

    return (
        target_intervals,
        internet_intervals,
        target_open,
        internet_open,
    )


# ----------------------------------------------------------------------
# Graph generation
# ----------------------------------------------------------------------

def make_icmp_chart(
    rows,
    output_path,
):

    by_target = {}

    for row in rows:

        (
            timestamp,
            target,
            success,
            count,
            loss,
            minimum,
            average,
            maximum,
        ) = row

        if average is None:
            continue

        try:

            dt = datetime.fromisoformat(
                timestamp.replace(
                    "Z",
                    "+00:00",
                )
            )

        except Exception:
            continue

        by_target.setdefault(
            target,
            []
        ).append(
            (
                dt,
                average,
            )
        )

    if not by_target:
        return False

    fig, ax = plt.subplots(
        figsize=(10.8, 4.6),
        dpi=150,
    )

    for target, values in (
        by_target.items()
    ):

        ax.plot(
            [
                x[0]
                for x in values
            ],
            [
                x[1]
                for x in values
            ],
            label=target,
            linewidth=0.8,
        )

    ax.set_title(
        "ICMP average latency over time"
    )

    ax.set_ylabel(
        "Latency (ms)"
    )

    ax.set_xlabel(
        "Time (UTC)"
    )

    ax.grid(
        True,
        alpha=0.25,
    )

    ax.legend(
        loc="upper left",
        ncol=2,
        fontsize=8,
    )

    fig.autofmt_xdate()

    fig.tight_layout()

    fig.savefig(
        output_path,
        bbox_inches="tight",
    )

    plt.close(fig)

    return True


def make_speed_chart(
    rows,
    output_path,
):

    values = []

    for row in rows:

        (
            timestamp,
            server,
            download,
            upload,
            idle,
            jitter,
            loss,
            success,
            error,
        ) = row

        if (
            not success
            or download is None
            or upload is None
        ):
            continue

        try:

            dt = datetime.fromisoformat(
                timestamp.replace(
                    "Z",
                    "+00:00",
                )
            )

        except Exception:
            continue

        values.append(
            (
                dt,
                download,
                upload,
            )
        )

    if not values:
        return False

    fig, ax = plt.subplots(
        figsize=(10.8, 4.6),
        dpi=150,
    )

    x = [
        item[0]
        for item in values
    ]

    ax.plot(
        x,
        [
            item[1]
            for item in values
        ],
        label="Download",
        linewidth=1.0,
    )

    ax.plot(
        x,
        [
            item[2]
            for item in values
        ],
        label="Upload",
        linewidth=1.0,
    )

    ax.set_title(
        "Speedtest throughput over time"
    )

    ax.set_ylabel(
        "Mbps"
    )

    ax.set_xlabel(
        "Time (UTC)"
    )

    ax.grid(
        True,
        alpha=0.25,
    )

    ax.legend(
        loc="best"
    )

    fig.autofmt_xdate()

    fig.tight_layout()

    fig.savefig(
        output_path,
        bbox_inches="tight",
    )

    plt.close(fig)

    return True


def make_speed_latency_chart(
    rows,
    output_path,
):

    values = []

    for row in rows:

        (
            timestamp,
            server,
            download,
            upload,
            idle,
            jitter,
            loss,
            success,
            error,
        ) = row

        if (
            not success
            or idle is None
        ):
            continue

        try:

            dt = datetime.fromisoformat(
                timestamp.replace(
                    "Z",
                    "+00:00",
                )
            )

        except Exception:
            continue

        values.append(
            (
                dt,
                idle,
                jitter,
            )
        )

    if not values:
        return False

    fig, ax = plt.subplots(
        figsize=(10.8, 4.6),
        dpi=150,
    )

    x = [
        item[0]
        for item in values
    ]

    ax.plot(
        x,
        [
            item[1]
            for item in values
        ],
        label="Idle latency",
        linewidth=1.0,
    )

    ax.plot(
        x,
        [
            item[2]
            for item in values
        ],
        label="Jitter",
        linewidth=1.0,
    )

    ax.set_title(
        "Speedtest idle latency and jitter"
    )

    ax.set_ylabel(
        "Milliseconds"
    )

    ax.set_xlabel(
        "Time (UTC)"
    )

    ax.grid(
        True,
        alpha=0.25,
    )

    ax.legend(
        loc="best"
    )

    fig.autofmt_xdate()

    fig.tight_layout()

    fig.savefig(
        output_path,
        bbox_inches="tight",
    )

    plt.close(fig)

    return True


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main():

    # --------------------------------------------------------------
    # Optional verbose mode
    # --------------------------------------------------------------

    VERBOSE = "-v" in sys.argv

    db_path = next(
        (
            arg
            for arg in sys.argv[1:]
            if arg != "-v"
        ),
        None,
    )

    if db_path is None:

        print(
            "Usage: python3 report.py [-v] <database.db>"
        )

        sys.exit(1)

    if not os.path.isfile(
        db_path
    ):

        print(
            f"Database not found: {db_path}"
        )

        sys.exit(1)

    output_dir = os.path.join(
        os.path.dirname(db_path),
        "reports",
    )

    os.makedirs(
        output_dir,
        exist_ok=True,
    )

    base_name = os.path.splitext(
        os.path.basename(db_path)
    )[0]

    pdf_path = os.path.join(
        output_dir,
        f"{base_name}_report.pdf",
    )

    conn = sqlite3.connect(
        db_path
    )

    tables = get_tables(
        conn
    )

    start, end, duration = (
        monitoring_period(
            conn,
            tables,
        )
    )

    ping_rows = (
        load_ping(conn)
        if "ping_measurements"
        in tables
        else []
    )

    speed_rows = (
        load_speedtests(conn)
        if "speedtest_measurements"
        in tables
        else []
    )

    dns_rows = (
        load_dns(conn)
        if "dns_measurements"
        in tables
        else []
    )

    https_rows = (
        load_https(conn)
        if "https_measurements"
        in tables
        else []
    )

    events = load_events(
        conn,
        tables,
    )

    ping_summary = (
        build_ping_summary(
            ping_rows
        )
    )

    (
        target_intervals,
        internet_intervals,
        open_targets,
        open_internet,
    ) = event_intervals(
        events
    )

    # ------------------------------------------------------------------
    # Aggregate internet ICMP values
    # ------------------------------------------------------------------

    internet_targets = [
        target
        for target in ping_summary
        if target != "gateway"
    ]

    internet_packets = sum(
        ping_summary[target]["packets"]
        for target in internet_targets
    )

    internet_success = sum(
        ping_summary[target]["success"]
        for target in internet_targets
    )

    if internet_packets:

        internet_loss = (
            (
                internet_packets
                -
                internet_success
            )
            /
            internet_packets
            *
            100
        )

    else:

        internet_loss = 0

    internet_availability = (
        100
        -
        internet_loss
    )

    # ------------------------------------------------------------------
    # Speedtest aggregates
    # ------------------------------------------------------------------

    successful_speed = [
        row
        for row in speed_rows
        if (
            row[7]
            and row[2] is not None
            and row[3] is not None
        )
    ]

    download_values = [
        row[2]
        for row in successful_speed
    ]

    upload_values = [
        row[3]
        for row in successful_speed
    ]

    idle_values = [
        row[4]
        for row in successful_speed
        if row[4] is not None
    ]

    jitter_values = [
        row[5]
        for row in successful_speed
        if row[5] is not None
    ]

    speed_loss_values = [
        row[6]
        for row in successful_speed
        if row[6] is not None
    ]

    # ------------------------------------------------------------------
    # Temporary graphs
    # ------------------------------------------------------------------

    with tempfile.TemporaryDirectory(
        prefix="internet_monitor_report_"
    ) as temp_dir:

        icmp_png = os.path.join(
            temp_dir,
            "icmp_latency.png",
        )

        speed_png = os.path.join(
            temp_dir,
            "speedtest.png",
        )

        latency_png = os.path.join(
            temp_dir,
            "speedtest_latency.png",
        )

        has_icmp = make_icmp_chart(
            ping_rows,
            icmp_png,
        )

        has_speed = make_speed_chart(
            speed_rows,
            speed_png,
        )

        has_latency = (
            make_speed_latency_chart(
                speed_rows,
                latency_png,
            )
        )

        # --------------------------------------------------------------
        # PDF styles
        # --------------------------------------------------------------

        styles = (
            getSampleStyleSheet()
        )

        styles.add(
            ParagraphStyle(
                name="TitleCenter",
                parent=styles["Title"],
                alignment=TA_CENTER,
                fontSize=20,
                leading=24,
                textColor=BLUE_DARK,
                spaceAfter=8,
            )
        )

        styles.add(
            ParagraphStyle(
                name="SubCenter",
                parent=styles["Normal"],
                alignment=TA_CENTER,
                fontSize=9,
                textColor=TEXT_GREY,
                spaceAfter=12,
            )
        )

        styles.add(
            ParagraphStyle(
                name="H1x",
                parent=styles["Heading1"],
                fontSize=13,
                leading=16,
                textColor=BLUE_DARK,
                spaceBefore=8,
                spaceAfter=7,
            )
        )

        styles.add(
            ParagraphStyle(
                name="Small",
                parent=styles["Normal"],
                fontSize=7.5,
                leading=10,
                textColor=TEXT_DARK,
            )
        )

        styles.add(
            ParagraphStyle(
                name="Summary",
                parent=styles["Normal"],
                fontSize=9,
                leading=13,
                textColor=TEXT_DARK,
            )
        )

        # --------------------------------------------------------------
        # Document
        # --------------------------------------------------------------

        document = SimpleDocTemplate(
            pdf_path,
            pagesize=A4,
            rightMargin=15 * mm,
            leftMargin=15 * mm,
            topMargin=14 * mm,
            bottomMargin=15 * mm,
            title=(
                f"Internet Monitor Report "
                f"{VERSION}"
            ),
            author="Internet Monitor",
        )

        story = []

        # ==============================================================
        # COVER / EXECUTIVE SUMMARY
        # ==============================================================

        # Cover logo
        story.append(
            Spacer(
                1,
                3 * mm,
            )
        )

        story.append(
            LogoFlowable(
                width=70 * mm,
            )
        )

        story.append(
            Spacer(
                1,
                2 * mm,
            )
        )

        story.append(
            Paragraph(
                "INTERNET CONNECTIVITY",
                styles["TitleCenter"],
            )
        )

        story.append(
            Paragraph(
                "MONITORING REPORT",
                styles["TitleCenter"],
            )
        )

        story.append(
            Paragraph(
                f"Report version {VERSION}",
                styles["SubCenter"],
            )
        )

        period_data = [
            [
                "Monitoring period",
                "",
            ],
            [
                "Start (UTC)",
                utc_display(start),
            ],
            [
                "End (UTC)",
                utc_display(end),
            ],
            [
                "Duration",
                fmt_duration(duration),
            ],
            [
                "Database",
                os.path.basename(db_path),
            ],
        ]

        story.append(
            make_table(
                period_data,
                widths=[
                    42 * mm,
                    138 * mm,
                ],
                font_size=8,
            )
        )

        story.append(
            Spacer(
                1,
                6 * mm,
            )
        )

        story.append(
            Paragraph(
                "Executive Summary",
                styles["H1x"],
            )
        )

        if (
            internet_loss == 0
            and not target_intervals
            and not internet_intervals
        ):

            headline = (
                "No confirmed internet connectivity "
                "degradation was detected during the "
                "monitoring period."
            )

        elif (
            target_intervals
            or internet_intervals
        ):

            headline = (
                f"The monitoring period contains "
                f"{len(target_intervals)} confirmed "
                f"target connectivity interval(s) "
                f"and "
                f"{len(internet_intervals)} confirmed "
                f"non-NORMAL internet state interval(s)."
            )

        else:

            headline = (
                "No confirmed connectivity-loss interval "
                "was recorded, although measured packet "
                "loss was non-zero."
            )

        story.append(
            Paragraph(
                headline,
                styles["Summary"],
            )
        )

        story.append(
            Spacer(
                1,
                3 * mm,
            )
        )

        total_dns = sum(
            row[1]
            for row in dns_rows
        )

        successful_dns = sum(
            row[2]
            for row in dns_rows
        )

        total_https = sum(
            row[1]
            for row in https_rows
        )

        successful_https = sum(
            row[2]
            for row in https_rows
        )

        # --------------------------------------------------------------
        # Executive Summary table
        # --------------------------------------------------------------

        summary_data = [
            [
                "Metric",
                "Result",
                "Interpretation",
            ],
            [
                "Internet ICMP loss",
                f"{internet_loss:.3f}%",
                "Aggregate loss across internet ICMP targets",
            ],
            [
                "Internet ICMP availability",
                f"{internet_availability:.3f}%",
                "Successful ICMP probes",
            ],
            [
                "Confirmed target loss events",
                str(len(target_intervals)),
                "Closed intervals only",
            ],
            [
                "Confirmed degraded intervals",
                str(len(internet_intervals)),
                "Closed non-NORMAL internet states",
            ],
            [
                "DNS success",
                (
                    f"{successful_dns}/{total_dns}"
                    if total_dns
                    else "-"
                ),
                "All configured DNS checks",
            ],
            [
                "HTTPS / DoH success",
                (
                    f"{successful_https}/{total_https}"
                    if total_https
                    else "-"
                ),
                "All configured HTTPS / DoH checks",
            ],
            [
                "Speedtests",
                (
                    f"{len(successful_speed)}"
                    f"/{len(speed_rows)}"
                ),
                "Successful speedtest runs",
            ],
            [
                "Average download",
                (
                    f"{mean(download_values):.2f} Mbps"
                    if download_values
                    else "-"
                ),
                "Average successful speedtests",
            ],
            [
                "Average upload",
                (
                    f"{mean(upload_values):.2f} Mbps"
                    if upload_values
                    else "-"
                ),
                "Average successful speedtests",
            ],
            [
                "Average idle latency",
                (
                    f"{mean(idle_values):.2f} ms"
                    if idle_values
                    else "-"
                ),
                "Speedtest idle latency",
            ],
            [
                "Average jitter",
                (
                    f"{mean(jitter_values):.2f} ms"
                    if jitter_values
                    else "-"
                ),
                "Speedtest idle jitter",
            ],
        ]

        story.append(
            make_table(
                summary_data,
                widths=[
                    48 * mm,
                    40 * mm,
                    92 * mm,
                ],
                font_size=8,
            )
        )

        story.append(
            Spacer(
                1,
                4 * mm,
            )
        )

        story.append(
            Paragraph(
                "The summary describes measured observations only. "
                "It does not establish the root cause of any "
                "connectivity problem or assign responsibility "
                "to a network provider.",
                styles["Small"],
            )
        )

        story.append(
            PageBreak()
        )

        # ==============================================================
        # ICMP
        # ==============================================================

        story.append(
            Paragraph(
                "ICMP Connectivity",
                styles["H1x"],
            )
        )

        ping_data = [
            [
                "Target",
                "Packets",
                "Success",
                "Loss",
                "Availability",
                "Avg latency",
            ]
        ]

        target_order = (
            ["gateway"]
            +
            [
                target
                for target in ping_summary
                if target != "gateway"
            ]
        )

        for target in target_order:

            if target not in ping_summary:
                continue

            item = ping_summary[target]

            ping_data.append(
                [
                    target,
                    str(item["packets"]),
                    str(item["success"]),
                    f"{item['loss']:.3f}%",
                    f"{item['availability']:.3f}%",
                    (
                        f"{item['avg']:.2f} ms"
                        if item["avg"] is not None
                        else "-"
                    ),
                ]
            )

        story.append(
            make_table(
                ping_data,
                widths=[
                    32 * mm,
                    25 * mm,
                    25 * mm,
                    25 * mm,
                    31 * mm,
                    32 * mm,
                ],
                font_size=7.5,
            )
        )

        story.append(
            Spacer(
                1,
                5 * mm,
            )
        )

        if has_icmp:

            story.append(
                Image(
                    icmp_png,
                    width=178 * mm,
                    height=76 * mm,
                )
            )

            story.append(
                Paragraph(
                    "The chart shows the recorded average latency "
                    "of each ICMP measurement cycle. "
                    "All timestamps are UTC.",
                    styles["Small"],
                )
            )

        story.append(
            PageBreak()
        )

        # ==============================================================
        # EVENTS
        # ==============================================================

        story.append(
            Paragraph(
                "Confirmed Connectivity Events",
                styles["H1x"],
            )
        )

        if target_intervals:

            data = [
                [
                    "Target",
                    "State",
                    "Start (UTC)",
                    "End (UTC)",
                    "Duration",
                ]
            ]

            for (
                target,
                state,
                start_ts,
                end_ts,
            ) in target_intervals:

                try:

                    start_dt = datetime.fromisoformat(
                        start_ts.replace(
                            "Z",
                            "+00:00",
                        )
                    )

                    end_dt = datetime.fromisoformat(
                        end_ts.replace(
                            "Z",
                            "+00:00",
                        )
                    )

                    event_duration = (
                        end_dt
                        -
                        start_dt
                    ).total_seconds()

                except Exception:

                    event_duration = None

                data.append(
                    [
                        target,
                        state,
                        utc_display(start_ts),
                        utc_display(end_ts),
                        fmt_duration(
                            event_duration
                        ),
                    ]
                )

            story.append(
                make_table(
                    data,
                    widths=[
                        28 * mm,
                        25 * mm,
                        48 * mm,
                        48 * mm,
                        28 * mm,
                    ],
                    font_size=6.8,
                )
            )

        else:

            story.append(
                Paragraph(
                    "No confirmed target connectivity-loss "
                    "events were recorded during this "
                    "monitoring period.",
                    styles["Summary"],
                )
            )

        story.append(
            Spacer(
                1,
                6 * mm,
            )
        )

        story.append(
            Paragraph(
                "Internet State Events",
                styles["H1x"],
            )
        )

        if internet_intervals:

            data = [
                [
                    "State",
                    "Start (UTC)",
                    "End (UTC)",
                    "Duration",
                ]
            ]

            for (
                state,
                start_ts,
                end_ts,
            ) in internet_intervals:

                try:

                    start_dt = datetime.fromisoformat(
                        start_ts.replace(
                            "Z",
                            "+00:00",
                        )
                    )

                    end_dt = datetime.fromisoformat(
                        end_ts.replace(
                            "Z",
                            "+00:00",
                        )
                    )

                    event_duration = (
                        end_dt
                        -
                        start_dt
                    ).total_seconds()

                except Exception:

                    event_duration = None

                data.append(
                    [
                        state,
                        utc_display(start_ts),
                        utc_display(end_ts),
                        fmt_duration(
                            event_duration
                        ),
                    ]
                )

            story.append(
                make_table(
                    data,
                    widths=[
                        35 * mm,
                        55 * mm,
                        55 * mm,
                        35 * mm,
                    ],
                    font_size=7.2,
                )
            )

        else:

            story.append(
                Paragraph(
                    "No non-NORMAL internet state "
                    "intervals were recorded.",
                    styles["Summary"],
                )
            )

        if (
            open_targets
            or open_internet
        ):

            story.append(
                Spacer(
                    1,
                    4 * mm,
                )
            )

            story.append(
                Paragraph(
                    "Open events were present at database end "
                    "and are therefore not included in confirmed "
                    "duration totals.",
                    styles["Small"],
                )
            )

        # ==============================================================
        # DNS
        # ==============================================================

        story.append(
            Paragraph(
                "DNS Monitoring",
                styles["H1x"],
            )
        )

        if dns_rows:

            data = [
                [
                    "Target",
                    "Tests",
                    "Successful",
                    "Failed",
                    "Success rate",
                ]
            ]

            for (
                target,
                total,
                success,
                failed,
            ) in dns_rows:

                rate = (
                    success
                    /
                    total
                    *
                    100
                    if total
                    else 0
                )

                data.append(
                    [
                        target,
                        str(total),
                        str(success),
                        str(failed),
                        f"{rate:.1f}%",
                    ]
                )

            story.append(
                make_table(
                    data,
                    widths=[
                        55 * mm,
                        30 * mm,
                        30 * mm,
                        30 * mm,
                        35 * mm,
                    ],
                    font_size=7.5,
                )
            )

        else:

            story.append(
                Paragraph(
                    "No DNS measurements were found.",
                    styles["Summary"],
                )
            )

        # ==============================================================
        # HTTPS / DoH
        # ==============================================================

        story.append(
            Paragraph(
                "HTTPS / DoH Monitoring",
                styles["H1x"],
            )
        )

        if https_rows:

            data = [
                [
                    "Target",
                    "Tests",
                    "Successful",
                    "Success rate",
                    "Avg",
                    "Min",
                    "Max",
                ]
            ]

            for (
                target,
                total,
                success,
                failed,
                average,
                minimum,
                maximum,
            ) in https_rows:

                rate = (
                    success
                    /
                    total
                    *
                    100
                    if total
                    else 0
                )

                data.append(
                    [
                        target,
                        str(total),
                        str(success),
                        f"{rate:.1f}%",
                        (
                            f"{average:.1f} ms"
                            if average is not None
                            else "-"
                        ),
                        (
                            f"{minimum:.1f} ms"
                            if minimum is not None
                            else "-"
                        ),
                        (
                            f"{maximum:.1f} ms"
                            if maximum is not None
                            else "-"
                        ),
                    ]
                )

            # Exactly 180 mm: same usable width as all other full-width tables.
            story.append(
                make_table(
                    data,
                    widths=[
                        38 * mm,
                        22 * mm,
                        27 * mm,
                        28 * mm,
                        21 * mm,
                        22 * mm,
                        22 * mm,
                    ],
                    font_size=6.9,
                )
            )

        else:

            story.append(
                Paragraph(
                    "No HTTPS / DoH measurements were found.",
                    styles["Summary"],
                )
            )

        story.append(
            PageBreak()
        )

        # ==============================================================
        # SPEEDTEST ANALYSIS
        # ==============================================================

        story.append(
            Paragraph(
                "Speedtest Analysis",
                styles["H1x"],
            )
        )

        if successful_speed:

            story.append(
                Paragraph(
                    (
                        f"{len(successful_speed)} successful "
                        f"speedtests were recorded. "
                        f"Download ranged from "
                        f"{min(download_values):.1f} to "
                        f"{max(download_values):.1f} Mbps; "
                        f"upload ranged from "
                        f"{min(upload_values):.1f} to "
                        f"{max(upload_values):.1f} Mbps."
                    ),
                    styles["Summary"],
                )
            )

            story.append(
                Spacer(
                    1,
                    4 * mm,
                )
            )

            if has_speed:

                story.append(
                    Image(
                        speed_png,
                        width=178 * mm,
                        height=76 * mm,
                    )
                )

            story.append(
                Spacer(
                    1,
                    4 * mm,
                )
            )

            if has_latency:

                story.append(
                    Image(
                        latency_png,
                        width=178 * mm,
                        height=76 * mm,
                    )
                )

        else:

            story.append(
                Paragraph(
                    "No successful speedtest measurements "
                    "were found.",
                    styles["Summary"],
                )
            )

        # ==============================================================
        # FULL SPEEDTEST TABLE
        #
        # Only included with -v
        # ==============================================================

        if VERBOSE:

            story.append(
                PageBreak()
            )

            story.append(
                Paragraph(
                    "Speedtest Results",
                    styles["H1x"],
                )
            )

            if speed_rows:

                data = [
                    [
                        "Time (UTC)",
                        "Server",
                        "Download",
                        "Upload",
                        "Idle",
                        "Jitter",
                        "Loss",
                    ]
                ]

                for row in speed_rows:

                    (
                        timestamp,
                        server,
                        download,
                        upload,
                        idle,
                        jitter,
                        loss,
                        success,
                        error,
                    ) = row

                    if success:

                        data.append(
                            [
                                time_display(
                                    timestamp
                                ),
                                server or "-",
                                (
                                    f"{download:.1f}"
                                    if download is not None
                                    else "-"
                                ),
                                (
                                    f"{upload:.1f}"
                                    if upload is not None
                                    else "-"
                                ),
                                (
                                    f"{idle:.1f}"
                                    if idle is not None
                                    else "-"
                                ),
                                (
                                    f"{jitter:.2f}"
                                    if jitter is not None
                                    else "-"
                                ),
                                (
                                    f"{loss:.2f}%"
                                    if loss is not None
                                    else "-"
                                ),
                            ]
                        )

                    else:

                        data.append(
                            [
                                time_display(
                                    timestamp
                                ),
                                server or "-",
                                "FAILED",
                                "-",
                                "-",
                                "-",
                                "-",
                            ]
                        )

                story.append(
                    make_table(
                        data,
                        widths=[
                            22 * mm,
                            43 * mm,
                            27 * mm,
                            25 * mm,
                            23 * mm,
                            23 * mm,
                            22 * mm,
                        ],
                        font_size=6.5,
                    )
                )

                story.append(
                    Spacer(
                        1,
                        4 * mm,
                    )
                )

                if successful_speed:

                    story.append(
                        Paragraph(
                            (
                                f"Average download: "
                                f"{mean(download_values):.2f} Mbps<br/>"
                                f"Average upload: "
                                f"{mean(upload_values):.2f} Mbps<br/>"
                                f"Average idle latency: "
                                f"{mean(idle_values):.2f} ms<br/>"
                                f"Average idle jitter: "
                                f"{mean(jitter_values):.2f} ms<br/>"
                                f"Average reported packet loss: "
                                f"{mean(speed_loss_values):.2f}%"
                            ),
                            styles["Small"],
                        )
                    )

            else:

                story.append(
                    Paragraph(
                        "No speedtest measurements were found.",
                        styles["Summary"],
                    )
                )

        # ==============================================================
        # TECHNICAL OBSERVATIONS
        # ==============================================================

        story.append(
            PageBreak()
        )

        story.append(
            Paragraph(
                "Technical Observations",
                styles["H1x"],
            )
        )

        observations = []

        if "gateway" in ping_summary:

            gateway = ping_summary[
                "gateway"
            ]

            if gateway["avg"] is not None:

                observations.append(
                    (
                        f"Packet loss to the local gateway "
                        f"was {gateway['loss']:.3f}%, with "
                        f"average ICMP latency of "
                        f"{gateway['avg']:.2f} ms."
                    )
                )

            else:

                observations.append(
                    (
                        f"Packet loss to the local gateway "
                        f"was {gateway['loss']:.3f}%."
                    )
                )

        observations.append(
            (
                f"The monitored internet ICMP targets "
                f"recorded {internet_loss:.3f}% aggregate "
                f"packet loss and "
                f"{internet_availability:.3f}% availability."
            )
        )

        if successful_speed:

            observations.append(
                (
                    f"Successful speedtests averaged "
                    f"{mean(download_values):.2f} Mbps "
                    f"download and "
                    f"{mean(upload_values):.2f} Mbps upload."
                )
            )

            if (
                max(download_values)
                -
                min(download_values)
                > 0
            ):

                observations.append(
                    (
                        f"Observed download speed range was "
                        f"{min(download_values):.1f}–"
                        f"{max(download_values):.1f} Mbps."
                    )
                )

        if (
            target_intervals
            or internet_intervals
        ):

            observations.append(
                (
                    f"The event parser identified "
                    f"{len(target_intervals)} confirmed "
                    f"target interval(s) and "
                    f"{len(internet_intervals)} confirmed "
                    f"internet-state interval(s)."
                )
            )

        else:

            observations.append(
                (
                    "No confirmed connectivity-loss or "
                    "non-NORMAL internet-state interval "
                    "was recorded."
                )
            )

        observations.append(
            (
                "ICMP packet loss, DNS failures, HTTPS "
                "results and speed measurements are "
                "observations recorded by the monitoring "
                "system. They do not by themselves establish "
                "the root cause of a connectivity problem or "
                "identify a particular provider as responsible."
            )
        )

        for observation in observations:

            story.append(
                Paragraph(
                    "• " + observation,
                    styles["Summary"],
                )
            )

            story.append(
                Spacer(
                    1,
                    2 * mm,
                )
            )

        story.append(
            Spacer(
                1,
                4 * mm,
            )
        )

        story.append(
            Paragraph(
                "Data Source",
                styles["H1x"],
            )
        )

        story.append(
            Paragraph(
                "This report was generated directly from "
                "the SQLite database produced by the Internet "
                "Monitor. The underlying measurement database "
                "is retained separately and can be used for "
                "further analysis.",
                styles["Summary"],
            )
        )

        # --------------------------------------------------------------
        # Build PDF
        # --------------------------------------------------------------

        document.build(
            story,
            canvasmaker=NumberedCanvas,
        )

    conn.close()

    print(
        f"Report generated: {pdf_path}"
    )


if __name__ == "__main__":
    main()

