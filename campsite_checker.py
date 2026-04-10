#!/usr/bin/env python3
"""
Campsite Availability Checker for ReserveCalifornia
Monitors beach campsites near Monterey, Santa Cruz & Big Sur
and sends email notifications when sites become available.

Usage:
    python campsite_checker.py                  # run once
    python campsite_checker.py --daemon         # run continuously
    python campsite_checker.py --discover       # discover campground IDs near target areas
"""

import argparse
import hashlib
import json
import logging
import smtplib
import time
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
import yaml

# ---------------------------------------------------------------------------
# Constants — ReserveCalifornia (Tyler/Aspira platform)
# ---------------------------------------------------------------------------
RDR_BASE = "https://california-rdr.prod.cali.rd12.recreation-management.tylerapp.com/rdr/"
SEARCH_PLACE_URL = RDR_BASE + "search/place"
SEARCH_GRID_URL = RDR_BASE + "search/grid"
PLACES_URL = RDR_BASE + "fd/places"

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.reservecalifornia.com",
    "Referer": "https://www.reservecalifornia.com/",
}

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"
STATE_PATH = SCRIPT_DIR / ".checker_state.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("campsite_checker")


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------
def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def load_state() -> dict:
    if STATE_PATH.exists():
        with open(STATE_PATH) as f:
            return json.load(f)
    return {"notified": {}}


def save_state(state: dict):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def _key(camp: str, date: str, site: str) -> str:
    return hashlib.md5(f"{camp}|{date}|{site}".encode()).hexdigest()


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------
def _place_body(place_id: int = 0, start_date: str = "", nights: int = 2,
                lat: float = 0, lon: float = 0) -> dict:
    return {
        "PlaceId": place_id,
        "Latitude": lat,
        "Longitude": lon,
        "HighlightedPlaceId": 0,
        "StartDate": start_date,
        "Nights": nights,
        "CountNearby": True,
        "NearbyLimit": 100,
        "NearbyOnlyAvailable": False,
        "NearbyCountLimit": 100,
        "Sort": "Distance",
        "CustomerId": 0,
        "RefreshFavourites": True,
        "IsADA": False,
        "UnitCategoryId": 0,
        "SleepingUnitId": 0,
        "MinVehicleLength": 0,
        "UnitTypesGroupIds": [],
    }


