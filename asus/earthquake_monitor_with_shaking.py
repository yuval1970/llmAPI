#!/usr/bin/env python3
"""
earthquake_monitor_with_shaking.py

Combines two previously built and tested pieces:

  1. Real-time global earthquake detection (EMSC WebSocket + USGS
     polling, deduplicated) -- from global_earthquake_monitor.py

  2. Scientifically real ground-motion estimation using OpenQuake's
     hazardlib BSSA14 GMPE -- from openquake_shaking_estimate.py
     (confirmed working on your machine, in the openquake_conda
     environment)

WHAT THIS DOES
--------------
Watches for new earthquakes in real time. Whenever a detected event's
magnitude meets or exceeds SHAKING_MAGNITUDE_THRESHOLD, it automatically
runs BSSA14 to estimate expected shaking (PGA in %g) at each configured
TARGET_LOCATION, based on the real distance from the actual epicenter to
that location.

IMPORTANT: MUST BE RUN INSIDE THE openquake_conda ENVIRONMENT
------------------------------------------------------------------
    conda activate openquake_conda
    python earthquake_monitor_with_shaking.py

This script needs openquake.hazardlib, which is only installed in that
environment (confirmed working there, not in your other environments).

REQUIREMENTS (already satisfied inside openquake_conda)
------------------------------------------------------------
    websocket-client, requests, numpy, openquake.hazardlib

USAGE
-----
    python earthquake_monitor_with_shaking.py

Edit SHAKING_MAGNITUDE_THRESHOLD and TARGET_LOCATIONS below to configure.
"""

import json
import math
import time
import threading
from datetime import datetime, timezone

import requests
import websocket
import numpy as np
import matplotlib
matplotlib.use("Agg")  # non-interactive backend -- safe to call from any
                       # thread (EMSC's websocket thread or the main
                       # USGS-polling thread), just saves PNG files
                       # rather than trying to pop up GUI windows
import matplotlib.pyplot as plt
import os

# Import hazardlib ONCE at module load time, on the main thread, before any
# background threads start. Importing it lazily inside a function that can
# be called from multiple threads (EMSC's websocket thread vs. the main
# USGS-polling thread) risks a race during hazardlib's metaclass-based GSIM
# registration, which is the suspected cause of an intermittent
# "'BooreEtAl2014' object has no attribute 'get_mean_and_stddevs'" error
# seen when this was imported lazily per-call instead.
try:
    from openquake.hazardlib.gsim.boore_2014 import BooreEtAl2014
    from openquake.hazardlib.imt import PGA
    from openquake.hazardlib.const import StdDev
    from openquake.hazardlib.contexts import RuptureContext
    _GMPE = BooreEtAl2014()  # single shared instance, built once
    _HAZARDLIB_OK = True
except ImportError:
    _HAZARDLIB_OK = False

# --------------------------------------------------------------------------
# CONFIGURATION
# --------------------------------------------------------------------------

EMSC_WS_URL = "wss://www.seismicportal.eu/standing_order/websocket"
USGS_FEED_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"
USGS_POLL_INTERVAL_SEC = 60

MIN_MAGNITUDE = 0.0      # minimum magnitude to even track/report at all
BBOX = None                # None = global. Or (minlat, maxlat, minlon, maxlon)

# Deduplication thresholds (same event reported by both EMSC and USGS)
DEDUP_TIME_SEC = 90
DEDUP_DIST_DEG = 1.0
DEDUP_MAG_DELTA = 1.0

# Only run the (heavier) shaking computation for events at or above this
# magnitude -- avoids wasting time computing shaking estimates for tiny,
# clearly-inconsequential events.
SHAKING_MAGNITUDE_THRESHOLD = 5.0

# Locations to estimate shaking at, whenever a qualifying event occurs.
# (name, lat, lon)
TARGET_LOCATIONS = [
    ("Tel Aviv", 32.0853, 34.7818),
    ("Jerusalem", 31.7683, 35.2137),
    ("Los Angeles", 34.0522, -118.2437),
    ("Athens", 37.9838, 23.7275),
    ("Nuku'alofa, Tonga", -21.1394, -175.2049),  # near Neiafu, for a real nonzero test case
]

