"""Render the link preview image (1200x630) shown when the site is shared.

Uses the live record when there is one, otherwise the held-out backtest result, and
today's closest game if there are games. The Docker build runs this, so each daily
deploy gets a fresh image.
"""
import argparse
import csv
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
FONT = HERE / "assets" / "Figtree.ttf"
WIDTH, HEIGHT = 1200, 630
INK, MUTED, LINE, BRAND = "#222222", "#6a6a6a", "#dddddd", "#e8590c"
TEAM_COLORS = {
    "ATL": "#c92b37", "BOS": "#15803d", "BKN": "#374151", "CHA": "#087e8b", "CHI": "#c92b37",
    "CLE": "#861b3b", "DAL": "#1265b6", "DEN": "#a77b08", "DET": "#ce2638", "GSW": "#2463ce",
    "HOU": "#cc263c", "IND": "#a57800", "LAC": "#245ba9", "LAL": "#753bbd", "MEM": "#526daa",
    "MIA": "#b82439", "MIL": "#23764f", "MIN": "#236480", "NOP": "#967b45", "NYK": "#cf631e",
    "OKC": "#147dc2", "ORL": "#2676c5", "PHI": "#2365bb", "PHX": "#a34c1d", "POR": "#c62a37",
    "SAC": "#7543aa", "SAS": "#4b5563", "TOR": "#cc293b", "UTA": "#6243a4", "WAS": "#b12c40",
}


def font(size, weight):
    face = ImageFont.truetype(str(FONT), size)
    face.set_variation_by_axes([weight])
    return face


def headline_stat(live_dir, backtest_dir):
    """(big text, caption) from the live record, else the held-out backtest."""
    try:
        live = json.loads((live_dir / "summary.json").read_text())["live"]
        if live.get("games"):
            wins = round(live["accuracy"] * live["games"])
            return f"{wins}–{live['games'] - wins}", f"live record, {live['accuracy']:.1%} correct"
    except (OSError, ValueError, KeyError):
        pass
    try:
        report = json.loads((backtest_dir / "report.json").read_text())
        test = report["results"][report["test_season"]]["elo"]["accuracy"]
        return f"{test:.1%}", f"correct on the held-out {report['test_season']} season"
    except (OSError, ValueError, KeyError):
        return "Elo", "a simple, transparent rating model"


def closest_upcoming(live_dir):
    """Today's closest unplayed game as (away, home, home win chance), or None."""
    try:
        summary = json.loads((live_dir / "summary.json").read_text())
        with (live_dir / f"predictions_{summary['season']}.csv").open(newline="") as file:
            pending = [r for r in csv.DictReader(file) if r["actual_home_win"] == ""]
    except (OSError, ValueError, KeyError):
        return None
    if not pending:
        return None
    row = min(pending, key=lambda r: abs(float(r["home_win_probability"]) - 0.5))
    return row["away_team"], row["home_team"], float(row["home_win_probability"])


def render(live_dir, backtest_dir, output):
    image = Image.new("RGB", (WIDTH, HEIGHT), "#ffffff")
    draw = ImageDraw.Draw(image)
    left = 80

    # Wordmark: the site's basketball mark and name.
    cx, cy, r = left + 22, 92, 22
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=BRAND, width=4)
    draw.line((cx - r, cy, cx + r, cy), fill=BRAND, width=4)
    draw.line((cx, cy - r, cx, cy + r), fill=BRAND, width=4)
    draw.arc((cx - r - 14, cy - r, cx + r - 26, cy + r), -60, 60, fill=BRAND, width=4)
    draw.arc((cx - r + 26, cy - r, cx + r + 14, cy + r), 120, 240, fill=BRAND, width=4)
    draw.text((left + 60, cy), "Forecast Lab", font=font(36, 800), fill=INK, anchor="lm")

    draw.text((left, 170), "Daily NBA win probabilities,", font=font(60, 800), fill=INK)
    draw.text((left, 240), "saved before tip-off.", font=font(60, 800), fill=INK)

    big, caption = headline_stat(live_dir, backtest_dir)
    draw.text((left, 470), big, font=font(112, 800), fill=INK, anchor="ls")
    draw.text((left, 520), caption, font=font(30, 500), fill=MUTED, anchor="ls")

    game = closest_upcoming(live_dir)
    if game:
        away, home, home_chance = game
        x0, x1, y = 660, WIDTH - 80, 400
        draw.rounded_rectangle((x0 - 32, y - 70, x1 + 32, y + 120), radius=28, outline=LINE, width=2)
        draw.text((x0, y - 30), "Closest game today", font=font(26, 600), fill=MUTED, anchor="ls")
        split = x0 + round((x1 - x0) * (1 - home_chance))
        draw.rounded_rectangle((x0, y, split - 4, y + 16), radius=8, fill=TEAM_COLORS.get(away, MUTED))
        draw.rounded_rectangle((split + 4, y, x1, y + 16), radius=8, fill=TEAM_COLORS.get(home, MUTED))
        draw.text((x0, y + 76), f"{away} {1 - home_chance:.0%}", font=font(40, 800), fill=INK, anchor="ls")
        draw.text((x1, y + 76), f"{home_chance:.0%} {home}", font=font(40, 800), fill=INK, anchor="rs")

    draw.line((0, HEIGHT - 8, WIDTH, HEIGHT - 8), fill=BRAND, width=16)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, optimize=True)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-dir", type=Path, default=HERE / "live")
    parser.add_argument("--backtest-dir", type=Path, default=HERE / "data" / "backtest")
    parser.add_argument("--output", type=Path, default=HERE / "live" / "og.png")
    args = parser.parse_args(argv)
    print(f"Saved {render(args.live_dir, args.backtest_dir, args.output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
