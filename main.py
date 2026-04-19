#!/usr/bin/env python3
"""Wallpaper engine driven by normalized daily solar elevation (-1..1)."""

import json
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from astral import LocationInfo
from astral.sun import elevation

ROOT_DIR = Path(__file__).parent
ENV_PATH = ROOT_DIR / ".env"

IMAGES_DIR = ROOT_DIR / "images"
GEO_CACHE_PATH = ROOT_DIR / ".geo_cache"

DEFAULTS = {
    # Safe fallback values; override in .env for your real location/timezone.
    "LATITUDE": "0.0",
    "LONGITUDE": "0.0",
    "TIMEZONE": "UTC",
    "CHECK_INTERVAL": "60",
    "SAMPLES_PER_DAY": "1440",
    "IMAGE_MAP": "1,2,3,4,5,6,7,8,9,10,11",
    "ORDERED_IMAGE_RANGES": "1:-0.05:0.05,2:0.05:0.25,3:0.25:0.9,4:0.9:0.9,5:0.9:0.25,6:0.25:0.05,7:0.05:-0.05,8:-0.05:-0.2,9:-0.2:-0.6,10:-0.6:-0.25,11:-0.25:-0.05",
    "GEO_UPDATE_DAYS": "3",
}

def load_env(path):
    """Load KEY=VALUE pairs from .env file (simple parser)."""
    data = {}
    if not path.exists():
        return data

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        data[key] = value
    return data


def _is_float(value):
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _load_geo_cache():
    """Return cached geo dict or None if unavailable/invalid."""
    if not GEO_CACHE_PATH.exists():
        return None
    try:
        data = json.loads(GEO_CACHE_PATH.read_text(encoding="utf-8"))
        lat = float(data["lat"])
        lon = float(data["lon"])
        tz_name = str(data["timezone"]).strip()
        if not tz_name:
            return None
        ZoneInfo(tz_name)
        return {"lat": lat, "lon": lon, "timezone": tz_name}
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def ensure_env_integrity():
    """Validate and self-heal .env required values.

    Fills missing keys from DEFAULTS and normalizes invalid values.
    If location fields are missing/invalid, tries geo cache first,
    then online geolocation as fallback.
    """
    env = load_env(ENV_PATH)

    # Ensure all required keys exist.
    for key, default_val in DEFAULTS.items():
        if key not in env or not str(env[key]).strip():
            _update_env_value(key, default_val)
            env[key] = default_val

    # Normalize non-location fields.
    if not env["CHECK_INTERVAL"].isdigit() or int(env["CHECK_INTERVAL"]) < 1:
        _update_env_value("CHECK_INTERVAL", DEFAULTS["CHECK_INTERVAL"])
        env["CHECK_INTERVAL"] = DEFAULTS["CHECK_INTERVAL"]

    if not env["SAMPLES_PER_DAY"].isdigit() or int(env["SAMPLES_PER_DAY"]) < 2:
        _update_env_value("SAMPLES_PER_DAY", DEFAULTS["SAMPLES_PER_DAY"])
        env["SAMPLES_PER_DAY"] = DEFAULTS["SAMPLES_PER_DAY"]

    if not env["GEO_UPDATE_DAYS"].isdigit() or int(env["GEO_UPDATE_DAYS"]) < 0:
        _update_env_value("GEO_UPDATE_DAYS", DEFAULTS["GEO_UPDATE_DAYS"])
        env["GEO_UPDATE_DAYS"] = DEFAULTS["GEO_UPDATE_DAYS"]

    try:
        image_map = [int(v.strip()) for v in env["IMAGE_MAP"].split(",") if v.strip()]
        if not image_map:
            raise ValueError()
    except ValueError:
        _update_env_value("IMAGE_MAP", DEFAULTS["IMAGE_MAP"])
        env["IMAGE_MAP"] = DEFAULTS["IMAGE_MAP"]

    try:
        parse_ordered_image_ranges(env.get("ORDERED_IMAGE_RANGES", ""))
    except ValueError:
        _update_env_value("ORDERED_IMAGE_RANGES", DEFAULTS["ORDERED_IMAGE_RANGES"])
        env["ORDERED_IMAGE_RANGES"] = DEFAULTS["ORDERED_IMAGE_RANGES"]

    # Validate location fields.
    location_valid = True
    if not _is_float(env.get("LATITUDE")):
        location_valid = False
    if not _is_float(env.get("LONGITUDE")):
        location_valid = False
    tz_name = str(env.get("TIMEZONE", "")).strip()
    if not tz_name:
        location_valid = False
    else:
        try:
            ZoneInfo(tz_name)
        except Exception:
            location_valid = False

    if location_valid:
        return

    # Recover location if missing/invalid: cache first, then internet.
    cached = _load_geo_cache()
    if cached is not None:
        _update_env_value("LATITUDE", str(cached["lat"]))
        _update_env_value("LONGITUDE", str(cached["lon"]))
        _update_env_value("TIMEZONE", cached["timezone"])
        return

    try:
        lat, lon, tz_new = _fetch_geo()
        _update_env_value("LATITUDE", str(lat))
        _update_env_value("LONGITUDE", str(lon))
        _update_env_value("TIMEZONE", tz_new)
        GEO_CACHE_PATH.write_text(
            json.dumps(
                {
                    "updated": datetime.now().astimezone().isoformat(),
                    "lat": lat,
                    "lon": lon,
                    "timezone": tz_new,
                }
            ),
            encoding="utf-8",
        )
    except (urllib.error.URLError, OSError, RuntimeError):
        # Last-resort fallback to safe defaults.
        _update_env_value("LATITUDE", DEFAULTS["LATITUDE"])
        _update_env_value("LONGITUDE", DEFAULTS["LONGITUDE"])
        _update_env_value("TIMEZONE", DEFAULTS["TIMEZONE"])


