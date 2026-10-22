"""Turn the model's output into the small data files the website reads (site/data/*.json)."""
import csv, datetime as dt, json, os, shutil
from .fetch_history import DATA

SITE = os.path.join(os.path.dirname(__file__), "..", "site")
NAMES = {"nfl": "NFL", "nba": "NBA", "cfb": "College Football"}


def record(rows):
    """Season-to-date grades for a list of finished games."""
    rows = [r for r in rows if r["home_score"] != r["away_score"] or r["spread"] is not None]
    if not rows:
        return None
    n = len(rows)
    margin = lambda r: r["home_score"] - r["away_score"]
    out = dict(games=n,
               winner_pct=round(100 * sum((r["pred"] > 0) == (margin(r) > 0) for r in rows) / n, 1),
               avg_miss=round(sum(abs(margin(r) - r["pred"]) for r in rows) / n, 1))
    lined = [r for r in rows if r["spread"] is not None]
    if lined:
        out["spread_avg_miss"] = round(sum(abs(margin(r) + r["spread"]) for r in lined) / len(lined), 1)
        w = l = p = 0
        for r in lined:
            diff, cover = r["pred"] + r["spread"], margin(r) + r["spread"]
            if diff == 0:
                continue
            if cover == 0:
                p += 1
            elif (cover > 0) == (diff > 0):
                w += 1
            else:
                l += 1
        out["ats"] = dict(wins=w, losses=l, pushes=p, pct=round(100 * w / (w + l), 1) if w + l else None)
    return out


def load_season(sport):
    path = os.path.join(DATA, f"season_{sport}.csv")
    rows = []
    if os.path.exists(path):
        with open(path) as f:
            for r in csv.DictReader(f):
                if r.get("home_fbs") == "0" or r.get("away_fbs") == "0":
                    continue  # college: only grade games between two FBS teams
                rows.append(dict(
                    date=r["date"], home=r["home"], away=r["away"],
                    home_name=r.get("home_name"), away_name=r.get("away_name"),
                    home_score=int(r["home_score"]), away_score=int(r["away_score"]),
                    spread=float(r["spread"]) if r["spread"] else None,
                    pred=float(r["pred"]), win_prob=float(r["win_prob"])))
    return rows


def eastern_now():
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("America/New_York"))
    except Exception:  # no time-zone data installed: Eastern standard time is close enough
        return dt.datetime.now(dt.timezone(dt.timedelta(hours=-5)))


def eastern_date(iso):
    when = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return when.astimezone(eastern_now().tzinfo).date()


def periods(rows):
    """Record for yesterday, this week (since Monday) and this month, by US Eastern date."""
    today = eastern_now().date()
    spans = [("Yesterday", today - dt.timedelta(days=1), today - dt.timedelta(days=1)),
             ("This week", today - dt.timedelta(days=today.weekday()), today),
             ("This month", today.replace(day=1), today)]
    out = []
    for label, start, end in spans:
        picked = [r for r in rows if start <= eastern_date(r["date"]) <= end]
        rec = record(picked) or dict(games=0)
        if picked:
            right = sum((r["pred"] > 0) == (r["home_score"] - r["away_score"] > 0) for r in picked)
            rec["winners"] = [right, len(picked) - right]
        out.append(dict(label=label, start=start.isoformat(), end=end.isoformat(), **rec))
    return out


def main():
    os.makedirs(os.path.join(SITE, "data"), exist_ok=True)
    shutil.copy(os.path.join(DATA, "predictions.json"), os.path.join(SITE, "data", "predictions.json"))
    backtest = json.load(open(os.path.join(DATA, "backtest_summary.json")))
    track = {}
    for sport in ("nfl", "nba", "cfb"):
        rows = load_season(sport)
        b = backtest.get(sport, {})
        track[sport] = dict(
            name=NAMES[sport],
            this_season=record(rows),
            periods=periods(rows),
            last_season=dict(games=b.get("games"), winner_pct=b.get("picked_winner_pct"),
                             avg_miss=b.get("model_avg_miss"), spread_avg_miss=b.get("vegas_avg_miss_same_games"),
                             spread_winner_pct=b.get("vegas_picked_winner_pct"),
                             ats=b.get("against_spread", {}).get("edge_0+")),
            recent=[{k: r[k] for k in ("date", "home", "away", "home_score", "away_score", "spread", "pred")}
                    for r in sorted(rows, key=lambda r: r["date"], reverse=True)[:40]],
        )
    json.dump(track, open(os.path.join(SITE, "data", "track_record.json"), "w"))
    print("site data written")


if __name__ == "__main__":
    main()