# BSSA14 (like most GMPEs) is empirically calibrated from real recordings
# typically only out to a few hundred km. Beyond this range you're not
# just getting "very small" numbers -- you're extrapolating the model
# far outside where it was ever validated, and the physical mechanism
# of any distant shaking (long-period surface waves) isn't what these
# near-field body-wave models represent anyway. Skip the computation
# entirely beyond this distance rather than showing misleading precision
# on a physically meaningless number.
MAX_VALID_DISTANCE_KM = 300

DEFAULT_VS30 = 400.0  # fallback ONLY if the real USGS lookup fails

# Cache so we don't re-query the same location's Vs30 on every event
_vs30_cache = {}

USGS_VS30_SERVICE_URL = "https://earthquake.usgs.gov/arcgis/rest/services/eq/vs30_mosaic/MapServer/identify"


def lookup_vs30(lat, lon):
    """
    Query USGS's real Global Vs30 Mosaic service (Heath et al. 2020,
    topographic-slope-based, 30 arc-second resolution) for the actual
    Vs30 at a specific point, instead of using a flat placeholder value.

    Returns Vs30 in m/s, or DEFAULT_VS30 with a warning if the lookup
    fails for any reason.

    NOTE: this specific query has not been test-executed against a live
    connection in this environment. The ArcGIS "identify" operation
    pattern used here is standard, but the exact JSON field name holding
    the pixel value can vary between services (commonly "Pixel Value"
    or "Stretched_Value" for raster layers). This function tries a few
    likely field names and falls back to printing the raw response if
    none match, so it can be fixed against real output rather than
    guessed further.
    """
    cache_key = (round(lat, 3), round(lon, 3))
    if cache_key in _vs30_cache:
        return _vs30_cache[cache_key]

    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "sr": "4326",
        "tolerance": "2",
        "mapExtent": f"{lon-1},{lat-1},{lon+1},{lat+1}",
        "imageDisplay": "400,400,96",
        "returnGeometry": "false",
        "f": "json",
    }

    try:
        resp = requests.get(USGS_VS30_SERVICE_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [])
        if not results:
            print(f"      [Vs30] no results for ({lat}, {lon}), "
                  f"using default {DEFAULT_VS30}")
            _vs30_cache[cache_key] = DEFAULT_VS30
            return DEFAULT_VS30

        attrs = results[0].get("attributes", {})
        # Confirmed real field name from live response: 'Classify.Pixel Value'
        # Kept other likely names as fallback in case the service response
        # shape varies by query/version.
        for key in ("Classify.Pixel Value", "Pixel Value", "Stretched_Value", "Value", "value"):
            if key in attrs:
                try:
                    vs30 = float(attrs[key])
                    _vs30_cache[cache_key] = vs30
                    return vs30
                except (TypeError, ValueError):
                    continue

        print(f"      [Vs30] unexpected response shape for ({lat}, {lon}): "
              f"{attrs} -- using default {DEFAULT_VS30}. Please share this "
              f"output so the correct field name can be fixed.")
        _vs30_cache[cache_key] = DEFAULT_VS30
        return DEFAULT_VS30

    except Exception as e:
        print(f"      [Vs30] lookup failed for ({lat}, {lon}): "
              f"{type(e).__name__}: {e} -- using default {DEFAULT_VS30}")
        _vs30_cache[cache_key] = DEFAULT_VS30
        return DEFAULT_VS30

# --------------------------------------------------------------------------

_lock = threading.Lock()
_known_events = []  # list of dicts: {time, lat, lon, mag, depth, place, sources:set()}


def in_bbox(lat, lon):
    if BBOX is None:
        return True
    minlat, maxlat, minlon, maxlon = BBOX
    return minlat <= lat <= maxlat and minlon <= lon <= maxlon


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# ============================================================================
# Ground motion computation (confirmed-working BSSA14 pattern from
# openquake_shaking_estimate.py)
# ============================================================================