def get_place_facilities(place_id: int, start_date: str, nights: int = 2) -> dict:
    """
    Call search/place to get the list of facilities (and high-level
    availability) for a given PlaceId.
    Returns {"place_info": {...}, "facilities": {fid: {...}, ...}}.
    """
    body = _place_body(place_id=place_id, start_date=start_date, nights=nights)
    try:
        r = requests.post(SEARCH_PLACE_URL, json=body, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.error("search/place failed for PlaceId=%s: %s", place_id, e)
        return {}

    sp = data.get("SelectedPlace") or {}
    return {
        "place_info": {
            "name": sp.get("Name", ""),
            "available": sp.get("Available", False),
            "unit_count": sp.get("AvailableUnitCount", 0),
        },
        "facilities": sp.get("Facilities") or {},
    }


def get_grid(place_id: int, facility_id: int,
             start_date: str, nights: int = 2) -> dict:
    """
    Call search/grid for a specific PlaceId + FacilityId.
    Returns the raw JSON response which contains Facility.Units.Slices.
    """
    body = _place_body(place_id=place_id, start_date=start_date, nights=nights)
    body["FacilityId"] = facility_id
    body["CountNearby"] = False
    try:
        r = requests.post(SEARCH_GRID_URL, json=body, headers=HEADERS, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error("search/grid failed PlaceId=%s FacilityId=%s: %s",
                  place_id, facility_id, e)
        return {}


def parse_available_sites(grid_data: dict, camp_name: str,
                          region: str, place_id: int) -> list[dict]:
    """Extract available sites from a grid response."""
    results = []
    fac = grid_data.get("Facility") or {}
    facility_name = fac.get("Name", "")
    units = fac.get("Units") or {}

    for uid, unit in units.items():
        slices = unit.get("Slices") or {}
        for date_str, sl in slices.items():
            if isinstance(sl, dict) and sl.get("IsFree"):
                # Format date for display
                try:
                    dt = datetime.fromisoformat(date_str.replace("Z", ""))
                    display_date = dt.strftime("%a %b %d, %Y")
                except Exception:
                    display_date = date_str

                results.append({
                    "campground": camp_name,
                    "region": region,
                    "facility": facility_name,
                    "site_name": unit.get("Name", f"Site {uid}"),
                    "date": display_date,
                    "date_raw": date_str,
                    "place_id": place_id,
                    "unit_id": uid,
                })
    return results


# ---------------------------------------------------------------------------
# Main check
# ---------------------------------------------------------------------------
def run_check(config: dict, send_notifications: bool = True) -> list[dict]:
    state = load_state()
    campgrounds = config["campgrounds"]
    date_ranges = config["date_ranges"]
    nights = config.get("nights", 2)
    all_findings = []
    new_findings = []

    for cg in campgrounds:
        name = cg["name"]
        pid = cg["place_id"]
        region = cg.get("region", "")

        for dr in date_ranges:
            start_dt = datetime.strptime(dr["start"], "%m/%d/%Y")
            end_dt = datetime.strptime(dr["end"], "%m/%d/%Y")

            # Step 1: Get facilities for this place + date
            log.info("Checking: %s (PlaceId=%s) for %s", name, pid, dr["start"])
            place_data = get_place_facilities(pid, dr["start"], nights)
            if not place_data:
                continue

            facilities = place_data.get("facilities", {})
            if not facilities:
                log.info("  No facilities found for %s", name)
                continue

            # Step 2: For each camping facility, get the grid
            for fid, finfo in facilities.items():
                fid_int = int(fid)
                fname = finfo.get("Name", f"Facility {fid}")
                category = finfo.get("Category", "")

                # Skip non-camping facilities (day use, tours, etc.)
                if category and category.lower() in ("day use", "tours", "picnic"):
                    continue

                # Check at 2-week intervals across the date range
                check_dt = start_dt
                while check_dt <= end_dt:
                    date_str = check_dt.strftime("%m/%d/%Y")
                    grid = get_grid(pid, fid_int, date_str, nights)

                    if grid:
                        sites = parse_available_sites(grid, name, region, pid)
                        for site in sites:
                            all_findings.append(site)
                            k = _key(name, site["date_raw"], site["site_name"])
                            if k not in state["notified"]:
                                new_findings.append(site)
                                state["notified"][k] = datetime.now().isoformat()

                    check_dt += timedelta(days=14)
                    time.sleep(0.5)  # rate limiting

    # --- Recreation.gov campgrounds ---
    rg_campgrounds = config.get("recreation_gov", [])
    for cg in rg_campgrounds:
        name = cg["name"]
        cid = cg["campground_id"]
        region = cg.get("region", "")

        for dr in date_ranges:
            start_dt = datetime.strptime(dr["start"], "%m/%d/%Y")
            end_dt = datetime.strptime(dr["end"], "%m/%d/%Y")
            log.info("Checking: %s (recreation.gov ID=%s) for %s", name, cid, dr["start"])

            current = start_dt.replace(day=1)
            while current <= end_dt:
                month_str = current.strftime("%Y-%m-01")
                data = _rg_get_month(cid, month_str)
                campsites = data.get("campsites") or {}

                for sid, site in campsites.items():
                    avails = site.get("availabilities") or {}
                    for date_str, status in avails.items():
                        if status != "Available":
                            continue
                        try:
                            dt = datetime.fromisoformat(date_str.replace("Z", ""))
                        except Exception:
                            continue
                        if dt.date() < start_dt.date() or dt.date() > end_dt.date():
                            continue
                        site_entry = {
                            "campground": name,
                            "region": region,
                            "facility": site.get("loop", ""),
                            "site_name": site.get("site", sid),
                            "date": dt.strftime("%a %b %d, %Y"),
                            "date_raw": date_str,
                            "place_id": cid,
                            "unit_id": sid,
                        }
                        all_findings.append(site_entry)
                        k = _key(name, date_str, site_entry["site_name"])
                        if k not in state["notified"]:
                            new_findings.append(site_entry)
                            state["notified"][k] = datetime.now().isoformat()

                if current.month == 12:
                    current = current.replace(year=current.year + 1, month=1)
                else:
                    current = current.replace(month=current.month + 1)
                time.sleep(0.5)

    # Prune old state (>7 days)
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    state["notified"] = {k: v for k, v in state["notified"].items() if v > cutoff}
    save_state(state)

    log.info("Total available: %d | New (not yet notified): %d",
             len(all_findings), len(new_findings))

    if new_findings and send_notifications:
        html = build_email_html(new_findings)
        send_email(
            config,
            f"Campsite Alert: {len(new_findings)} site(s) available!",
            html,
        )

    return all_findings


def _rg_get_month(campground_id: int, month_start: str) -> dict:
    """Fetch a month of availability from recreation.gov."""
    url = (f"https://www.recreation.gov/api/camps/availability/campground/"
           f"{campground_id}/month?start_date={month_start}T00%3A00%3A00.000Z")
    try:
        r = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "application/json",
        }, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error("recreation.gov failed for ID=%s: %s", campground_id, e)
        return {}


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
def build_email_html(findings: list[dict]) -> str:
    rows = ""
    for f in findings:
        link = f"https://www.reservecalifornia.com/Web/#702702702/park/{f['place_id']}"
        rows += (
            f"<tr>"
            f"<td style='padding:8px;border:1px solid #ddd'>"
            f"<a href='{link}'>{f['campground']}</a></td>"
            f"<td style='padding:8px;border:1px solid #ddd'>{f['region']}</td>"
            f"<td style='padding:8px;border:1px solid #ddd'>{f['facility']}</td>"
            f"<td style='padding:8px;border:1px solid #ddd'><b>{f['site_name']}</b></td>"
            f"<td style='padding:8px;border:1px solid #ddd'>{f['date']}</td>"
            f"</tr>"
        )

    return f"""
    <html><body style="font-family:Arial,sans-serif;max-width:750px;margin:auto">
    <h2 style="color:#cc0000">Campsite Available!</h2>
    <p>The following beach campsites just opened up on
    <a href="https://www.reservecalifornia.com">ReserveCalifornia</a>:</p>
    <table style="border-collapse:collapse;width:100%">
      <tr style="background:#222;color:#fff">
        <th style="padding:8px;text-align:left">Campground</th>
        <th style="padding:8px;text-align:left">Region</th>
        <th style="padding:8px;text-align:left">Facility</th>
        <th style="padding:8px;text-align:left">Site</th>
        <th style="padding:8px;text-align:left">Date</th>
      </tr>
      {rows}
    </table>
    <p style="margin-top:20px;font-size:12px;color:#888">
      Book fast — these go quickly!<br>
      <a href="https://www.reservecalifornia.com">reservecalifornia.com</a>
    </p>
    </body></html>
    """


def send_email(config: dict, subject: str, html_body: str):
    email_cfg = config["email"]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_cfg["sender_email"]
    msg["To"] = email_cfg["recipient_email"]
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(email_cfg["smtp_server"], email_cfg["smtp_port"]) as server:
            server.starttls()
            server.login(email_cfg["sender_email"], email_cfg["sender_password"])
            server.send_message(msg)
        log.info("Email sent to %s", email_cfg["recipient_email"])
    except Exception as e:
        log.error("Failed to send email: %s", e)


# ---------------------------------------------------------------------------
# Discovery mode
# ---------------------------------------------------------------------------
SEARCH_COORDS = {
    "Santa Cruz": (36.9741, -122.0308),
    "Monterey": (36.6002, -121.8947),
    "Big Sur": (36.2704, -121.8081),
}


def run_discover(config: dict):
    nights = config.get("nights", 2)
    start_date = config["date_ranges"][0]["start"]

    print("\n" + "=" * 80)
    print("  CAMPGROUND DISCOVERY — Coastal campsites near the target areas")
    print("=" * 80)

    for area, (lat, lon) in SEARCH_COORDS.items():
        print(f"\n--- {area} (lat={lat}, lon={lon}) ---")
        body = _place_body(lat=lat, lon=lon, start_date=start_date, nights=nights)
        try:
            r = requests.post(SEARCH_PLACE_URL, json=body, headers=HEADERS, timeout=30)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"  Error: {e}")
            continue

        nearby = data.get("NearbyPlaces", [])
        if not nearby:
            print("  No results returned")
            continue

        for np in nearby:
            pid = np.get("PlaceId", "?")
            name = np.get("Name", "?")
            avail = np.get("Available", False)
            units = np.get("AvailableUnitCount", 0)
            dist = np.get("MilesFromSelected", 0)
            tag = "AVAILABLE" if avail else "-"
            facs = np.get("Facilities") or {}

            # Show facility breakdown
            fac_names = []
            for fid, fi in facs.items():
                if isinstance(fi, dict):
                    cat = fi.get("Category", "")
                    if cat.lower() not in ("day use", "tours"):
                        fac_names.append(f"{fi.get('Name',fid)}")

            fac_str = ", ".join(fac_names[:3]) if fac_names else "no camping facilities"
            print(f"  PlaceId={pid:<6} {name:<40} {dist:>5.1f}mi  [{tag:>10}]  {fac_str}")

    print("\n" + "=" * 80)
    print("  Add desired PlaceIds to config.yaml under 'campgrounds'")
    print("=" * 80 + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Check ReserveCalifornia for available beach campsites"
    )
    parser.add_argument("--daemon", action="store_true",
                        help="Run continuously at the configured interval")
    parser.add_argument("--discover", action="store_true",
                        help="Discover campground PlaceIds near target areas")
    parser.add_argument("--no-email", action="store_true",
                        help="Print results but don't send email")
    args = parser.parse_args()

    config = load_config()

    if args.discover:
        run_discover(config)
        return

    def _print_results(findings):
        if findings:
            print(f"\n{'='*75}")
            print(f"  {len(findings)} available site(s):")
            print(f"{'='*75}")
            for f in findings:
                print(f"  {f['campground']:<30} {f['facility']:<35} "
                      f"{f['site_name']:<18} {f['date']}")
            print(f"{'='*75}")
        else:
            print("\n  No availability found.")

    if args.daemon:
        interval = config.get("check_interval_minutes", 30)
        log.info("Daemon mode — checking every %d minutes", interval)
        while True:
            try:
                _print_results(run_check(config, send_notifications=not args.no_email))
            except Exception as e:
                log.error("Check cycle failed: %s", e)
            log.info("Sleeping %d minutes...", interval)
            time.sleep(interval * 60)
    else:
        _print_results(run_check(config, send_notifications=not args.no_email))


if __name__ == "__main__":
    main()
