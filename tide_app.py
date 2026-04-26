import streamlit as st
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
import math
import plotly.graph_objects as go

ET_TZ = pytz.timezone("US/Eastern")

st.set_page_config(
    page_title="Tides & Weather",
    page_icon="🌊",
    layout="centered",
)

NOAA_STATIONS = {
    "8726384": {"name": "Anna Maria Island, FL", "lat": 27.5306, "lon": -82.7328},
    "8723214": {"name": "Miami Beach, FL", "lat": 25.7907, "lon": -80.1300},
    "8724580": {"name": "Key West, FL", "lat": 24.5551, "lon": -81.7800},
    "8726520": {"name": "Tampa Bay, FL", "lat": 27.9506, "lon": -82.4572},
    "8726724": {"name": "Clearwater Beach, FL", "lat": 27.9780, "lon": -82.8270},
    "8726607": {"name": "St. Petersburg, FL", "lat": 27.7676, "lon": -82.6403},
    "8725110": {"name": "Naples, FL", "lat": 26.1420, "lon": -81.7948},
    "8725520": {"name": "Fort Myers, FL", "lat": 26.6406, "lon": -81.8723},
    "8726347": {"name": "Bradenton Beach, FL", "lat": 27.4672, "lon": -82.6956},
}

ZIP_DEFAULTS = {
    "34216": {"lat": 27.4836, "lon": -82.7128, "name": "Anna Maria, FL"},
    "34217": {"lat": 27.4672, "lon": -82.6956, "name": "Bradenton Beach, FL"},
}

WMO_CODES = {
    0: ("Clear", "☀️"),
    1: ("Mostly Clear", "🌤️"),
    2: ("Partly Cloudy", "⛅"),
    3: ("Overcast", "☁️"),
    45: ("Foggy", "🌫️"),
    48: ("Rime Fog", "🌫️"),
    51: ("Light Drizzle", "🌧️"),
    53: ("Drizzle", "🌧️"),
    55: ("Heavy Drizzle", "🌧️"),
    61: ("Light Rain", "🌧️"),
    63: ("Rain", "🌧️"),
    65: ("Heavy Rain", "🌧️"),
    80: ("Light Showers", "🌧️"),
    81: ("Showers", "🌧️"),
    82: ("Heavy Showers", "⛈️"),
    95: ("Thunderstorm", "⛈️"),
    96: ("Thunderstorm w/ Hail", "⛈️"),
    99: ("Severe Thunderstorm", "⛈️"),
}

@st.cache_data(ttl=86400)
def geocode_zip(zip_code: str):
    if zip_code in ZIP_DEFAULTS:
        return ZIP_DEFAULTS[zip_code]
    
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {"name": zip_code, "count": 1, "language": "en", "format": "json"}
    
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if "results" in data and data["results"]:
            r = data["results"][0]
            return {"lat": r["latitude"], "lon": r["longitude"], "name": r.get("name", zip_code)}
    except:
        pass
    return None

def haversine(lat1, lon1, lat2, lon2):
    R = 3959
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

def find_nearest_station(lat: float, lon: float):
    nearest = None
    min_dist = float("inf")
    for station_id, info in NOAA_STATIONS.items():
        dist = haversine(lat, lon, info["lat"], info["lon"])
        if dist < min_dist:
            min_dist = dist
            nearest = station_id
    return nearest, min_dist