def compute_shaking_at_targets(magnitude, depth_km, event_lat, event_lon):
    """Run BSSA14 for the real distance from the event to each configured
    target location that falls within MAX_VALID_DISTANCE_KM, using each
    location's REAL Vs30 (looked up from USGS's Global Vs30 Mosaic).
    Targets beyond MAX_VALID_DISTANCE_KM are returned separately, marked
    as out-of-range, since BSSA14 isn't calibrated for such distances and
    a computed value there would be misleading rather than useful."""
    if not _HAZARDLIB_OK:
        raise RuntimeError("openquake.hazardlib failed to import at "
                          "startup -- check you're in the "
                          "openquake_conda environment")

    all_distances = [(name, tlat, tlon,
                      haversine_km(event_lat, event_lon, tlat, tlon))
                     for name, tlat, tlon in TARGET_LOCATIONS]

    in_range = [(name, tlat, tlon, dist) for name, tlat, tlon, dist in all_distances
               if dist <= MAX_VALID_DISTANCE_KM]
    out_of_range = [(name, dist) for name, tlat, tlon, dist in all_distances
                    if dist > MAX_VALID_DISTANCE_KM]

    if not in_range:
        return [], out_of_range

    distances = [dist for _, _, _, dist in in_range]
    vs30_values = [lookup_vs30(tlat, tlon) for _, tlat, tlon, _ in in_range]
    n = len(distances)

    ctx = RuptureContext()
    ctx.mag = magnitude
    ctx.rake = 0.0
    ctx.dip = 90.0
    ctx.ztor = depth_km
    ctx.rjb = np.array(distances, dtype=float)
    ctx.rrup = np.array(distances, dtype=float)
    ctx.vs30 = np.array(vs30_values, dtype=float)
    ctx.vs30measured = np.full(n, True)
    ctx.z1pt0 = np.full(n, -999.0)

    if not hasattr(_GMPE, "compute"):
        raise RuntimeError(
            f"_GMPE ({type(_GMPE)}) has no compute() method. Available "
            f"attrs: {[a for a in dir(_GMPE) if not a.startswith('_')]}"
        )

    imts = [PGA()]
    mean = np.zeros((1, n))
    sig = np.zeros((1, n))
    tau = np.zeros((1, n))
    phi = np.zeros((1, n))
    _GMPE.compute(ctx, imts, mean, sig, tau, phi)
    pga_percent_g = np.exp(mean[0]) * 100

    results = []
    for (name, _, _, dist), vs30, pga in zip(in_range, vs30_values, pga_percent_g):
        results.append((name, dist, vs30, float(pga)))
    return results, out_of_range


SHAKEMAP_OUTPUT_DIR = "shakemaps"


