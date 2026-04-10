#!/usr/bin/env python3
"""
Campsite Finder — Flask API server
Serves the HTML frontend and provides API endpoints for searching
ReserveCalifornia + Recreation.gov campsite availability.
"""

import smtplib
import time
import yaml
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder="static")
CONFIG_PATH = Path(__file__).parent / "config.yaml"

def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)

# ---------------------------------------------------------------------------
# ReserveCalifornia API
# ---------------------------------------------------------------------------
RDR_BASE = "https://california-rdr.prod.cali.rd12.recreation-management.tylerapp.com/rdr/"
RC_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.reservecalifornia.com",
    "Referer": "https://www.reservecalifornia.com/",
}
RG_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
}


def rc_body(place_id, start_date, nights):
    return {
        "PlaceId": place_id, "Latitude": 0, "Longitude": 0,
        "HighlightedPlaceId": 0, "StartDate": start_date, "Nights": nights,
        "CountNearby": True, "NearbyLimit": 100,
        "NearbyOnlyAvailable": False, "NearbyCountLimit": 10,
        "Sort": "Distance", "CustomerId": 0, "RefreshFavourites": True,
        "IsADA": False, "UnitCategoryId": 0, "SleepingUnitId": 0,
        "MinVehicleLength": 0, "UnitTypesGroupIds": [],
    }


def check_rc(place_id, name, region, start_date, end_date, nights):
    results = []
    date_str = start_date.strftime("%m/%d/%Y")
    try:
        r = requests.post(RDR_BASE + "search/place",
                          json=rc_body(place_id, date_str, nights),
                          headers=RC_HEADERS, timeout=30)
        r.raise_for_status()
        sp = r.json().get("SelectedPlace") or {}
        facs = sp.get("Facilities") or {}
    except Exception:
        return results

    for fid, finfo in facs.items():
        if not isinstance(finfo, dict):
            continue
        cat = finfo.get("Category") or ""
        if cat.lower() in ("day use", "tours", "picnic"):
            continue
        fname = finfo.get("Name", f"Facility {fid}")
        check_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.min.time())

        while check_dt <= end_dt:
            ds = check_dt.strftime("%m/%d/%Y")
            body = rc_body(place_id, ds, nights)
            body["FacilityId"] = int(fid)
            body["CountNearby"] = False
            try:
                gr = requests.post(RDR_BASE + "search/grid", json=body,
                                   headers=RC_HEADERS, timeout=30)
                gr.raise_for_status()
                gdata = gr.json()
            except Exception:
                check_dt += timedelta(days=14)
                time.sleep(0.3)
                continue

            fac = gdata.get("Facility") or {}
            for uid, unit in (fac.get("Units") or {}).items():
                for dstr, sl in (unit.get("Slices") or {}).items():
                    if isinstance(sl, dict) and sl.get("IsFree"):
                        try:
                            dt = datetime.fromisoformat(dstr.replace("Z", ""))
                        except Exception:
                            continue
                        if dt.date() < start_date or dt.date() > end_date:
                            continue
                        site_name = (unit.get("Name") or f"Site {uid}").replace("\xa0", " ")
                        results.append({
                            "campground": name.replace("\xa0", " "),
                            "region": region,
                            "facility": fname.replace("\xa0", " "),
                            "site": site_name,
                            "date": dt.strftime("%a %b %d, %Y"),
                            "day": dt.strftime("%A"),
                            "source": "ReserveCalifornia",
                            "place_id": place_id,
                            "link": f"https://www.reservecalifornia.com/CaliforniaWebHome/Facilities/SearchViewUnitAvailab498702702702702702?parkId={place_id}",
                        })
            check_dt += timedelta(days=14)
            time.sleep(0.3)
    return results


