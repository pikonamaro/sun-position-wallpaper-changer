#!/usr/bin/env python3
"""Print today's normalized solar curve values (-1..1) for image-range tuning."""

from datetime import datetime
from importlib import import_module
from pathlib import Path
from zoneinfo import ZoneInfo

from astral import LocationInfo
from astral.sun import sun

from main import build_daily_curve, build_image_timeline, load_config


def sample_time_label(index, total_samples):
    """Convert sample index to HH:MM for a 24h day."""
    if total_samples <= 1:
        return "00:00"
    seconds = round((index / (total_samples - 1)) * 86400)
    if seconds >= 86400:
        seconds = 86399
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours:02d}:{minutes:02d}"


def build_times_for_day(today, total_samples, tz):
    """Build datetime points aligned to sample indices for one day."""
    times = []
    for i in range(total_samples):
        seconds = round((i / (total_samples - 1)) * 86400) if total_samples > 1 else 0
        if seconds >= 86400:
            seconds = 86399
        hour = seconds // 3600
        minute = (seconds % 3600) // 60
        second = seconds % 60
        times.append(datetime(today.year, today.month, today.day, hour, minute, second, tzinfo=tz))
    return times


def horizon_normalize(degrees):
    """Normalize degrees to -1..1 while keeping 0 at the astronomical horizon."""
    if not degrees:
        return []
    max_abs = max(abs(min(degrees)), abs(max(degrees)))
    if max_abs == 0:
        return [0.0] * len(degrees)
    return [d / max_abs for d in degrees]


def compute_sun_events(today, config, tz):
    """Return today's key solar events in local timezone."""
    loc = LocationInfo(
        latitude=config["latitude"],
        longitude=config["longitude"],
        timezone=config["timezone"],
    )
    return sun(loc.observer, date=today, tzinfo=tz)


def print_ascii_graph(values, width=72, height=20):
    """Render normalized -1..1 values as a simple ASCII graph."""
    if not values:
        print("No values to graph")
        return

    width = max(10, width)
    height = max(5, height)

    points = []
    for x in range(width):
        src_idx = round((x / (width - 1)) * (len(values) - 1))
        v = max(-1.0, min(1.0, values[src_idx]))
        y = round(((1.0 - v) / 2.0) * (height - 1))
        points.append((x, y, v))

    zero_y = round(((1.0 - 0.0) / 2.0) * (height - 1))
    canvas = [[" " for _ in range(width)] for _ in range(height)]

    for y in range(height):
        canvas[y][0] = "|"
    for x in range(width):
        canvas[zero_y][x] = "-"
    canvas[zero_y][0] = "+"

    for x, y, _ in points:
        canvas[y][x] = "*"

    print("ASCII graph (y: normalized -1..1, x: time 00:00 -> 23:59)")
    for row in canvas:
        print("".join(row))
    print(" " + "^" + " " * (width - 8) + "^")
    print(" " + "00:00" + " " * (width - 11) + "23:59")
    print()