@st.cache_data(ttl=3600)
def get_tide_data(station_id: str, days: int = 14):
    now = datetime.now(ET_TZ)
    start = now.strftime("%Y%m%d")
    end = (now + timedelta(days=days)).strftime("%Y%m%d")
    
    url = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
    base_params = {
        "begin_date": start,
        "end_date": end,
        "station": station_id,
        "product": "predictions",
        "datum": "MLLW",
        "time_zone": "lst_ldt",
        "units": "english",
        "format": "json",
        "application": "TideWeatherApp",
    }
    
    hilo_df = pd.DataFrame()
    curve_df = pd.DataFrame()
    
    try:
        hilo_params = {**base_params, "interval": "hilo"}
        curve_params = {**base_params, "interval": "6", "end_date": (now + timedelta(days=min(days, 2))).strftime("%Y%m%d")}
        
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            hilo_future = executor.submit(requests.get, url, params=hilo_params, timeout=10)
            curve_future = executor.submit(requests.get, url, params=curve_params, timeout=10)
            
            hilo_resp = hilo_future.result()
            curve_resp = curve_future.result()
        
        hilo_data = hilo_resp.json()
        if "predictions" in hilo_data:
            hilo_df = pd.DataFrame(hilo_data["predictions"])
            hilo_df["t"] = pd.to_datetime(hilo_df["t"])
            hilo_df["v"] = hilo_df["v"].astype(float)
            hilo_df["type_label"] = hilo_df["type"].map({"H": "High", "L": "Low"})
        
        curve_data = curve_resp.json()
        if "predictions" in curve_data:
            curve_df = pd.DataFrame(curve_data["predictions"])
            curve_df["t"] = pd.to_datetime(curve_df["t"])
            curve_df["v"] = curve_df["v"].astype(float)
    except:
        pass
    
    return hilo_df, curve_df

@st.cache_data(ttl=1800)
def get_weather(lat: float, lon: float, days: int = 14):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,wind_speed_10m,wind_gusts_10m,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,wind_speed_10m_max,weather_code,sunrise,sunset",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "timezone": "America/New_York",
        "forecast_days": days,
    }
    
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data.get("hourly", {}).get("time"):
            data["_hourly_index"] = {t: i for i, t in enumerate(data["hourly"]["time"])}
        return data
    except:
        pass
    return {}

def format_time_et(dt):
    return dt.strftime("%-I:%M %p")

def format_date_short(dt):
    return dt.strftime("%a %b %-d")

st.markdown("""
<style>
    .stApp { background-color: #111D3D !important; }
    .block-container { padding-top: 1rem; padding-bottom: 1rem; }
    [data-testid="stMetric"] { padding: 0.3rem; }
    [data-testid="stHorizontalBlock"] { gap: 0.5rem; flex-wrap: nowrap; }
    [data-testid="column"] { min-width: 0 !important; }
    .metric-row { display: flex; gap: 0.5rem; }
    .metric-item { flex: 1; text-align: center; background: rgba(255,255,255,0.05); border-radius: 8px; padding: 0.5rem 0.25rem; }
    .metric-label { font-size: 0.75rem; color: #888; margin-bottom: 0.1rem; }
    .metric-value { font-size: 1.1rem; font-weight: bold; }
    .refresh-btn button { width: 100%; }
    [data-testid="stSidebar"] { background-color: #0D1529 !important; }
</style>
""", unsafe_allow_html=True)

def clear_cache_and_rerun():
    st.cache_data.clear()
    st.rerun()

with st.sidebar:
    st.header("⚙️ Settings")
    
    input_method = st.radio("Location input", ["Zip Code", "Select Location"])
    
    if input_method == "Zip Code":
        zip_code = st.text_input("Enter ZIP code", value="34216")
        geo = geocode_zip(zip_code)
        if geo:
            lat, lon = geo["lat"], geo["lon"]
            location_name = geo["name"]
            station_id, dist = find_nearest_station(lat, lon)
            station_name = NOAA_STATIONS[station_id]["name"]
            st.caption(f"📍 {location_name}")
            st.caption(f"Tide station: {station_name} ({dist:.1f} mi)")
        else:
            st.error("Could not find location")
            st.stop()
    else:
        station_options = {v["name"]: k for k, v in NOAA_STATIONS.items()}
        selected_name = st.selectbox("Select location", options=list(station_options.keys()), index=0)
        station_id = station_options[selected_name]
        lat = NOAA_STATIONS[station_id]["lat"]
        lon = NOAA_STATIONS[station_id]["lon"]
        location_name = selected_name
    
    st.divider()
    days = st.slider("Forecast days", 1, 14, 3)
    ref_line = st.slider("Reference line (ft)", 0.0, 5.0, 1.6, 0.1)
    st.divider()
    if st.button("🔄 Refresh Data", use_container_width=True):
        clear_cache_and_rerun()