def generate_shakemap_plot(event, in_range_results, out_of_range_results):
    """
    Generate a visual shake map: a contour plot of estimated PGA around
    the epicenter (using a generic Vs30 for the background field, since
    querying real per-pixel Vs30 for every grid point would be very slow),
    with the actual configured target locations marked and labeled with
    their real, Vs30-adjusted PGA values from compute_shaking_at_targets().

    Saves a PNG file and returns its path. Does not display an
    interactive window, since this can be called from a background
    thread during live monitoring -- open the saved file manually.
    """
    if not _HAZARDLIB_OK:
        return None

    os.makedirs(SHAKEMAP_OUTPUT_DIR, exist_ok=True)

    lat, lon = event["lat"], event["lon"]
    magnitude = event["mag"]
    depth_km = event.get("depth", 10.0)

    # Build a grid around the epicenter, sized roughly to
    # MAX_VALID_DISTANCE_KM so the whole meaningful area is shown.
    span_deg = max(1.0, MAX_VALID_DISTANCE_KM / 111.0 * 1.3)  # ~km per degree latitude
    grid_n = 60
    lats = np.linspace(lat - span_deg, lat + span_deg, grid_n)
    lons = np.linspace(lon - span_deg, lon + span_deg, grid_n)

    generic_vs30 = 400.0  # flat background assumption -- see docstring
    pga_grid = np.zeros((grid_n, grid_n))

    for i, la in enumerate(lats):
        row_dists = [haversine_km(lat, lon, la, lo) for lo in lons]
        ctx = RuptureContext()
        ctx.mag = magnitude
        ctx.rake = 0.0
        ctx.dip = 90.0
        ctx.ztor = depth_km
        ctx.rjb = np.array(row_dists, dtype=float)
        ctx.rrup = np.array(row_dists, dtype=float)
        ctx.vs30 = np.full(grid_n, generic_vs30, dtype=float)
        ctx.vs30measured = np.full(grid_n, True)
        ctx.z1pt0 = np.full(grid_n, -999.0)

        imts = [PGA()]
        mean = np.zeros((1, grid_n))
        sig = np.zeros((1, grid_n))
        tau = np.zeros((1, grid_n))
        phi = np.zeros((1, grid_n))
        _GMPE.compute(ctx, imts, mean, sig, tau, phi)
        pga_grid[i, :] = np.exp(mean[0]) * 100

    fig, ax = plt.subplots(figsize=(9, 7))
    contour = ax.contourf(lons, lats, pga_grid, levels=20, cmap="YlOrRd")
    plt.colorbar(contour, label="Estimated PGA (%g), generic Vs30=400 m/s")
    ax.plot(lon, lat, "k*", markersize=22, label="Epicenter")

    for name, dist, vs30, pga in in_range_results:
        # Recover this target's actual lat/lon from TARGET_LOCATIONS
        tlat, tlon = next((la, lo) for n, la, lo in TARGET_LOCATIONS if n == name)
        ax.plot(tlon, tlat, "bo", markersize=9)
        ax.annotate(f"{name}\n{dist:.0f}km, Vs30={vs30:.0f}, "
                   f"PGA~{pga:.3f}%g",
                   (tlon, tlat), textcoords="offset points", xytext=(8, 8),
                   fontsize=8, color="blue",
                   bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="blue", alpha=0.8))

    # Note: out-of-range targets aren't plotted here since they fall
    # outside this zoomed-in map's extent (span is sized to
    # MAX_VALID_DISTANCE_KM around the epicenter).

    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title(f"Shake Map (BSSA14 estimate) -- M{magnitude} "
                f"{event['place']}\n{datetime.fromtimestamp(event['time'], tz=timezone.utc).isoformat()}")
    ax.legend(loc="upper right")
    plt.tight_layout()

    safe_place = "".join(c if c.isalnum() else "_" for c in event["place"])[:40]
    timestamp = datetime.fromtimestamp(event["time"], tz=timezone.utc).strftime("%Y%m%dT%H%M%S")
    filename = os.path.join(SHAKEMAP_OUTPUT_DIR, f"shakemap_{timestamp}_{safe_place}.png")
    plt.savefig(filename, dpi=120)
    plt.close(fig)

    return filename


def print_shaking_estimate(event):
    print(f"\n  --- Estimated shaking (BSSA14) for M{event['mag']} "
          f"{event['place']} ---")
    try:
        results, out_of_range = compute_shaking_at_targets(
            event["mag"], event.get("depth", 10.0),
            event["lat"], event["lon"]
        )
    except Exception as e:
        print(f"      Shaking computation failed: {type(e).__name__}: {e}")
        return

    for name, dist, vs30, pga in results:
        print(f"      {name:<20} {dist:>8.0f} km   Vs30={vs30:>6.0f} m/s   "
              f"PGA ~{pga:>7.3f} %g")

    for name, dist in out_of_range:
        print(f"      {name:<20} {dist:>8.0f} km   "
              f"(beyond {MAX_VALID_DISTANCE_KM}km -- outside BSSA14's "
              f"valid range, skipped)")

    try:
        map_path = generate_shakemap_plot(event, results, out_of_range)
        if map_path:
            print(f"      Shake map saved: {map_path}")
    except Exception as e:
        print(f"      Shake map generation failed: {type(e).__name__}: {e}")

    print()


# ============================================================================
# Event detection + dedup (from global_earthquake_monitor.py)
# ============================================================================

def find_matching_event(t, lat, lon, mag):
    for ev in _known_events:
        if abs(ev["time"] - t) > DEDUP_TIME_SEC:
            continue
        if abs(ev["lat"] - lat) > DEDUP_DIST_DEG or abs(ev["lon"] - lon) > DEDUP_DIST_DEG:
            continue
        if mag is not None and ev["mag"] is not None and abs(ev["mag"] - mag) > DEDUP_MAG_DELTA:
            continue
        return ev
    return None


