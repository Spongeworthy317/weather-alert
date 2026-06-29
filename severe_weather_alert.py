#!/usr/bin/env python3
"""
Severe weather email alert for a list of U.S. cities.

Runs on a schedule (e.g. GitHub Actions cron), checks the National Weather
Service API for active alerts and the short-term forecast for every city in
cities.json, and emails ONE combined report listing only the cities that have
severe weather, rain, or snow coming. Silent when every city is clear.

Configuration is via environment variables (see SETUP.md). The only required
ones are the three email secrets:
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
CITIES_FILE = os.environ.get("WX_CITIES_FILE", "cities.json")

# Forecast lookahead and the precip probability that counts as "rain/snow".
HOURS_AHEAD = int(os.environ.get("WX_HOURS_AHEAD", "36"))
PRECIP_THRESHOLD = int(os.environ.get("WX_PRECIP_THRESHOLD", "50"))  # percent

# Words in a forecast that mean precipitation worth flagging.
PRECIP_WORDS = ["rain", "snow", "shower", "thunderstorm", "sleet",
                "freezing", "wintry", "blizzard", "flurr", "drizzle", "ice"]

# Send an email even when nothing is happening (handy for a one-time test).
ALWAYS_SEND = os.environ.get("WX_ALWAYS_SEND", "0") == "1"

# Politeness delay between NWS API calls (seconds).
API_PAUSE = float(os.environ.get("WX_API_PAUSE", "0.4"))

# Email
GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
ALERT_TO = [a.strip() for a in os.environ.get("ALERT_TO", "").split(",") if a.strip()]
ALERT_FROM = os.environ.get("ALERT_FROM", GMAIL_USER)

USER_AGENT = os.environ.get(
    "WX_USER_AGENT",
    "multi-city-severe-weather-alert/2.0 (%s)" % (GMAIL_USER or "anonymous@example.com"),
)


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


def alerts_for_point(lat, lon):
    """Active alerts whose zone contains this point."""
    data = api_get("https://api.weather.gov/alerts/active?point=%s,%s" % (lat, lon))
    time.sleep(API_PAUSE)
    return data.get("features", [])


def get_city_alerts(city):
    """Collect + de-duplicate alerts across a city's center and suburb points."""
    points = [(city["lat"], city["lon"])] + [tuple(p) for p in city.get("extra_points", [])]
    seen, out = set(), []
    for lat, lon in points:
        for feat in alerts_for_point(lat, lon):
            p = feat.get("properties", {})
            key = feat.get("id") or (p.get("event"), p.get("headline"), p.get("areaDesc"))
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "event": p.get("event", "Weather alert"),
                "severity": p.get("severity", ""),
                "headline": p.get("headline", ""),
                "area": p.get("areaDesc", ""),
                "expires": p.get("expires", ""),
                "instruction": (p.get("instruction") or "").strip(),
            })
    # Most urgent first.
    order = {"Extreme": 0, "Severe": 1, "Moderate": 2, "Minor": 3, "Unknown": 4, "": 5}
    out.sort(key=lambda a: order.get(a["severity"], 5))
    return out


