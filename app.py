import streamlit as st
import pandas as pd
import requests
import smtplib
import time
import yaml
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

st.set_page_config(page_title="Campsite Finder", layout="wide", initial_sidebar_state="expanded")

# ---------------------------------------------------------------------------
# Dark theme
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    /* ---- base ---- */
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"],
    section[data-testid="stSidebar"], [data-testid="stSidebarContent"] {
        background-color: #0a0a0a !important;
        color: #d0d0d0 !important;
    }
    section[data-testid="stSidebar"] {
        border-right: 1px solid #1a1a1a !important;
    }

    /* ---- text ---- */
    h1, h2, h3, h4, h5, h6, p, span, label, li,
    .stMarkdown, [data-testid="stMarkdownContainer"],
    [data-testid="stMetricValue"], [data-testid="stMetricLabel"],
    [data-testid="stWidgetLabel"] label,
    [data-testid="stWidgetLabel"] p {
        color: #d0d0d0 !important;
    }
    h1 { color: #fff !important; font-weight: 700 !important; }

    /* ---- multiselect pills (fix red pills) ---- */
    [data-testid="stMultiSelect"] span[data-baseweb="tag"] {
        background-color: #222 !important;
        color: #ddd !important;
        border: 1px solid #444 !important;
        border-radius: 4px !important;
    }
    [data-testid="stMultiSelect"] span[data-baseweb="tag"] span {
        color: #ddd !important;
    }
    /* tag close button */
    [data-testid="stMultiSelect"] span[data-baseweb="tag"] svg {
        fill: #888 !important;
    }

    /* ---- inputs ---- */
    [data-testid="stMultiSelect"] > div > div,
    [data-baseweb="select"] > div,
    [data-baseweb="input"] > div,
    input[type="number"],
    .stDateInput > div > div > input,
    .stNumberInput > div > div > input,
    [data-baseweb="base-input"] {
        background-color: #141414 !important;
        color: #d0d0d0 !important;
        border-color: #2a2a2a !important;
    }
    input { color: #d0d0d0 !important; }

    /* dropdown menu */
    [data-baseweb="popover"], [data-baseweb="menu"],
    ul[role="listbox"], li[role="option"] {
        background-color: #141414 !important;
        color: #d0d0d0 !important;
    }
    li[role="option"]:hover {
        background-color: #222 !important;
    }

    /* ---- search button ---- */
    .stButton > button[kind="primary"] {
        background-color: #fff !important;
        color: #000 !important;
        border: none !important;
        font-weight: 700 !important;
        font-size: 1rem !important;
        border-radius: 6px !important;
        padding: 0.6rem 1rem !important;
    }
    .stButton > button[kind="primary"]:hover {
        background-color: #ccc !important;
    }

    /* ---- download button ---- */
    .stDownloadButton > button {
        background-color: #141414 !important;
        color: #d0d0d0 !important;
        border: 1px solid #333 !important;
    }

    /* ---- tabs ---- */
    .stTabs [data-baseweb="tab-list"] { border-bottom: 1px solid #222 !important; }
    .stTabs [data-baseweb="tab"] {
        color: #666 !important;
        background: transparent !important;
    }
    .stTabs [aria-selected="true"] {
        color: #fff !important;
        border-bottom: 2px solid #fff !important;
    }

    /* ---- metrics ---- */
    [data-testid="stMetricValue"] {
        font-size: 2rem !important; color: #fff !important; font-weight: 700 !important;
    }
    [data-testid="stMetricLabel"] { color: #666 !important; text-transform: uppercase !important; font-size: 0.75rem !important; }

    /* ---- dataframe ---- */
    .stDataFrame { border: 1px solid #1a1a1a !important; }

    /* ---- divider ---- */
    hr { border-color: #1a1a1a !important; }

    /* ---- alerts ---- */
    .stAlert, [data-testid="stNotification"] {
        background-color: #111 !important;
        border: 1px solid #222 !important;
        color: #d0d0d0 !important;
    }

    /* ---- checkbox ---- */
    [data-testid="stCheckbox"] label span { color: #d0d0d0 !important; }

    /* ---- progress bar ---- */
    .stProgress > div > div > div { background-color: #fff !important; }

    /* ---- scrollbar ---- */
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: #0a0a0a; }
    ::-webkit-scrollbar-thumb { background: #333; border-radius: 3px; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CONFIG_PATH = Path(__file__).parent / "config.yaml"


@st.cache_data(ttl=3600)
def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


config = load_config()

# ---------------------------------------------------------------------------
# API
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

# ---------------------------------------------------------------------------
# Campground registry
# ---------------------------------------------------------------------------
RC_CAMPS = [
    {"name": "New Brighton SB", "place_id": 685, "region": "Santa Cruz"},
    {"name": "Seacliff SB", "place_id": 714, "region": "Santa Cruz"},
    {"name": "Sunset SB", "place_id": 726, "region": "Santa Cruz"},
    {"name": "Manresa SB", "place_id": 672, "region": "Santa Cruz"},
    {"name": "Asilomar SB", "place_id": 1084, "region": "Monterey"},
    {"name": "Fort Ord Dunes SP", "place_id": 1125, "region": "Monterey"},
    {"name": "Pfeiffer Big Sur SP", "place_id": 690, "region": "Big Sur"},
    {"name": "Andrew Molera SP", "place_id": 1077, "region": "Big Sur"},
    {"name": "Limekiln SP", "place_id": 666, "region": "Big Sur"},
    {"name": "Julia Pfeiffer Burns SP", "place_id": 661, "region": "Big Sur"},
]

RG_CAMPS = [
    {"name": "Kirk Creek", "campground_id": 233116, "region": "Big Sur"},
    {"name": "Plaskett Creek", "campground_id": 231959, "region": "Big Sur"},
]

ALL_CAMPS = [
    {**c, "source": "ReserveCalifornia"} for c in RC_CAMPS
] + [
    {**c, "source": "Recreation.gov"} for c in RG_CAMPS
]

ALL_REGIONS = sorted(set(c["region"] for c in ALL_CAMPS))


# ---------------------------------------------------------------------------
# ReserveCalifornia helpers
# ---------------------------------------------------------------------------
def _rc_body(place_id, start_date, nights):
    return {
        "PlaceId": place_id, "Latitude": 0, "Longitude": 0,
        "HighlightedPlaceId": 0, "StartDate": start_date, "Nights": nights,
        "CountNearby": True, "NearbyLimit": 100,
        "NearbyOnlyAvailable": False, "NearbyCountLimit": 10,
        "Sort": "Distance", "CustomerId": 0, "RefreshFavourites": True,
        "IsADA": False, "UnitCategoryId": 0, "SleepingUnitId": 0,
        "MinVehicleLength": 0, "UnitTypesGroupIds": [],
    }


@st.cache_data(ttl=600, show_spinner=False)
def rc_facilities(place_id, start_date, nights):
    try:
        r = requests.post(RDR_BASE + "search/place",
                          json=_rc_body(place_id, start_date, nights),
                          headers=RC_HEADERS, timeout=30)
        r.raise_for_status()
        sp = r.json().get("SelectedPlace") or {}
        return sp.get("Facilities") or {}
    except Exception:
        return {}


@st.cache_data(ttl=600, show_spinner=False)
def rc_grid(place_id, facility_id, start_date, nights):
    body = _rc_body(place_id, start_date, nights)
    body["FacilityId"] = facility_id
    body["CountNearby"] = False
    try:
        r = requests.post(RDR_BASE + "search/grid", json=body,
                          headers=RC_HEADERS, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


def rc_parse(grid_data, camp_name, region, fac_name):
    out = []
    fac = grid_data.get("Facility") or {}
    for uid, unit in (fac.get("Units") or {}).items():
        for ds, sl in (unit.get("Slices") or {}).items():
            if isinstance(sl, dict) and sl.get("IsFree"):
                try:
                    dt = datetime.fromisoformat(ds.replace("Z", ""))
                except Exception:
                    continue
                out.append({
                    "Campground": camp_name, "Region": region,
                    "Facility": fac_name,
                    "Site": unit.get("Name", f"Site {uid}"),
                    "Date": dt.strftime("%a %b %d, %Y"),
                    "Day": dt.strftime("%A"),
                    "date_obj": dt, "Source": "ReserveCalifornia",
                })
    return out


def check_rc(cg, start_date, end_date, nights):
    pid = cg["place_id"]
    results = []
    facs = rc_facilities(pid, start_date.strftime("%m/%d/%Y"), nights)
    if not facs:
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
            grid = rc_grid(pid, int(fid), check_dt.strftime("%m/%d/%Y"), nights)
            if grid:
                results.extend(rc_parse(grid, cg["name"], cg["region"], fname))
            check_dt += timedelta(days=14)
            time.sleep(0.3)
    return results


# ---------------------------------------------------------------------------
# Recreation.gov helpers
# ---------------------------------------------------------------------------
@st.cache_data(ttl=600, show_spinner=False)
def rg_month(campground_id, month_start):
    url = (f"https://www.recreation.gov/api/camps/availability/campground/"
           f"{campground_id}/month?start_date={month_start}T00%3A00%3A00.000Z")
    try:
        r = requests.get(url, headers=RG_HEADERS, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


def check_rg(cg, start_date, end_date, nights):
    cid = cg["campground_id"]
    results = []
    current = start_date.replace(day=1)
    while current <= end_date:
        data = rg_month(cid, current.strftime("%Y-%m-01"))
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
                results.append({
                    "Campground": cg["name"], "Region": cg["region"],
                    "Facility": site.get("loop", ""),
                    "Site": site.get("site", sid),
                    "Date": dt.strftime("%a %b %d, %Y"),
                    "Day": dt.strftime("%A"),
                    "date_obj": dt, "Source": "Recreation.gov",
                })
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
        time.sleep(0.3)
    return results


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
def send_email(results_df):
    email_cfg = config.get("email", {})
    sender = email_cfg.get("sender_email", "")
    password = email_cfg.get("sender_password", "")
    recipient = email_cfg.get("recipient_email", "")
    if not all([sender, password, recipient]) or sender == "your-email@gmail.com":
        return False, "Email not configured in config.yaml"

    rows = ""
    for _, r in results_df.iterrows():
        rows += (
            f"<tr>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #222'>{r.get('Campground','')}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #222'>{r.get('Region','')}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #222'>{r.get('Facility','')}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #222'><b>{r.get('Site','')}</b></td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #222'>{r.get('Date','')}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #222'>{r.get('Day','')}</td>"
            f"</tr>"
        )

    html = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:800px;margin:auto;background:#0a0a0a;color:#ddd;padding:20px">
    <h2 style="color:#fff;margin-bottom:4px">Campsite Availability Alert</h2>
    <p style="color:#888;margin-top:0">Found {len(results_df)} available site(s)</p>
    <table style="border-collapse:collapse;width:100%;font-size:13px">
      <tr style="background:#1a1a1a;color:#aaa;text-transform:uppercase;font-size:11px">
        <th style="padding:8px 10px;text-align:left">Campground</th>
        <th style="padding:8px 10px;text-align:left">Region</th>
        <th style="padding:8px 10px;text-align:left">Facility</th>
        <th style="padding:8px 10px;text-align:left">Site</th>
        <th style="padding:8px 10px;text-align:left">Date</th>
        <th style="padding:8px 10px;text-align:left">Day</th>
      </tr>
      {rows}
    </table>
    <p style="margin-top:20px;font-size:11px;color:#555">
      Book at <a href="https://www.reservecalifornia.com" style="color:#888">reservecalifornia.com</a>
      or <a href="https://www.recreation.gov" style="color:#888">recreation.gov</a>
    </p>
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Campsite Alert: {len(results_df)} site(s) available"
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP(email_cfg.get("smtp_server", "smtp.gmail.com"),
                          email_cfg.get("smtp_port", 587)) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)
        return True, f"Email sent to {recipient}"
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
st.sidebar.markdown("### Filters")

sel_regions = st.sidebar.multiselect(
    "Region", ALL_REGIONS, default=ALL_REGIONS, key="regions"
)

# Campgrounds filtered by selected regions
region_camps = [c for c in ALL_CAMPS if c["region"] in sel_regions]
camp_names = [c["name"] for c in region_camps]
sel_camp_names = st.sidebar.multiselect(
    "Campgrounds", camp_names, default=camp_names, key="camps"
)

today = datetime.now().date()
c1, c2 = st.sidebar.columns(2)
start_date = c1.date_input("From", today + timedelta(days=1), key="from")
end_date = c2.date_input("To", today + timedelta(days=60), key="to")

nights = st.sidebar.number_input("Nights", min_value=1, max_value=14, value=2, key="nights")
weekend_only = st.sidebar.checkbox("Weekends only (Fri/Sat)", key="weekend")

send_email_flag = st.sidebar.checkbox("Email results", value=True, key="email_flag")

st.sidebar.markdown("---")
search_btn = st.sidebar.button("SEARCH", type="primary", use_container_width=True)

# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------
st.markdown("# Campsite Finder")
st.caption("Monterey / Santa Cruz / Big Sur")

if search_btn:
    selected = [c for c in region_camps if c["name"] in sel_camp_names]
    if not selected:
        st.warning("Select at least one campground.")
        st.stop()

    all_results = []
    progress = st.progress(0, text="Searching...")

    for i, cg in enumerate(selected):
        progress.progress((i + 1) / len(selected), text=f"Checking {cg['name']}...")
        if cg["source"] == "ReserveCalifornia":
            all_results.extend(check_rc(cg, start_date, end_date, nights))
        else:
            all_results.extend(check_rg(cg, start_date, end_date, nights))

    progress.empty()

    # Filter weekends
    if weekend_only:
        all_results = [r for r in all_results if r["Day"] in ("Friday", "Saturday")]

    # Deduplicate
    seen = set()
    deduped = []
    for r in all_results:
        key = (r["Campground"], r["Facility"], r["Site"], r["Date"])
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    if not deduped:
        st.markdown("---")
        st.markdown("**No availability found.** Try expanding your date range or selecting more campgrounds.")
        st.stop()

    # Build dataframe
    df = pd.DataFrame(deduped)
    display_cols = ["Campground", "Region", "Facility", "Site", "Date", "Day", "Source"]
    df_show = df[[c for c in display_cols if c in df.columns]].sort_values(
        ["Region", "Campground", "Date", "Site"]
    )

    # --- Metrics ---
    st.markdown("---")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("CAMPGROUNDS", len(df_show["Campground"].unique()))
    m2.metric("AVAILABLE SITES", len(df_show))
    m3.metric("DATES", len(df_show["Date"].unique()))
    m4.metric("SOURCES", len(df_show["Source"].unique()))

    # --- Results by region ---
    st.markdown("---")
    avail_regions = sorted(df_show["Region"].unique())
    tabs = st.tabs(avail_regions)

    for tab, reg in zip(tabs, avail_regions):
        with tab:
            reg_df = df_show[df_show["Region"] == reg]
            for camp_name in reg_df["Campground"].unique():
                camp_df = reg_df[reg_df["Campground"] == camp_name]
                src = camp_df["Source"].iloc[0]
                count = len(camp_df)
                st.markdown(f"**{camp_name}** &mdash; {count} site(s) &nbsp; `{src}`")
                st.dataframe(
                    camp_df[["Facility", "Site", "Date", "Day"]],
                    use_container_width=True,
                    hide_index=True,
                    height=min(400, 35 * len(camp_df) + 38),
                )

    # --- Download ---
    st.markdown("---")
    csv = df_show.to_csv(index=False)
    st.download_button("Download CSV", csv, "campsite_availability.csv",
                       "text/csv", use_container_width=True)

    # --- Email ---
    if send_email_flag:
        st.markdown("---")
        with st.spinner("Sending email..."):
            ok, msg = send_email(df_show)
        if ok:
            st.success(msg)
        else:
            st.error(f"Email failed: {msg}")

else:
    # Landing state
    st.markdown("---")
    st.markdown("""
| Region | Campgrounds | Source |
|--------|------------|--------|
| Santa Cruz | New Brighton, Seacliff, Sunset, Manresa | ReserveCalifornia |
| Monterey | Asilomar, Fort Ord Dunes | ReserveCalifornia |
| Big Sur | Pfeiffer Big Sur, Andrew Molera, Limekiln, Julia Pfeiffer Burns | ReserveCalifornia |
| Big Sur | Kirk Creek, Plaskett Creek | Recreation.gov |
""")
    st.caption("Set filters, click SEARCH. Results display here and optionally email.")