now_et = datetime.now(ET_TZ)

st.markdown("""
<style>
#refresh_btn {
    position: fixed;
    top: 0.7rem;
    right: 4rem;
    z-index: 999;
}
button[kind="secondary"]:has(p) {
    background: none !important;
    border: none !important;
    box-shadow: none !important;
    color: #888 !important;
    font-size: 0.8rem !important;
    padding: 0.2rem 0.4rem !important;
    min-height: 0 !important;
}
button[kind="secondary"]:has(p):hover {
    color: #bbb !important;
    background: none !important;
}
</style>
""", unsafe_allow_html=True)

header_cols = st.columns([6, 1])
with header_cols[0]:
    st.title("🌊 Tides & Weather")
with header_cols[1]:
    st.markdown("<div style='margin-top:1.2rem'></div>", unsafe_allow_html=True)
    if st.button(f"{now_et.strftime('%-I:%M %p')}", key="refresh_btn"):
        clear_cache_and_rerun()

tides, tide_curve = get_tide_data(station_id, days)
weather = get_weather(lat, lon, days)

current_tide = None
now_time = now_et.replace(tzinfo=None)
if not tide_curve.empty:
    chart_timestamps = pd.to_datetime(tide_curve["t"]).astype(np.int64) // 10**9
    now_ts = pd.Timestamp(now_time).value // 10**9
    current_tide = np.interp(now_ts, chart_timestamps, tide_curve["v"].values)

if weather:
    hourly = weather.get("hourly", {})
    daily = weather.get("daily", {})
    hourly_index = weather.get("_hourly_index", {})
    
    if hourly.get("time"):
        current_hour_key = now_time.strftime("%Y-%m-%dT%H:00")
        current_idx = hourly_index.get(current_hour_key, 0)
        
        current_temp = hourly["temperature_2m"][current_idx]
        current_wind = hourly["wind_speed_10m"][current_idx]
        current_gust = hourly["wind_gusts_10m"][current_idx]
        current_code = hourly["weather_code"][current_idx]
        
        condition, icon = WMO_CODES.get(current_code, ("Unknown", "❓"))
        
        st.subheader(f"{icon} Current conditions")
        
        tide_str = f"{current_tide:.1f} ft" if current_tide is not None else "--"
        st.markdown(f"""
        <div class="metric-row">
            <div class="metric-item"><div class="metric-label">Tide</div><div class="metric-value">{tide_str}</div></div>
            <div class="metric-item"><div class="metric-label">Temp</div><div class="metric-value">{current_temp:.0f}°F</div></div>
            <div class="metric-item"><div class="metric-label">Wind</div><div class="metric-value">{current_wind:.0f} mph{' ⚠️' if current_wind > 15 else ''}</div></div>
            <div class="metric-item"><div class="metric-label">Gusts</div><div class="metric-value">{current_gust:.0f} mph</div></div>
        </div>
        """, unsafe_allow_html=True)
        
        st.caption(f"{condition} in {location_name}")

today_str_tides = now_time.strftime("%Y-%m-%d")
today_tides_early = tides[tides["t"].dt.strftime("%Y-%m-%d") == today_str_tides]
upcoming_today_early = today_tides_early[today_tides_early["t"] >= now_time]

