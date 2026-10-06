#!/bin/bash
BASE_DIR="/opt/internet-monitor"
REPORT_SCRIPT="$BASE_DIR/report.py"
ANALYZE_SCRIPT="$BASE_DIR/analyze.py"
MAIL_TO="your@email.com"

echo "=== Internet Monitor report ==="
echo "Start: $(date)"

# 1. Find the latest database ===============================================================================================
DB=$(find "$BASE_DIR" -maxdepth 1 -type f -name 'monitor_*.db' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)
if [ -z "$DB" ]; then
    echo "ERROR: No monitor_*.db database found."
    exit 1
fi
echo "Selected database: $DB"

# 2. Generate report ========================================================================================================
echo "Generating report..."
if ! python3 "$REPORT_SCRIPT" "$DB"; then
    echo "ERROR: Report generation failed."
    exit 1
fi

# 3. Check PDF ==============================================================================================================
DB_NAME=$(basename "$DB" .db)
PDF="$BASE_DIR/reports/${DB_NAME}_report.pdf"
if [ ! -f "$PDF" ]; then
    echo "ERROR: PDF was not created: $PDF"
    exit 1
fi
echo "PDF created: $PDF"
echo "PDF size: $(du -h "$PDF" | cut -f1)"

# 4. Generate analysis ======================================================================================================
echo "Generating analysis..."
STATUS_OUTPUT=$(python3 "$ANALYZE_SCRIPT" "$DB")
# echo "$STATUS_OUTPUT"

# 5. Send email =============================================================================================================
echo "Sending email to: $MAIL_TO"
(
    echo "To: $MAIL_TO"
    echo "Subject: Internet Monitor report - $DB_NAME"
    echo "MIME-Version: 1.0"
    echo 'Content-Type: multipart/mixed; boundary="BOUNDARY"'
    echo
    echo "--BOUNDARY"
    echo 'Content-Type: text/plain; charset="UTF-8"'
    echo
    echo "Automatically generated Internet Monitor report."
    echo
    echo "Database: $DB_NAME"
    echo "Generated: $(date)"
    echo
    echo
    echo
    echo "$STATUS_OUTPUT"
    echo
    echo
    echo
    echo "--BOUNDARY"
    echo 'Content-Type: application/pdf; name="Internet_Monitor_report.pdf"'
    echo 'Content-Disposition: attachment; filename="Internet_Monitor_report.pdf"'
    echo "Content-Transfer-Encoding: base64"
    echo
    base64 "$PDF"
    echo
    echo "--BOUNDARY--"
) | sendmail -t

# 6. Report success status ==================================================================================================
if [ $? -eq 0 ]; then
    echo "Email successfully handed over to sendmail."
else
    echo "ERROR: Email sending failed."
    exit 1
fi

echo "Finished: $(date)"
echo "=== DONE ==="