def check_rg(campground_id, name, region, start_date, end_date, nights):
    results = []
    current = start_date.replace(day=1)
    while current <= end_date:
        month_str = current.strftime("%Y-%m-01")
        url = (f"https://www.recreation.gov/api/camps/availability/campground/"
               f"{campground_id}/month?start_date={month_str}T00%3A00%3A00.000Z")
        try:
            r = requests.get(url, headers=RG_HEADERS, timeout=30)
            r.raise_for_status()
            data = r.json()
        except Exception:
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
            time.sleep(0.3)
            continue

        for sid, site in (data.get("campsites") or {}).items():
            avails = site.get("availabilities") or {}
            for ds, status in avails.items():
                if status != "Available":
                    continue
                try:
                    dt = datetime.fromisoformat(ds.replace("Z", ""))
                except Exception:
                    continue
                if dt.date() < start_date or dt.date() > end_date:
                    continue
                if nights > 1:
                    ok = True
                    for n in range(1, nights):
                        nd = (dt + timedelta(days=n)).strftime("%Y-%m-%dT00:00:00Z")
                        if avails.get(nd) != "Available":
                            ok = False
                            break
                    if not ok:
                        continue
                loop = (site.get("loop") or "").replace("\xa0", " ")
                sname = (site.get("site") or str(sid)).replace("\xa0", " ")
                results.append({
                    "campground": name.replace("\xa0", " "),
                    "region": region,
                    "facility": loop,
                    "site": sname,
                    "date": dt.strftime("%a %b %d, %Y"),
                    "day": dt.strftime("%A"),
                    "source": "Recreation.gov",
                    "campground_id": campground_id,
                    "link": f"https://www.recreation.gov/camping/campgrounds/{campground_id}",
                })

        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
        time.sleep(0.3)
    return results


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/search", methods=["POST"])
def api_search():
    body = request.json
    camps = body.get("campgrounds", [])
    start = datetime.strptime(body["start_date"], "%Y-%m-%d").date()
    end = datetime.strptime(body["end_date"], "%Y-%m-%d").date()
    nights = body.get("nights", 2)
    weekend_only = body.get("weekend_only", False)

    all_results = []
    for cg in camps:
        if cg.get("source") == "Recreation.gov":
            all_results.extend(check_rg(
                cg["campground_id"], cg["name"], cg["region"], start, end, nights
            ))
        else:
            all_results.extend(check_rc(
                cg["place_id"], cg["name"], cg["region"], start, end, nights
            ))

    if weekend_only:
        all_results = [r for r in all_results if r["day"] in ("Friday", "Saturday")]

    # Deduplicate
    seen = set()
    deduped = []
    for r in all_results:
        key = (r["campground"], r["facility"], r["site"], r["date"])
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    # Consecutive nights filter: keep only sites available for N consecutive days
    consecutive = body.get("consecutive_nights", 0)
    if consecutive and consecutive > 1:
        # Build lookup: (campground, facility, site) -> set of date strings
        from collections import defaultdict
        site_dates = defaultdict(set)
        for r in deduped:
            try:
                dt = datetime.strptime(r["date"], "%a %b %d, %Y").date()
            except Exception:
                continue
            site_dates[(r["campground"], r["facility"], r["site"])].add(dt)

        filtered = []
        for r in deduped:
            try:
                dt = datetime.strptime(r["date"], "%a %b %d, %Y").date()
            except Exception:
                continue
            key = (r["campground"], r["facility"], r["site"])
            dates = site_dates[key]
            # Check if all consecutive nights from this date are available
            if all((dt + timedelta(days=d)) in dates for d in range(consecutive)):
                filtered.append(r)
        deduped = filtered

    return jsonify({"results": deduped, "count": len(deduped)})


@app.route("/api/email", methods=["POST"])
def api_email():
    body = request.json
    results = body.get("results", [])
    if not results:
        return jsonify({"ok": False, "message": "No results to email"})

    config = load_config()
    email_cfg = config.get("email", {})
    sender = email_cfg.get("sender_email", "")
    password = email_cfg.get("sender_password", "")
    recipient = email_cfg.get("recipient_email", "")

    if not all([sender, password, recipient]) or sender == "your-email@gmail.com":
        return jsonify({"ok": False, "message": "Email not configured in config.yaml"})

    def _clean(s):
        """Strip non-ASCII characters."""
        if not s:
            return ""
        return str(s).replace("\xa0", " ").encode("ascii", "ignore").decode("ascii")

    rows = ""
    for r in results:
        link = r.get("link", "")
        cg_cell = f"<a href='{link}' style='color:#88aacc;text-decoration:none'>{_clean(r['campground'])}</a>" if link else _clean(r['campground'])
        rows += (
            f"<tr>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #1a1a1a'>{cg_cell}</td>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #1a1a1a'>{_clean(r['region'])}</td>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #1a1a1a'>{_clean(r['facility'])}</td>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #1a1a1a'><b>{_clean(r['site'])}</b></td>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #1a1a1a'>{_clean(r['date'])}</td>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #1a1a1a'>{_clean(r['day'])}</td>"
            f"</tr>"
        )

    html = f"""
    <html><body style="font-family:-apple-system,sans-serif;max-width:800px;margin:auto;background:#0a0a0a;color:#ccc;padding:24px">
    <h2 style="color:#fff;margin-bottom:4px;font-weight:600">Campsite Availability</h2>
    <p style="color:#666;margin-top:0;font-size:13px">{len(results)} site(s) found</p>
    <table style="border-collapse:collapse;width:100%;font-size:13px;color:#ccc">
      <tr style="background:#111;color:#666;text-transform:uppercase;font-size:11px;letter-spacing:0.5px">
        <th style="padding:10px 12px;text-align:left">Campground</th>
        <th style="padding:10px 12px;text-align:left">Region</th>
        <th style="padding:10px 12px;text-align:left">Facility</th>
        <th style="padding:10px 12px;text-align:left">Site</th>
        <th style="padding:10px 12px;text-align:left">Date</th>
        <th style="padding:10px 12px;text-align:left">Day</th>
      </tr>
      {rows}
    </table>
    <p style="margin-top:24px;font-size:11px;color:#444">
      Book at <a href="https://www.reservecalifornia.com" style="color:#666">reservecalifornia.com</a>
      or <a href="https://www.recreation.gov" style="color:#666">recreation.gov</a>
    </p>
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Campsite Alert: {len(results)} site(s) available"
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP(email_cfg.get("smtp_server", "smtp.gmail.com"),
                          email_cfg.get("smtp_port", 587)) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)
        return jsonify({"ok": True, "message": f"Sent to {recipient}"})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8520, debug=False)
