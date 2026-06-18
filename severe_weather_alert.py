#!/usr/bin/env python3
"""
Severe weather email alert for the greater Indianapolis metro area.

Runs on a schedule (e.g. GitHub Actions cron), checks the National Weather
Service API for active alerts and the short-term forecast, and emails you
ONLY when severe weather, rain, or snow is coming. Silent on clear days.

Configuration is via environment variables (see the README). The only
required ones are the three email secrets:
    GMAIL_USER, GMAIL_APP_PASSWORD, ALERT_TO
"""

import os
import sys
import json
import time
import smtplib
import urllib.request
import urllib.error
from datetime import datetime, timezone
from email.message import EmailMessage

# --------------------------------------------------------------------------
# Configuration (override any of these with environment variables)
# --------------------------------------------------------------------------
LAT = os.environ.get("WX_LAT", "39.7684")          # downtown Indianapolis
LON = os.environ.get("WX_LON", "-86.1581")
STATE = os.environ.get("WX_STATE", "IN")

# Counties that make up the greater Indianapolis metro. An alert is included
# if its area description mentions any of these. Edit to taste.
COUNTIES = [c.strip().lower() for c in os.environ.get(
    "WX_COUNTIES",
    "Marion,Hamilton,Hendricks,Boone,Hancock,Johnson,Morgan,Shelby,Madison",
).split(",") if c.strip()]

# Forecast lookahead and the precip probability that counts as "rain/snow".
HOURS_AHEAD = int(os.environ.get("WX_HOURS_AHEAD", "36"))
PRECIP_THRESHOLD = int(os.environ.get("WX_PRECIP_THRESHOLD", "50"))  # percent

# Words in a forecast that mean precipitation worth flagging.
PRECIP_WORDS = ["rain", "snow", "shower", "thunderstorm", "sleet",
                "freezing", "wintry", "blizzard", "flurr", "drizzle", "ice"]

# Send an email even when there is nothing to report (handy for a one-time
# "is this working?" test). Set WX_ALWAYS_SEND=1 to enable.
ALWAYS_SEND = os.environ.get("WX_ALWAYS_SEND", "0") == "1"

# Email
GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
ALERT_TO = [a.strip() for a in os.environ.get("ALERT_TO", "").split(",") if a.strip()]
ALERT_FROM = os.environ.get("ALERT_FROM", GMAIL_USER)

# NWS requires a descriptive User-Agent with a contact. Override if you like.
USER_AGENT = os.environ.get(
    "WX_USER_AGENT",
    "indy-severe-weather-alert/1.0 (%s)" % (GMAIL_USER or "anonymous@example.com"),
)
PLACE_NAME = os.environ.get("WX_PLACE_NAME", "Greater Indianapolis")


