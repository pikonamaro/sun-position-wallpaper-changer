#!!!VIBE CODED!!!

# Solar Wallpaper Engine

A small Python app that changes your KDE Plasma wallpaper based on the sun position.

It calculates a daily solar curve for your location, normalizes it, and maps each moment to an image number.

## Features

- Uses real solar elevation for your coordinates
- Recalculates curve at startup and on date change
- Supports two image selection modes:
  - `IMAGE_MAP` (simple equal bins)
  - `ORDERED_IMAGE_RANGES` (different morning/evening mapping for same value)
- Optional IP geolocation refresh on startup (cached, periodic)
- Includes a preview tool with table + PNG + interactive HTML chart

## Requirements

- Linux with KDE Plasma
- Python 3.10+
- `plasma-apply-wallpaperimage` available in PATH

Python packages used:

- `astral`
- `matplotlib` (for PNG graph in preview script)
- `plotly` (for interactive HTML graph in preview script)

## Setup

Create and activate virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install astral matplotlib plotly
```

Place your wallpaper images in the `images/` folder as numbered files:

- `images/1.png`
- `images/2.png`
- ...

## Configuration (.env)

The app reads `.env` from the project root.

Example:

```dotenv
LATITUDE=42.6826
LONGITUDE=23.3223
TIMEZONE=Europe/Sofia
CHECK_INTERVAL=60
SAMPLES_PER_DAY=1440
IMAGE_MAP=1,2,3,4,5,6,7,8,9,10,11
ORDERED_IMAGE_RANGES=1:-0.05:0.05,2:0.05:0.25,3:0.25:0.9,4:0.9:0.9,5:0.9:0.25,6:0.25:0.05,7:0.05:-0.05,8:-0.05:-0.2,9:-0.2:-0.6,10:-0.6:-0.25,11:-0.25:-0.05
GEO_UPDATE_DAYS=3
```

Notes:

- `ORDERED_IMAGE_RANGES` format is `image:min:max,image:min:max,...`
- If `ORDERED_IMAGE_RANGES` is empty, app falls back to `IMAGE_MAP`
- `GEO_UPDATE_DAYS=0` disables startup IP geolocation updates
- On startup, `.env` is validated and missing/invalid values are auto-repaired

## Run

Run directly:

```bash
source .venv/bin/activate
python main.py
```

## Preview / Tuning Tool

Generate value table and charts:

```bash
source .venv/bin/activate
python print_solar_curve.py
```

Outputs:

- `solar_curve_today.png`
- `solar_curve_today.html`

Use these to tune `IMAGE_MAP` or `ORDERED_IMAGE_RANGES`.

## Systemd User Service

Service file in this repo:

- `wallpaper-engine.service`

Copy to user systemd directory and enable:

```bash
mkdir -p ~/.config/systemd/user
cp wallpaper-engine.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now wallpaper-engine.service
```

Useful commands:

```bash
systemctl --user restart wallpaper-engine.service
systemctl --user status wallpaper-engine.service
journalctl --user -u wallpaper-engine.service -f
```