def load_config():
    env = DEFAULTS.copy()
    env.update(load_env(ENV_PATH))

    image_map = [int(v.strip()) for v in env["IMAGE_MAP"].split(",") if v.strip()]
    if not image_map:
        raise ValueError("IMAGE_MAP must contain at least one image number")

    ordered_image_ranges = parse_ordered_image_ranges(env.get("ORDERED_IMAGE_RANGES", ""))

    config = {
        "latitude": float(env["LATITUDE"]),
        "longitude": float(env["LONGITUDE"]),
        "timezone": env["TIMEZONE"],
        "check_interval": max(1, int(env["CHECK_INTERVAL"])),
        "samples_per_day": max(2, int(env["SAMPLES_PER_DAY"])),
        "image_map": image_map,
        "ordered_image_ranges": ordered_image_ranges,
        "geo_update_days": max(0, int(env["GEO_UPDATE_DAYS"])),
    }
    return config


def parse_ordered_image_ranges(raw_value):
    """Parse ordered ranges: image:min:max,image:min:max,..."""
    if not raw_value.strip():
        return []

    parsed = []
    for item in raw_value.split(","):
        part = item.strip()
        if not part:
            continue
        pieces = [p.strip() for p in part.split(":")]
        if len(pieces) != 3:
            raise ValueError(
                "ORDERED_IMAGE_RANGES must use image:min:max entries separated by commas"
            )
        image_s, min_s, max_s = pieces
        parsed.append(
            {
                "image": int(image_s),
                "min": float(min_s),
                "max": float(max_s),
            }
        )
    return parsed


def _geo_cache_stale(max_age_days):
    """Return True if geo cache is missing or older than max_age_days."""
    if not GEO_CACHE_PATH.exists():
        return True
    try:
        data = json.loads(GEO_CACHE_PATH.read_text(encoding="utf-8"))
        last = datetime.fromisoformat(data["updated"])
        return (datetime.now().astimezone() - last).days >= max_age_days
    except (json.JSONDecodeError, KeyError, ValueError):
        return True