# --------------------------------------------------------------------------
# NWS API helpers
# --------------------------------------------------------------------------
def api_get(url, retries=3, backoff=3):
    """GET a NWS API URL, returning parsed JSON. Retries on transient errors."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/geo+json"}
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
    raise RuntimeError("NWS request failed after %d tries: %s\n%s"
                       % (retries, url, last_err))


def get_forecast_url():
    """Resolve the forecast URL for the configured point."""
    data = api_get("https://api.weather.gov/points/%s,%s" % (LAT, LON))
    return data["properties"]["forecast"]


def get_active_alerts():
    """Return alerts for the state, filtered to our metro counties."""
    data = api_get("https://api.weather.gov/alerts/active?area=%s" % STATE)
    out = []
    for feat in data.get("features", []):
        p = feat.get("properties", {})
        area = (p.get("areaDesc") or "").lower()
        if COUNTIES and not any(county in area for county in COUNTIES):
            continue
        out.append({
            "event": p.get("event", "Weather alert"),
            "severity": p.get("severity", ""),
            "headline": p.get("headline", ""),
            "area": p.get("areaDesc", ""),
            "onset": p.get("onset") or p.get("effective", ""),
            "expires": p.get("expires", ""),
            "description": (p.get("description") or "").strip(),
            "instruction": (p.get("instruction") or "").strip(),
        })
    # De-duplicate identical events (NWS often splits by zone).
    seen, deduped = set(), []
    for a in out:
        key = (a["event"], a["headline"])
        if key not in seen:
            seen.add(key)
            deduped.append(a)
    return deduped


def get_precip_periods(forecast_url):
    """Return forecast periods within HOURS_AHEAD that look like rain/snow."""
    data = api_get(forecast_url)
    periods = data.get("properties", {}).get("periods", [])
    now = datetime.now(timezone.utc)
    hits = []
    for per in periods:
        try:
            start = datetime.fromisoformat(per["startTime"])
        except Exception:
            start = now
        hours_out = (start - now).total_seconds() / 3600.0
        if hours_out > HOURS_AHEAD:
            continue
        short = (per.get("shortForecast") or "").lower()
        pop = per.get("probabilityOfPrecipitation", {}) or {}
        pop_val = pop.get("value")
        word_hit = any(w in short for w in PRECIP_WORDS)
        pop_hit = isinstance(pop_val, (int, float)) and pop_val >= PRECIP_THRESHOLD
        if word_hit or pop_hit:
            hits.append({
                "name": per.get("name", ""),
                "short": per.get("shortForecast", ""),
                "detailed": per.get("detailedForecast", ""),
                "pop": pop_val,
                "temp": per.get("temperature"),
                "unit": per.get("temperatureUnit", ""),
            })
    return hits


# --------------------------------------------------------------------------
# Email composition
# --------------------------------------------------------------------------
def fmt_time(iso):
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).strftime("%a %b %-d, %-I:%M %p")
    except Exception:
        return iso


def build_email(alerts, precip):
    today = datetime.now().strftime("%b %-d")
    if alerts:
        worst = alerts[0]["event"]
        subject = "⚠️ Weather alert — %s (%s): %s" % (PLACE_NAME, today, worst)
    else:
        subject = "\U0001f327️ Rain/snow expected — %s (%s)" % (PLACE_NAME, today)

    lines = []
    html = ["<div style='font-family:Arial,Helvetica,sans-serif;font-size:15px;color:#1a1a1a'>"]
    html.append("<p style='font-size:17px;font-weight:bold;margin:0 0 6px'>Bad weather is coming — %s</p>" % PLACE_NAME)
    lines.append("Bad weather is coming — %s\n" % PLACE_NAME)

    if alerts:
        lines.append("ACTIVE NWS ALERTS")
        lines.append("=================")
        html.append("<h3 style='margin:14px 0 6px'>Active NWS alerts</h3>")
        for a in alerts:
            lines.append("\n* %s (%s)" % (a["event"], a["severity"] or "n/a"))
            if a["headline"]:
                lines.append("  %s" % a["headline"])
            if a["expires"]:
                lines.append("  In effect until: %s" % fmt_time(a["expires"]))
            if a["area"]:
                lines.append("  Area: %s" % a["area"])
            if a["instruction"]:
                lines.append("  Guidance: %s" % a["instruction"])
            html.append(
                "<div style='border-left:4px solid #c0392b;background:#fbeaea;"
                "padding:8px 12px;margin:8px 0'>"
                "<div style='font-weight:bold;color:#c0392b'>%s (%s)</div>"
                "<div>%s</div>"
                "<div style='color:#555;font-size:13px;margin-top:4px'>In effect until: %s</div>"
                "<div style='color:#555;font-size:13px'>Area: %s</div>"
                "%s</div>" % (
                    a["event"], a["severity"] or "n/a", a["headline"],
                    fmt_time(a["expires"]), a["area"],
                    ("<div style='margin-top:4px'>%s</div>" % a["instruction"]) if a["instruction"] else "",
                )
            )

    if precip:
        lines.append("\nFORECAST — RAIN / SNOW")
        lines.append("=======================")
        html.append("<h3 style='margin:14px 0 6px'>Forecast — rain / snow</h3>")
        for p in precip:
            pop = ("  (%d%% chance)" % p["pop"]) if isinstance(p["pop"], (int, float)) else ""
            temp = (" — %s°%s" % (p["temp"], p["unit"])) if p["temp"] is not None else ""
            lines.append("\n* %s%s: %s%s" % (p["name"], temp, p["short"], pop))
            lines.append("  %s" % p["detailed"])
            html.append(
                "<div style='border-left:4px solid #2c6fbb;background:#eaf1fb;"
                "padding:8px 12px;margin:8px 0'>"
                "<div style='font-weight:bold;color:#2c6fbb'>%s%s</div>"
                "<div>%s%s</div>"
                "<div style='color:#555;font-size:13px;margin-top:4px'>%s</div></div>"
                % (p["name"], temp, p["short"], pop, p["detailed"])
            )

    if not alerts and not precip:
        lines.append("No active alerts and no rain/snow in the forecast window.")
        html.append("<p>No active alerts and no rain/snow in the forecast window.</p>")

    footer = "Source: National Weather Service (api.weather.gov). Sent %s." % (
        datetime.now().strftime("%a %b %-d %-I:%M %p"))
    lines.append("\n---\n%s" % footer)
    html.append("<p style='color:#888;font-size:12px;margin-top:16px'>%s</p></div>" % footer)

    return subject, "\n".join(lines), "".join(html)


def send_email(subject, text_body, html_body):
    if not (GMAIL_USER and GMAIL_APP_PASSWORD and ALERT_TO):
        raise SystemExit("Missing email config: set GMAIL_USER, GMAIL_APP_PASSWORD, ALERT_TO.")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = ALERT_FROM
    msg["To"] = ", ".join(ALERT_TO)
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as s:
        s.starttls()
        s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        s.send_message(msg)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    print("Checking weather for %s (counties: %s)" % (PLACE_NAME, ", ".join(COUNTIES)))
    forecast_url = get_forecast_url()
    alerts = get_active_alerts()
    precip = get_precip_periods(forecast_url)
    print("Found %d alert(s), %d precip period(s)." % (len(alerts), len(precip)))

    if not alerts and not precip and not ALWAYS_SEND:
        print("Clear skies — no email sent.")
        return

    subject, text_body, html_body = build_email(alerts, precip)
    send_email(subject, text_body, html_body)
    print("Email sent: %s" % subject)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        # Fail loudly so the GitHub Actions run shows red and you get notified.
        print("ERROR: %s" % e, file=sys.stderr)
        sys.exit(1)
