"""Email notification support for watch/scheduled mode.

Sends a formatted HTML email with the top waiver wire recommendations
after a scheduled analysis run.  Uses SMTP (Gmail App Password recommended).

Configuration (via .env):
    NOTIFY_EMAIL_TO       Recipient email address
    NOTIFY_EMAIL_FROM     Sender email address (defaults to NOTIFY_EMAIL_TO)
    NOTIFY_SMTP_HOST      SMTP server hostname (default: smtp.gmail.com)
    NOTIFY_SMTP_PORT      SMTP port (default: 587, TLS)
    NOTIFY_SMTP_PASSWORD  SMTP password / Gmail App Password

Usage:
    from src.notifier import send_email_report
    send_email_report(rec_df, schedule_analysis=schedule_analysis)
"""

from __future__ import annotations

import os
import smtplib
import ssl
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def _get_email_config() -> dict:
    """Read email notification settings from environment variables."""
    to_addr = os.environ.get("NOTIFY_EMAIL_TO", "")
    from_addr = os.environ.get("NOTIFY_EMAIL_FROM", "") or to_addr
    smtp_host = os.environ.get("NOTIFY_SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("NOTIFY_SMTP_PORT", "587"))
    smtp_password = os.environ.get("NOTIFY_SMTP_PASSWORD", "")
    return {
        "to": to_addr,
        "from": from_addr,
        "host": smtp_host,
        "port": smtp_port,
        "password": smtp_password,
    }


def email_configured() -> bool:
    """Return True if enough env vars are set to send email."""
    cfg = _get_email_config()
    return bool(cfg["to"] and cfg["password"])


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

_INJURY_COLORS = {
    "OUT-SEASON": "#dc3545",
    "OUT": "#dc3545",
    "SUSP": "#dc3545",
    "DTD": "#ffc107",
}


def _format_html_report(
    rec_df: "pd.DataFrame",
    schedule_analysis: dict | None = None,
    top_n: int = 15,
    mode: str = "watch",
    il_action: dict | None = None,
) -> str:
    """Build an HTML email body from the recommendation DataFrame."""
    now = datetime.now().strftime("%A %B %d, %Y at %I:%M %p")
    rows = rec_df.head(top_n)

    # Mode-specific header
    if mode == "stream":
        title = "🏀 Streaming Picks — Today's Games"
        subtitle = f"Best available players with a game today — {now}"
        footer_note = "Streaming mode: daily add/drop for players with games today."
    else:
        title = "🏀 NBA Fantasy Advisor"
        subtitle = f"Waiver Wire Report — {now}"
        footer_note = "Adj_Score = Z × needs × availability × injury × schedule + recency + trending"

    # Determine which columns to include
    has_injury = "Injury" in rows.columns
    has_games = "Games_Wk" in rows.columns
    has_hot = "Hot" in rows.columns
    has_trending = "Trending" in rows.columns

    # Build table header
    header_cols = ["#", "Player", "Team", "Z_Value", "Adj_Score"]
    if has_games:
        header_cols.append("Games")
    if has_injury:
        header_cols.append("Injury")
    if has_hot:
        header_cols.append("")
    if has_trending:
        header_cols.append("")

    header_html = "".join(f"<th style='padding:6px 10px;text-align:left;border-bottom:2px solid #333;'>{c}</th>" for c in header_cols)

    # Build table rows
    body_rows = []
    for i, (_, row) in enumerate(rows.iterrows(), 1):
        player = row.get("Player", row.get("PLAYER_NAME", ""))
        team = row.get("Team", row.get("TEAM_ABBREVIATION", ""))
        z_val = row.get("Z_Value", row.get("Z_Total", 0))
        adj = row.get("Adj_Score", 0)
        injury = row.get("Injury", "-") if has_injury else "-"
        games = row.get("Games_Wk", "") if has_games else ""
        hot = row.get("Hot", "") if has_hot else ""
        trending = row.get("Trending", "") if has_trending else ""

        # Color the injury badge
        injury_str = str(injury) if injury and str(injury) != "-" else ""
        inj_color = _INJURY_COLORS.get(injury_str, "#6c757d")
        inj_badge = (
            f"<span style='background:{inj_color};color:#fff;padding:2px 6px;"
            f"border-radius:3px;font-size:11px;'>{injury_str}</span>"
            if injury_str else "-"
        )

        # Color the adj_score
        if adj >= 1.5:
            score_color = "#28a745"
        elif adj >= 0.5:
            score_color = "#218838"
        else:
            score_color = "#6c757d"

        # Flags
        flags = ""
        if hot and str(hot).strip():
            flags += " 🔥"
        if trending and str(trending).strip():
            flags += " 📈"

        bg = "#f8f9fa" if i % 2 == 0 else "#ffffff"
        td = f"style='padding:6px 10px;border-bottom:1px solid #dee2e6;background:{bg};'"

        cells = [
            f"<td {td}>{i}</td>",
            f"<td {td}><strong>{player}</strong>{flags}</td>",
            f"<td {td}>{team}</td>",
            f"<td {td}>{z_val:+.2f}</td>" if isinstance(z_val, (int, float)) else f"<td {td}>{z_val}</td>",
            f"<td {td}><span style='color:{score_color};font-weight:bold;'>{adj:.2f}</span></td>",
        ]
        if has_games:
            cells.append(f"<td {td}>{games}</td>")
        if has_injury:
            cells.append(f"<td {td}>{inj_badge}</td>")

        body_rows.append(f"<tr>{''.join(cells)}</tr>")

    table_html = body_rows_html = "\n".join(body_rows)

    # Schedule summary
    sched_summary = ""
    if schedule_analysis and schedule_analysis.get("weeks"):
        wk = schedule_analysis["weeks"][0]
        sched_summary = (
            f"<p style='color:#666;font-size:13px;'>"
            f"📅 Week {wk.get('week', '?')}: {wk.get('start_date', '?')} – {wk.get('end_date', '?')} "
            f"| Avg {schedule_analysis.get('avg_games_per_week', '?')} games/team</p>"
        )

    # IL action banner (streaming mode)
    il_banner = ""
    if il_action and mode == "stream":
        if il_action["strategy"] == "drop_regular":
            il_banner = (
                f"<div style='background:#fff3cd;border:1px solid #ffc107;border-radius:6px;"
                f"padding:12px 16px;margin:10px 0;'>"
                f"<strong>⚠️ IL/IL+ Action Required</strong><br>"
                f"<span style='color:#155724;font-weight:bold;'>ACTIVATE</span> "
                f"{il_action['il_player']} (z: {il_action['il_z']:+.2f}) from {il_action['slot']}<br>"
                f"<span style='color:#dc3545;font-weight:bold;'>DROP</span> "
                f"{il_action['drop_player']} (z: {il_action['drop_z']:+.2f})<br>"
                f"<em style='font-size:12px;color:#856404;'>IL player returning is a roster "
                f"upgrade — no streaming add needed today.</em>"
                f"</div>"
            )
        else:
            il_banner = (
                f"<div style='background:#f8d7da;border:1px solid #f5c6cb;border-radius:6px;"
                f"padding:12px 16px;margin:10px 0;'>"
                f"<strong>⚠️ IL/IL+ Action Required</strong><br>"
                f"<span style='color:#dc3545;font-weight:bold;'>DROP</span> "
                f"{il_action['il_player']} (z: {il_action['il_z']:+.2f}) "
                f"from {il_action['slot']} to clear violation, then stream normally."
                f"</div>"
            )

    html = f"""
    <html>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 700px; margin: 0 auto; padding: 20px;">
        <div style="background: linear-gradient(135deg, #1a1a2e, #16213e); color: #fff; padding: 20px 25px; border-radius: 8px 8px 0 0;">
            <h2 style="margin: 0 0 5px 0;">{title}</h2>
            <p style="margin: 0; color: #a0aec0; font-size: 14px;">{subtitle}</p>
        </div>

        {sched_summary}
        {il_banner}

        <table style="width:100%;border-collapse:collapse;font-size:14px;margin-top:10px;">
            <thead><tr style="background:#e9ecef;">{header_html}</tr></thead>
            <tbody>
                {table_html}
            </tbody>
        </table>

        <p style="color:#999;font-size:12px;margin-top:20px;">
            Generated by <strong>NBA Fantasy Advisor</strong> (v2) — automated {mode} mode.
            <br>{footer_note}
        </p>
    </body>
    </html>
    """
    return html


def _format_plain_report(
    rec_df: "pd.DataFrame",
    top_n: int = 15,
) -> str:
    """Build a plain-text fallback for the email."""
    now = datetime.now().strftime("%A %B %d, %Y at %I:%M %p")
    lines = [
        "NBA Fantasy Advisor - Waiver Wire Report",
        f"Generated: {now}",
        "",
        f"{'#':<4} {'Player':<22} {'Team':<5} {'Z':>6} {'Score':>7} {'Injury':<8}",
        "-" * 56,
    ]
    for i, (_, row) in enumerate(rec_df.head(top_n).iterrows(), 1):
        player = str(row.get("Player", row.get("PLAYER_NAME", "")))[:20]
        team = str(row.get("Team", row.get("TEAM_ABBREVIATION", "")))
        z_val = row.get("Z_Value", row.get("Z_Total", 0))
        adj = row.get("Adj_Score", 0)
        injury = row.get("Injury", "-")
        z_str = f"{z_val:+.2f}" if isinstance(z_val, (int, float)) else str(z_val)
        lines.append(f"{i:<4} {player:<22} {team:<5} {z_str:>6} {adj:>7.2f} {injury or '-':<8}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------

def send_email_report(
    rec_df: "pd.DataFrame",
    schedule_analysis: dict | None = None,
    top_n: int = 15,
    mode: str = "watch",
    il_action: dict | None = None,
) -> bool:
    """Send the recommendation report via email.

    Args:
        rec_df: Recommendation DataFrame.
        schedule_analysis: Optional schedule data for header context.
        top_n: Number of recommendations to include.
        mode: Report type — ``"watch"`` (full waiver) or ``"stream"`` (today's games).
        il_action: Optional IL resolution recommendation dict from streaming analysis.

    Returns True on success, False on failure (prints error to stderr).
    """
    cfg = _get_email_config()
    if not cfg["to"] or not cfg["password"]:
        print("  ✗ Email not configured — set NOTIFY_EMAIL_TO and NOTIFY_SMTP_PASSWORD in .env")
        return False

    # Auto-extract il_action from DataFrame attrs if not explicitly provided
    if il_action is None and hasattr(rec_df, "attrs"):
        il_action = rec_df.attrs.get("il_action")

    html_body = _format_html_report(rec_df, schedule_analysis, top_n, mode=mode, il_action=il_action)
    text_body = _format_plain_report(rec_df, top_n)

    now = datetime.now().strftime("%b %d")
    if mode == "stream":
        subject = f"🏀 Streaming Picks — {now}"
    else:
        subject = f"🏀 Waiver Wire Report — {now}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["from"]
    msg["To"] = cfg["to"]
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as server:
            server.starttls(context=context)
            server.login(cfg["from"], cfg["password"])
            server.sendmail(cfg["from"], [cfg["to"]], msg.as_string())
        print(f"  ✓ Email sent to {cfg['to']}")
        return True
    except smtplib.SMTPAuthenticationError:
        print(f"  ✗ SMTP authentication failed — check NOTIFY_SMTP_PASSWORD (use a Gmail App Password, not your account password)")
        return False
    except Exception as e:
        print(f"  ✗ Failed to send email: {e}")
        return False