def report_event(source, t, lat, lon, mag, depth, place):
    if mag is not None and mag < MIN_MAGNITUDE:
        return
    if not in_bbox(lat, lon):
        return

    with _lock:
        match = find_matching_event(t, lat, lon, mag)
        if match:
            if source not in match["sources"]:
                match["sources"].add(source)
                print(f"  [confirmed by {source}] M{mag} {place} "
                      f"(now confirmed by: {sorted(match['sources'])})")
            return

        event = {
            "time": t, "lat": lat, "lon": lon, "mag": mag,
            "depth": depth, "place": place, "sources": {source},
        }
        _known_events.append(event)

    dt = datetime.fromtimestamp(t, tz=timezone.utc)
    print(f"\n  *** NEW EVENT ({source}) ***")
    print(f"      M{mag}  {place}")
    print(f"      Time: {dt.isoformat()}")
    print(f"      Location: {lat:.4f}, {lon:.4f}  Depth: {depth} km\n")

    if mag is not None and mag >= SHAKING_MAGNITUDE_THRESHOLD:
        print_shaking_estimate(event)


# ============================================================================
# EMSC WebSocket
# ============================================================================

def emsc_on_message(ws, message):
    try:
        payload = json.loads(message)
        data = payload.get("data", {}).get("properties", payload.get("data", {}))
        lat = data.get("lat")
        lon = data.get("lon")
        mag = data.get("mag")
        depth = data.get("depth", 10.0)
        place = data.get("flynn_region") or data.get("region")
        time_str = data.get("time")

        if lat is None or lon is None or time_str is None:
            return

        t = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%S.%fZ") \
            .replace(tzinfo=timezone.utc).timestamp()

        report_event("EMSC", t, lat, lon, mag, depth, place)
    except Exception as e:
        print(f"  [EMSC] failed to parse message: {e}")


def emsc_on_error(ws, error):
    print(f"  [EMSC] connection error: {error}")


def emsc_on_close(ws, close_status_code, close_msg):
    print("  [EMSC] connection closed")


def emsc_on_open(ws):
    print("  [EMSC] connected, listening for real-time events...")


def run_emsc_listener():
    while True:
        try:
            ws = websocket.WebSocketApp(
                EMSC_WS_URL,
                on_open=emsc_on_open,
                on_message=emsc_on_message,
                on_error=emsc_on_error,
                on_close=emsc_on_close,
            )
            ws.run_forever()
        except Exception as e:
            print(f"  [EMSC] listener crashed: {e}")
        print("  [EMSC] reconnecting in 10s...")
        time.sleep(10)


# ============================================================================
# USGS polling
# ============================================================================

def poll_usgs():
    try:
        resp = requests.get(USGS_FEED_URL, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [USGS] request failed: {e}")
        return

    data = resp.json()
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        coords = feature.get("geometry", {}).get("coordinates", [None, None, None])
        lon, lat, depth = coords
        mag = props.get("mag")
        place = props.get("place")
        time_ms = props.get("time")

        if lat is None or lon is None or time_ms is None:
            continue

        t = time_ms / 1000
        report_event("USGS", t, lat, lon, mag, depth or 10.0, place)


def run_usgs_poller():
    while True:
        poll_usgs()
        time.sleep(USGS_POLL_INTERVAL_SEC)


# ============================================================================

def main():
    print("Starting combined earthquake monitor + shaking estimator")
    print(f"Min magnitude tracked: {MIN_MAGNITUDE}")
    print(f"Shaking estimate threshold: M{SHAKING_MAGNITUDE_THRESHOLD}+")
    print(f"Target locations: {[name for name, _, _ in TARGET_LOCATIONS]}")
    print(f"Region filter: {'global' if BBOX is None else BBOX}\n")
    print("NOTE: this reports earthquakes that have already occurred, "
          "and estimates shaking using a real GMPE (BSSA14). It cannot "
          "predict earthquakes before they happen.\n")

    if not _HAZARDLIB_OK:
        print("ERROR: openquake.hazardlib not found. This script must "
              "be run inside the openquake_conda environment:\n"
              "    conda activate openquake_conda\n"
              "    python earthquake_monitor_with_shaking.py")
        return

    emsc_thread = threading.Thread(target=run_emsc_listener, daemon=True)
    emsc_thread.start()

    try:
        run_usgs_poller()
    except KeyboardInterrupt:
        print("\nStopped by user.")


if __name__ == "__main__":
    main()
