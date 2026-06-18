# Severe weather email alert — setup guide

This emails you early each morning **only when severe weather, rain, or snow is coming**
to the greater Indianapolis metro area. It runs on GitHub's free servers, so **your
computer does not need to be on**.

You'll do a one-time setup (~15 minutes). No coding required — just copy, paste, and click.

---

## What you have

Three files (in this folder):

- `severe_weather_alert.py` — the program that checks the weather and sends the email.
- `weather-alert.yml` — tells GitHub to run it every morning.
- `SETUP.md` — this guide.

---

## Part 1 — Get a Gmail "app password" (so the script can send email)

This is a special 16-character password that lets the script send mail from your Gmail
**without** exposing your real password. (If you don't use Gmail, see "Other email" at the bottom.)

1. Your Google account must have **2-Step Verification** turned on.
   Check at <https://myaccount.google.com/security>. If it's off, turn it on first.
2. Go to <https://myaccount.google.com/apppasswords>.
3. Under "App name," type `Weather alert` and click **Create**.
4. Google shows a **16-character password** (like `abcd efgh ijkl mnop`).
   Copy it and keep it handy — you'll paste it in Part 3. Remove the spaces when you paste.

---

## Part 2 — Create the GitHub repository and add the files

1. If you don't have a GitHub account, make a free one at <https://github.com/signup>.
2. Go to <https://github.com/new> and create a repository:
   - Name: `weather-alert` (anything is fine)
   - Set it to **Private**
   - Click **Create repository**
3. On the new repo page, click **uploading an existing file** (the link in the
   "Quick setup" box), then drag in **`severe_weather_alert.py`** and **`SETUP.md`**.
   Click **Commit changes**.
4. Now add the workflow file in the right folder:
   - Click **Add file -> Create new file**.
   - In the filename box, type exactly: `.github/workflows/weather-alert.yml`
     (typing the slashes creates the folders automatically).
   - Open `weather-alert.yml` from this folder, copy all of its contents, and paste them in.
   - Click **Commit changes**.

---

## Part 3 — Add your email secrets

These are stored encrypted by GitHub and never shown in logs.

1. In your repo, go to **Settings** (top menu) -> **Secrets and variables** -> **Actions**.
2. Click **New repository secret** and add each of these three (name must match exactly):

   | Name                 | Value                                                        |
   |----------------------|--------------------------------------------------------------|
   | `GMAIL_USER`         | your full Gmail address, e.g. `you@gmail.com`                 |
   | `GMAIL_APP_PASSWORD` | the 16-character app password from Part 1 (no spaces)        |
   | `ALERT_TO`           | where to send the alert, e.g. `cmacer@cornerstonecompaniesinc.com` (commas for multiple) |

   Click **Add secret** after each one.

---

## Part 4 — Test it right now

1. In your repo, click the **Actions** tab. If prompted, click the green button to enable workflows.
2. Click **Severe weather alert** in the left sidebar.
3. Click **Run workflow -> Run workflow**.
4. Wait ~30 seconds and refresh. A green check = it ran successfully.
   - If there's bad weather in the forecast, you'll get an email.
   - On a clear day it sends nothing (that's correct). To force a test email anyway,
     temporarily set `WX_ALWAYS_SEND` to `1` (see "Tuning" below), run it, then set it back.

That's it. From now on it runs automatically every morning.

---

## When does it run?

Every day at **10:00 UTC**, which is **6:00 AM Eastern in summer / 5:00 AM in winter**.
To change the time, edit the `cron:` line in `weather-alert.yml`. The time is in UTC, so
subtract 4 hours (summer) or 5 hours (winter) to get Eastern. Example: `"0 9 * * *"` =
5 AM EDT / 4 AM EST.

GitHub occasionally delays scheduled runs by a few minutes when busy — not a problem for a
morning heads-up.

---

## Tuning (optional)

Open `weather-alert.yml` and uncomment any of the `WX_` lines under `env:` to change behavior:

- `WX_COUNTIES` — the counties to watch (comma-separated). Default covers the Indy metro.
- `WX_PRECIP_THRESHOLD` — chance-of-precip percent that counts as "rain/snow." Default `50`.
  Raise to `70` for fewer rain emails; lower to `30` to catch more.
- `WX_HOURS_AHEAD` — how far ahead to scan the forecast. Default `36` hours.
- `WX_ALWAYS_SEND` — set to `1` to email even on clear days (testing only). Default `0`.

You can also change the location by adding `WX_LAT`, `WX_LON`, and `WX_PLACE_NAME`.

---

## Good to know

- **Cost:** free. This uses a tiny fraction of GitHub Actions' free monthly minutes.
- **Data source:** the official U.S. National Weather Service API (`api.weather.gov`). No API key needed.
- **If a run fails** (red X), click it to see the log. The most common cause is a wrong
  app password or a typo in a secret name.
- **GitHub may email you** if the scheduled workflow has had no activity for 60 days and pause
  it; just click the link in that email to re-enable, or run it manually now and then.

---

## Other email (not Gmail)

The script uses Gmail's SMTP server by default. For Outlook/Microsoft 365 or another provider,
the SMTP host and port in `severe_weather_alert.py` (`smtp.gmail.com`, `587`) would need to be
changed to your provider's settings, and `GMAIL_USER` / `GMAIL_APP_PASSWORD` set to that
account's credentials. Ask me and I'll adjust it for your provider.