def get_city_precip(city):
    """Forecast periods within HOURS_AHEAD that look like rain/snow."""
    pts = api_get("https://api.weather.gov/points/%s,%s" % (city["lat"], city["lon"]))
    time.sleep(API_PAUSE)
    forecast_url = pts["properties"]["forecast"]
    data = api_get(forecast_url)
    time.sleep(API_PAUSE)
    periods = data.get("properties", {}).get("periods", [])
    now = datetime.now(timezone.utc)
    hits = []
    for per in periods:
        try:
            start = datetime.fromisoformat(per["startTime"])
        except Exception:
            start = now
        if (start - now).total_seconds() / 3600.0 > HOURS_AHEAD:
            continue
        short = (per.get("shortForecast") or "").lower()
        pop = (per.get("probabilityOfPrecipitation") or {}).get("value")
        word_hit = any(w in short for w in PRECIP_WORDS)
        pop_hit = isinstance(pop, (int, float)) and pop >= PRECIP_THRESHOLD
        if word_hit or pop_hit:
            hits.append({
                "name": per.get("name", ""),
                "short": per.get("shortForecast", ""),
                "detailed": per.get("detailedForecast", ""),
                "pop": pop,
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


def build_email(flagged, clear, errored):
    """flagged: list of dicts {name, alerts, precip}. clear/errored: name lists."""
    today = datetime.now().strftime("%b %-d")
    total = len(flagged) + len(clear) + len(errored)
    any_alert = any(c["alerts"] for c in flagged)
    icon = "⚠️" if any_alert else "\U0001f327️"
    subject = "%s Weather alert — %d of %d cities (%s)" % (icon, len(flagged), total, today)

    lines = ["Bad weather is coming to %d of %d cities.\n" % (len(flagged), total)]
    html = ["<div style='font-family:Arial,Helvetica,sans-serif;font-size:15px;color:#1a1a1a'>"]
    html.append("<p style='font-size:17px;font-weight:bold;margin:0 0 10px'>"
                "Bad weather is coming to %d of %d cities</p>" % (len(flagged), total))

    for c in flagged:
        lines.append("\n========================================")
        lines.append(c["name"].upper())
        lines.append("========================================")
        html.append("<h2 style='font-size:18px;margin:18px 0 4px;"
                    "border-bottom:2px solid #ddd;padding-bottom:4px'>%s</h2>" % c["name"])

        for a in c["alerts"]:
            lines.append("\n[ALERT] %s (%s)" % (a["event"], a["severity"] or "n/a"))
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
                "<div style='color:#555;font-size:13px'>Area: %s</div>%s</div>" % (
                    a["event"], a["severity"] or "n/a", a["headline"],
                    fmt_time(a["expires"]), a["area"],
                    ("<div style='margin-top:4px'>%s</div>" % a["instruction"]) if a["instruction"] else "",
                ))

        for p in c["precip"]:
            pop = ("  (%d%% chance)" % p["pop"]) if isinstance(p["pop"], (int, float)) else ""
            temp = (" — %s°%s" % (p["temp"], p["unit"])) if p["temp"] is not None else ""
            lines.append("\n[FORECAST] %s%s: %s%s" % (p["name"], temp, p["short"], pop))
            lines.append("  %s" % p["detailed"])
            html.append(
                "<div style='border-left:4px solid #2c6fbb;background:#eaf1fb;"
                "padding:8px 12px;margin:8px 0'>"
                "<div style='font-weight:bold;color:#2c6fbb'>%s%s</div>"
                "<div>%s%s</div>"
                "<div style='color:#555;font-size:13px;margin-top:4px'>%s</div></div>" % (
                    p["name"], temp, p["short"], pop, p["detailed"]))

    if clear:
        lines.append("\nNo issues: %s" % ", ".join(clear))
        html.append("<p style='color:#2e7d32;font-size:13px;margin-top:16px'>"
                    "<b>Clear (no alerts or precip):</b> %s</p>" % ", ".join(clear))
    if errored:
        lines.append("\nCould not check (will retry next run): %s" % ", ".join(errored))
        html.append("<p style='color:#b26a00;font-size:13px'>"
                    "<b>Could not check this run:</b> %s</p>" % ", ".join(errored))

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
def load_cities():
    with open(CITIES_FILE, "r", encoding="utf-8") as f:
        cities = json.load(f)
    if not isinstance(cities, list) or not cities:
        raise SystemExit("%s must be a non-empty JSON list of cities." % CITIES_FILE)
    return cities


def main():
    cities = load_cities()
    print("Checking %d cities from %s" % (len(cities), CITIES_FILE))

    flagged, clear, errored = [], [], []
    for city in cities:
        name = city.get("name", "%s,%s" % (city.get("lat"), city.get("lon")))
        try:
            alerts = get_city_alerts(city)
            precip = get_city_precip(city)
            if alerts or precip:
                flagged.append({"name": name, "alerts": alerts, "precip": precip})
                print("  %s: %d alert(s), %d precip period(s)" % (name, len(alerts), len(precip)))
            else:
                clear.append(name)
                print("  %s: clear" % name)
        except Exception as e:
            errored.append(name)
            print("  %s: ERROR %s" % (name, e), file=sys.stderr)

    if not flagged and not ALWAYS_SEND:
        # Still surface check failures so silent breakage doesn't hide.
        if errored:
            print("All checkable cities clear, but errors occurred: %s" % ", ".join(errored))
        else:
            print("All %d cities clear — no email sent." % len(cities))
        return

    subject, text_body, html_body = build_email(flagged, clear, errored)
    send_email(subject, text_body, html_body)
    print("Email sent: %s" % subject)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print("ERROR: %s" % e, file=sys.stderr)
        sys.exit(1)
