"""Quarterly retune: re-pick the model's settings using every finished game we have.

Run: python -m sportsai.retune   (GitHub runs this on Jan 1, Apr 1, Jul 1 and Oct 1)
New settings are kept only if they predicted the last 90 days (or last year, early in a season)
at least as well as the old ones.
The result is written to the "settings" of data/backtest_summary.json, which predict.py uses.
"""
import datetime as dt, json, os, sys
from .backtest import load, tune, graded, mae
from .fetch_history import DATA, fbs_teams_from_games
from .predict import load_current, CURRENT
from .model import run


def all_games(sport):
    history = load(sport)
    current = load_current(sport)
    for g in current:
        g["home_fbs"] = g["away_fbs"] = 1
    if sport == "cfb":
        season = CURRENT[sport][0]
        fbs = {t for _, t in fbs_teams_from_games(current)}
        fbs |= {g[s + "_id"] for g in history if g["season"] == season - 1 for s in ("home", "away") if g[s + "_fbs"]}
        for g in current:
            g["home_fbs"], g["away_fbs"] = int(g["home_id"] in fbs), int(g["away_id"] in fbs)
    return sorted(history + current, key=lambda g: g["date"])


def recent_miss(sport, games, settings, since):
    out, _ = run(sport, games, settings)
    recent = graded(sport, [g for g in out if g["date"] >= since])
    return (mae(recent, "pred"), len(recent)) if recent else (None, 0)


def main(sports):
    path = os.path.join(DATA, "backtest_summary.json")
    summary = json.load(open(path))
    today = dt.date.today()
    since = (today - dt.timedelta(days=90)).isoformat()
    for sport in sports:
        games = all_games(sport)
        old = summary[sport]["settings"]
        new = {**old, **tune(sport, games, train=games)}
        old_miss, n = recent_miss(sport, games, old, since)
        window = since
        if n < 50:  # early in a season: judge on the last year instead of 90 days
            window = (today - dt.timedelta(days=365)).isoformat()
            old_miss, n = recent_miss(sport, games, old, window)
        new_miss, _ = recent_miss(sport, games, new, window)
        keep_new = n == 0 or new_miss <= old_miss
        note = dict(date=today.isoformat(), judged_since=window, games_used=len(games), recent_games=n,
                    recent_avg_miss_old=round(old_miss, 2) if old_miss else None,
                    recent_avg_miss_new=round(new_miss, 2) if new_miss else None,
                    adopted=keep_new, old_settings=old, new_settings=new)
        summary[sport].setdefault("retunes", []).append(note)
        if keep_new:
            summary[sport]["settings"] = new
        print(sport, "adopted" if keep_new else "kept old", json.dumps({k: note[k] for k in
              ("games_used", "recent_games", "recent_avg_miss_old", "recent_avg_miss_new")}))
    json.dump(summary, open(path, "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv[1:] or ["nfl", "nba", "cfb"])