def _fetch_geo():
    """Fetch latitude, longitude, timezone from IP geolocation."""
    req = urllib.request.Request(
        "http://ip-api.com/json/?fields=status,lat,lon,timezone",
        headers={"User-Agent": "wallpaper-engine/1.0"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    if data.get("status") != "success":
        raise RuntimeError(f"Geolocation failed: {data}")
    return data["lat"], data["lon"], data["timezone"]


def maybe_update_geo(config):
    """Update coordinates from IP geolocation if cache is stale.

    Updates both the in-memory config and writes new values to .env.
    Returns True if coordinates were updated.
    """
    if config["geo_update_days"] <= 0:
        return False
    if not _geo_cache_stale(config["geo_update_days"]):
        return False

    try:
        lat, lon, tz_name = _fetch_geo()
    except (urllib.error.URLError, OSError, RuntimeError) as e:
        print(f"Geolocation update skipped (no connection or error): {e}", file=sys.stderr)
        return False

    config["latitude"] = lat
    config["longitude"] = lon
    config["timezone"] = tz_name

    _update_env_value("LATITUDE", str(lat))
    _update_env_value("LONGITUDE", str(lon))
    _update_env_value("TIMEZONE", tz_name)

    GEO_CACHE_PATH.write_text(
        json.dumps({"updated": datetime.now().astimezone().isoformat(),
                    "lat": lat, "lon": lon, "timezone": tz_name}),
        encoding="utf-8",
    )
    return True


def _update_env_value(key, value):
    """Update or append a KEY=VALUE in the .env file."""
    if not ENV_PATH.exists():
        ENV_PATH.write_text(f"{key}={value}\n", encoding="utf-8")
        return

    lines = ENV_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
    found = False
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
            lines[i] = f"{key}={value}\n"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}\n")
    ENV_PATH.write_text("".join(lines), encoding="utf-8")


def build_daily_curve(target_date, tz, latitude, longitude, samples_per_day):
    """Build one day's solar elevation degrees and normalized values (-1..1)."""
    loc = LocationInfo(latitude=latitude, longitude=longitude, timezone=str(tz))
    total_seconds = 24 * 60 * 60
    step_seconds = total_seconds / (samples_per_day - 1)

    degrees = []
    for i in range(samples_per_day):
        seconds = int(round(i * step_seconds))
        ts = datetime.combine(target_date, datetime.min.time(), tz) + timedelta(seconds=seconds)
        degrees.append(elevation(loc.observer, ts))

    max_abs = max(abs(min(degrees)), abs(max(degrees)))
    if max_abs == 0:
        normalized = [0.0] * len(degrees)
    else:
        normalized = [d / max_abs for d in degrees]

    return {
        "date": target_date,
        "degrees": degrees,
        "normalized": normalized,
    }


def normalized_at(now, curve):
    """Return curve value for current time index in current day."""
    idx = sample_index_at(now, len(curve["normalized"]))
    return curve["normalized"][idx]


def sample_index_at(now, total_samples):
    """Return sample index for current day time."""
    sec = now.hour * 3600 + now.minute * 60 + now.second
    idx = round((sec / 86400) * (total_samples - 1))
    idx = max(0, min(idx, total_samples - 1))
    return idx


def image_for_normalized(value, image_map):
    """Map a normalized -1..1 value to an image number using equal bins."""
    clamped = max(-1.0, min(1.0, value))
    progress = (clamped + 1.0) / 2.0
    idx = int(progress * len(image_map))
    idx = min(idx, len(image_map) - 1)
    return image_map[idx]


def _match_rule(value, rule_set):
    """Find matching image from a rule set, with boundary clamping."""
    if not rule_set:
        return None

    for r in rule_set:
        low = min(r["min"], r["max"])
        high = max(r["min"], r["max"])
        if low <= value <= high:
            return r["image"]

    # No exact match — clamp to the nearest boundary rule
    overall_low = min(min(r["min"], r["max"]) for r in rule_set)
    overall_high = max(max(r["min"], r["max"]) for r in rule_set)

    if value > overall_high:
        for r in rule_set:
            if max(r["min"], r["max"]) == overall_high:
                return r["image"]
    if value < overall_low:
        for r in rule_set:
            if min(r["min"], r["max"]) == overall_low:
                return r["image"]

    return None


def build_image_timeline(curve, config):
    """Build image selections for each sample in today's curve.

    Rules whose max >= min are treated as ascending (sun rising),
    rules whose max < min are treated as descending (sun setting).
    Rules with max == min (peak) belong to both sets.
    At each sample the curve direction is checked and the matching
    set is used, so the same normalized value can map to different
    images in the morning vs evening.
    """
    normalized = curve["normalized"]
    image_map = config["image_map"]
    rules = config["ordered_image_ranges"]

    if not rules:
        return [image_for_normalized(v, image_map) for v in normalized]

    ascending_rules = []
    descending_rules = []
    for r in rules:
        if r["max"] >= r["min"]:
            ascending_rules.append(r)
        if r["max"] <= r["min"]:
            descending_rules.append(r)

    ascending_rules.sort(key=lambda r: min(r["min"], r["max"]))
    descending_rules.sort(key=lambda r: max(r["min"], r["max"]), reverse=True)

    n = len(normalized)
    timeline = []

    for i in range(n):
        value = normalized[i]
        if i < n - 1:
            ascending = normalized[i + 1] >= normalized[i]
        else:
            ascending = normalized[i] >= normalized[i - 1] if i > 0 else True

        rule_set = ascending_rules if ascending else descending_rules
        matched = _match_rule(value, rule_set)

        if matched is not None:
            timeline.append(matched)
        else:
            timeline.append(image_for_normalized(value, image_map))

    return timeline


def image_path(number):
    return IMAGES_DIR / f"{number}.png"


def set_wallpaper(path):
    """Set the KDE Plasma wallpaper using plasma-apply-wallpaperimage."""
    subprocess.run(
        ["plasma-apply-wallpaperimage", str(path)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def main():
    ensure_env_integrity()
    config = load_config()

    if maybe_update_geo(config):
        print(f"Geolocation updated: lat={config['latitude']}, lon={config['longitude']}, tz={config['timezone']}")
    else:
        print("Geolocation: using cached/configured coordinates")

    tz = ZoneInfo(config["timezone"])

    curve = build_daily_curve(
        date.today(),
        tz,
        config["latitude"],
        config["longitude"],
        config["samples_per_day"],
    )
    image_timeline = build_image_timeline(curve, config)
    current_image = None

    print(
        "Wallpaper engine started "
        f"(lat={config['latitude']}, lon={config['longitude']}, tz={config['timezone']})"
    )
    print(f"Images directory: {IMAGES_DIR}")
    print(
        f"Curve prepared for {curve['date']} with {config['samples_per_day']} points; "
        f"range={min(curve['degrees']):.2f}..{max(curve['degrees']):.2f} degrees"
    )
    if config["ordered_image_ranges"]:
        print(f"Using {len(config['ordered_image_ranges'])} ordered image ranges")

    while True:
        try:
            now = datetime.now(tz=tz)
            if now.date() != curve["date"]:
                curve = build_daily_curve(
                    now.date(),
                    tz,
                    config["latitude"],
                    config["longitude"],
                    config["samples_per_day"],
                )
                image_timeline = build_image_timeline(curve, config)
                print(
                    f"[{now:%H:%M}] Recalculated curve for {curve['date']} "
                    f"({config['samples_per_day']} points)"
                )

            value = normalized_at(now, curve)
            sample_idx = sample_index_at(now, len(image_timeline))
            img_num = image_timeline[sample_idx]
            path = image_path(img_num)

            if img_num != current_image:
                if not path.exists():
                    print(f"[{now:%H:%M}] Image {img_num} selected but {path} not found, skipping")
                else:
                    set_wallpaper(path)
                    current_image = img_num
                    print(f"[{now:%H:%M}] Wallpaper → {img_num}.png (normalized={value:.3f})")

        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)

        time.sleep(config["check_interval"])


if __name__ == "__main__":
    main()