def save_real_graph(curve, config, today, times, events, horizon_norm):
    """Save a PNG graph with hour labels to correlate time with normalized values."""
    try:
        mdates = import_module("matplotlib.dates")
        plt = import_module("matplotlib.pyplot")
    except ImportError:
        print("matplotlib is not installed; skipping PNG graph generation")
        print("Install with: pip install matplotlib")
        return None

    fig, ax = plt.subplots(figsize=(14, 6), tight_layout=True)
    ax.plot(times, curve["normalized"], color="#0d47a1", linewidth=2.2, label="min-max normalized")
    ax.plot(times, horizon_norm, color="#ef6c00", linewidth=1.8, linestyle="--", label="horizon-normalized")
    ax.axhline(0.0, color="#777777", linewidth=1.0, linestyle="--")
    ax.fill_between(times, curve["normalized"], 0.0, color="#64b5f6", alpha=0.2)

    for key, color in [
        ("dawn", "#6a1b9a"),
        ("sunrise", "#2e7d32"),
        ("noon", "#c62828"),
        ("sunset", "#2e7d32"),
        ("dusk", "#6a1b9a"),
    ]:
        ax.axvline(events[key], color=color, linewidth=1.0, linestyle=":", alpha=0.8)

    ax.set_title(f"Solar Curve - {today} ({config['timezone']})")
    ax.set_xlabel("Time of day")
    ax.set_ylabel("Normalized value")
    ax.set_ylim(-1.05, 1.05)
    ax.grid(True, which="both", linestyle=":", alpha=0.5)

    ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.tick_params(axis="x", rotation=45)
    ax.legend(loc="upper left")

    out_path = Path(__file__).parent / "solar_curve_today.png"
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def save_interactive_graph(curve, config, today, times, images, events, horizon_norm):
    """Save an interactive HTML graph with hover data and zoom."""
    try:
        go = import_module("plotly.graph_objects")
        subplots = import_module("plotly.subplots")
    except ImportError:
        print("plotly is not installed; skipping interactive HTML chart generation")
        print("Install with: pip install plotly")
        return None

    fig = subplots.make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Scatter(
            x=times,
            y=curve["normalized"],
            mode="lines",
            name="min-max normalized",
            line={"color": "#0d47a1", "width": 3},
            customdata=list(zip(curve["degrees"], images)),
            hovertemplate=(
                "Time: %{x|%H:%M:%S}<br>"
                "Normalized: %{y:.4f}<br>"
                "Degrees: %{customdata[0]:.2f}<br>"
                "Image: %{customdata[1]}<extra></extra>"
            ),
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=times,
            y=horizon_norm,
            mode="lines",
            name="horizon-normalized",
            line={"color": "#ef6c00", "width": 2, "dash": "dash"},
            hovertemplate="Time: %{x|%H:%M:%S}<br>Horizon norm: %{y:.4f}<extra></extra>",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=times,
            y=curve["degrees"],
            mode="lines",
            name="degrees",
            line={"color": "#00897b", "width": 2},
            hovertemplate="Time: %{x|%H:%M:%S}<br>Degrees: %{y:.2f}<extra></extra>",
        ),
        secondary_y=True,
    )
    fig.add_hline(y=0.0, line_dash="dash", line_color="#777777")
    fig.add_hline(y=0.0, line_dash="dot", line_color="#00897b", secondary_y=True)

    for key, label, color in [
        ("dawn", "Dawn", "#6a1b9a"),
        ("sunrise", "Sunrise", "#2e7d32"),
        ("noon", "Culmination", "#c62828"),
        ("sunset", "Sunset", "#2e7d32"),
        ("dusk", "Dusk", "#6a1b9a"),
    ]:
        fig.add_vline(x=events[key], line_dash="dot", line_color=color, opacity=0.8)
        fig.add_annotation(
            x=events[key],
            y=1.03,
            yref="paper",
            text=label,
            showarrow=False,
            textangle=-90,
            font={"size": 10, "color": color},
        )

    fig.update_layout(
        title=f"Solar Curve (interactive) - {today} ({config['timezone']})",
        xaxis_title="Time of day",
        template="plotly_white",
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="Normalized value", range=[-1.05, 1.05], secondary_y=False)
    fig.update_yaxes(title_text="Solar elevation (degrees)", secondary_y=True)
    fig.update_xaxes(dtick=3600000, tickformat="%H:%M", rangeslider={"visible": True})

    out_path = Path(__file__).parent / "solar_curve_today.html"
    fig.write_html(out_path, include_plotlyjs="cdn", full_html=True)
    return out_path


def main():
    config = load_config()
    tz = ZoneInfo(config["timezone"])
    today = datetime.now(tz=tz).date()

    curve = build_daily_curve(
        today,
        tz,
        config["latitude"],
        config["longitude"],
        config["samples_per_day"],
    )

    print(f"Date: {today}  TZ: {config['timezone']}")
    print(f"Samples: {config['samples_per_day']}")
    print(f"Degrees range: {min(curve['degrees']):.2f} .. {max(curve['degrees']):.2f}")
    print()

    times = build_times_for_day(today, len(curve["normalized"]), tz)
    events = compute_sun_events(today, config, tz)
    horizon_norm = horizon_normalize(curve["degrees"])
    images = build_image_timeline(curve, config)

    print(f"Dawn:\t\t{events['dawn']:%H:%M:%S}")
    print(f"Sunrise:\t{events['sunrise']:%H:%M:%S}")
    print(f"Culmination:\t{events['noon']:%H:%M:%S}")
    print(f"Sunset:\t\t{events['sunset']:%H:%M:%S}")
    print(f"Dusk:\t\t{events['dusk']:%H:%M:%S}")
    print()

    out_graph = save_real_graph(curve, config, today, times, events, horizon_norm)
    if out_graph is not None:
        print(f"Saved graph: {out_graph}")
        print()

    out_interactive = save_interactive_graph(
        curve, config, today, times, images, events, horizon_norm
    )
    if out_interactive is not None:
        print(f"Saved interactive chart: {out_interactive}")
        print()
    
    print("index\ttime\tnormalized\timage")

    for i, value in enumerate(curve["normalized"]):
        time_label = sample_time_label(i, config["samples_per_day"])
        image_num = images[i]
        print(f"{i}\t{time_label}\t{value:.6f}\t{image_num}")
    print_ascii_graph(curve["normalized"])


if __name__ == "__main__":
    main()