if weather and weather.get("hourly"):
    hourly_early = weather["hourly"]
    
    st.markdown("**Today's upcoming tides:**")
    
    if upcoming_today_early.empty:
        st.caption("No more tides today")
    else:
        for _, row in upcoming_today_early.iterrows():
            tide_type = row["type_label"]
            tide_time = format_time_et(row["t"])
            tide_height = row["v"]
            arrow = "⬆️" if tide_type == "High" else "⬇️"
            
            tide_hour_key = row["t"].strftime("%Y-%m-%dT%H:00")
            idx = hourly_index.get(tide_hour_key)
            if idx is not None:
                wind_speed = f"{hourly_early['wind_speed_10m'][idx]:.0f}"
                wind_gust = f"{hourly_early['wind_gusts_10m'][idx]:.0f}"
            else:
                wind_speed, wind_gust = "--", "--"
            
            wind_caution = ' ⚠️' if wind_speed != '--' and float(wind_speed) > 15 else ''
            st.markdown(f"{arrow} **{tide_type}** at **{tide_time}** — {tide_height:.1f} ft | Wind: {wind_speed} mph{wind_caution} (gusts {wind_gust})")

st.subheader("🌊 Tide chart")

if not tide_curve.empty:
    chart_data = tide_curve
    
    hilo_48h = tides[tides["t"] <= tide_curve["t"].max()]
    
    chart_timestamps = pd.to_datetime(chart_data["t"]).astype(np.int64) // 10**9
    now_ts = pd.Timestamp(now_time).value // 10**9
    now_height = np.interp(now_ts, chart_timestamps, chart_data["v"].values)
    
    y_min = chart_data["v"].min() - 0.5
    y_max = chart_data["v"].max() + 0.5

    
    fig = go.Figure()
    
    above_vals = np.maximum(chart_data["v"].values, ref_line)
    fig.add_trace(go.Scatter(
        x=chart_data["t"], y=above_vals,
        fill=None, mode="lines", line=dict(width=0),
        showlegend=False, hoverinfo="skip"
    ))
    fig.add_trace(go.Scatter(
        x=chart_data["t"], y=[ref_line] * len(chart_data),
        fill="tonexty", fillcolor="rgba(74, 144, 217, 0.3)",
        mode="lines", line=dict(width=0),
        showlegend=False, hoverinfo="skip"
    ))
    
    fig.add_trace(go.Scatter(
        x=chart_data["t"], y=chart_data["v"],
        mode="lines", name="Tide",
        line=dict(color="#4A90D9", width=2),
        hovertemplate="%{x|%a %I:%M %p}<br>%{y:.1f} ft<extra></extra>"
    ))
    
    fig.add_hline(y=ref_line, line=dict(color="#FF6B6B", width=2, dash="dash"),
                   annotation_text=f"{ref_line:.1f} ft", annotation_position="right",
                   annotation_font=dict(color="#FF6B6B", size=12))
    
    fig.add_trace(go.Scatter(
        x=hilo_48h["t"], y=hilo_48h["v"],
        mode="markers", name="High/Low",
        marker=dict(color="#4A90D9", size=10),
        text=hilo_48h["type_label"],
        hovertemplate="%{text}<br>%{x|%a %I:%M %p}<br>%{y:.1f} ft<extra></extra>"
    ))
    
    fig.add_trace(go.Scatter(
        x=[now_time], y=[now_height],
        mode="markers", name="Now",
        marker=dict(color="#FFD700", size=14, symbol="diamond"),
        hovertemplate="Now<br>%{x|%I:%M %p}<br>%{y:.1f} ft<extra></extra>"
    ))
    
    dates = pd.to_datetime(chart_data["t"]).dt.date.unique()
    shapes = []
    for i, d in enumerate(dates):
        day_start = datetime.combine(d, datetime.min.time())
        day_end = datetime.combine(d + pd.Timedelta(days=1), datetime.min.time())
        shapes.append(dict(
            type="rect", xref="x", yref="paper",
            x0=day_start, x1=day_end, y0=0, y1=1,
            fillcolor="rgba(0,0,0,0)" if i % 2 == 0 else "rgba(255,255,255,0.15)",
            line=dict(width=0), layer="below"
        ))
    
    fig.update_layout(
        height=250, margin=dict(l=0, r=50, t=0, b=0),
        yaxis=dict(range=[y_min, y_max], title="Feet"),
        xaxis=dict(tickformat="%a %d %I:%M %p"),
        showlegend=False,
        shapes=shapes,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)"
    )
    st.plotly_chart(fig, use_container_width=True)
    
    boating_windows = []
    above = chart_data["v"] >= ref_line
    in_window = False
    window_start = None
    
    for i in range(len(chart_data)):
        if above.iloc[i] and not in_window:
            in_window = True
            window_start = chart_data["t"].iloc[i]
        elif not above.iloc[i] and in_window:
            in_window = False
            window_end = chart_data["t"].iloc[i]
            boating_windows.append((window_start, window_end))
    
    if in_window:
        boating_windows.append((window_start, chart_data["t"].iloc[-1]))
    
    usable_windows = []
    for start, end in boating_windows:
        day_start = start.replace(hour=7, minute=0, second=0, microsecond=0)
        
        if start < day_start:
            start = day_start
        
        if start < end:
            usable_windows.append((start, end))
    
    st.caption(f"Reference: {ref_line:.1f} ft MLLW | {days}-day prediction")
    
    if usable_windows:
        st.markdown("**🚤 Boating windows** (tide above reference):")
        for start, end in usable_windows:
            duration = (end - start).total_seconds() / 3600
            st.markdown(f"- **{start.strftime('%a %b %d')}**: Leave {start.strftime('%-I:%M %p')} → Return by {end.strftime('%-I:%M %p')} ({duration:.1f} hrs)")
    else:
        st.caption("No boating windows in forecast period")

with st.expander("⏰ Upcoming tides", expanded=False):
    if not tides.empty:
        upcoming = tides[tides["t"] >= now_time].head(8)
        
        for _, row in upcoming.iterrows():
            tide_type = row["type_label"]
            tide_time = format_time_et(row["t"])
            tide_date = format_date_short(row["t"])
            tide_height = row["v"]
            
            arrow = "⬆️" if tide_type == "High" else "⬇️"
            color = "blue" if tide_type == "High" else "green"
            
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"{arrow} **{tide_type}** - {tide_date}")
                st.caption(f"{tide_time} ET")
            with col2:
                st.markdown(f"**:{color}[{tide_height:.1f} ft]**")
            st.markdown("---")

st.subheader(f"📅 {days}-day forecast")

if weather and weather.get("daily"):
    daily = weather["daily"]
    
    for i in range(min(days, len(daily["time"]))):
        date = datetime.fromisoformat(daily["time"][i])
        temp_max = daily["temperature_2m_max"][i]
        temp_min = daily["temperature_2m_min"][i]
        wind_max = daily["wind_speed_10m_max"][i]
        code = daily["weather_code"][i]
        
        condition, icon = WMO_CODES.get(code, ("Unknown", "❓"))
        
        day_tides = tides[tides["t"].dt.date == date.date()] if not tides.empty else pd.DataFrame()
        
        st.markdown(f"### {icon} {format_date_short(date)}")
        st.caption(condition)
        
        st.markdown(f"""
        <div class="metric-row">
            <div class="metric-item"><div class="metric-label">High</div><div class="metric-value">{temp_max:.0f}°F</div></div>
            <div class="metric-item"><div class="metric-label">Low</div><div class="metric-value">{temp_min:.0f}°F</div></div>
            <div class="metric-item"><div class="metric-label">Wind</div><div class="metric-value">{wind_max:.0f} mph{' ⚠️' if wind_max > 15 else ''}</div></div>
        </div>
        """, unsafe_allow_html=True)
        
        if not day_tides.empty:
            tide_str = " • ".join([
                f"{'⬆️' if r['type']=='H' else '⬇️'} {format_time_et(r['t'])} ({r['v']:.1f}ft)"
                for _, r in day_tides.iterrows()
            ])
            st.caption(f"🌊 {tide_str}")
        
        st.markdown("---")

st.caption("Data: NOAA CO-OPS (tides) | Open-Meteo (weather)")
st.caption("Built with [Snowflake Cortex Code](https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code)")
