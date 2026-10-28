"""Can any simple betting rule make 10%+ profit over time? An honest test on past seasons.

Every bet is graded against the closing spread or total at -110 (win +$0.909, loss -$1, push $0).
Breaking even needs 52.4% wins; 10% profit needs about 57.6%.

The rules are chosen on 2023-2024 (the "train" seasons) and then judged only on 2025 (the "test"
season), which played no part in choosing them. Our model's settings were also tuned before 2025.
Run: python -m research.strategies   (plain Python, about a minute)
"""
import collections, datetime as dt, json, math, os, sys

from sportsai import backtest, model
from sportsai.fetch_history import DATA

WIN, TRAIN, TEST = 100 / 110, (2023, 2024), 2025
TARGET = 0.10


def et_day(iso):
    t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00")) - dt.timedelta(hours=5)
    return t.date().isoformat()


def games(sport):
    settings = json.load(open(os.path.join(DATA, "backtest_summary.json")))[sport]["settings"]
    out, _ = model.run(sport, backtest.load(sport), settings)
    rows = []
    for g in backtest.graded(sport, out):
        if g["season"] not in TRAIN + (TEST,) or g["spread"] is None:
            continue
        total = float(g["total"]) if g.get("total") not in (None, "") else None
        rows.append(dict(sport=sport, season=g["season"], day=et_day(g["date"]), spread=g["spread"],
                         margin=g["home_score"] - g["away_score"], pts=g["home_score"] + g["away_score"],
                         total=total, edge=g["pred"] + g["spread"], neutral=g["neutral"]))
    return rows


def ats(g, side):
    """Result of a spread bet on 'home' or 'away': 1 win, 0 push, -1 loss."""
    d = g["margin"] + g["spread"]
    d = d if side == "home" else -d
    return (d > 0) - (d < 0)


def ou(g, side):
    d = g["pts"] - g["total"]
    d = d if side == "over" else -d
    return (d > 0) - (d < 0)


def stats(results):
    n = len(results)
    if not n:
        return dict(n=0)
    w, l = results.count(1), results.count(-1)
    roi = (w * WIN - l) / n
    # rough 95% range for the profit rate (normal approximation)
    sd = math.sqrt(max(sum((WIN if r == 1 else -1 if r == -1 else 0) ** 2 for r in results) / n - roi ** 2, 0) / n)
    return dict(n=n, won=w, lost=l, win_pct=round(100 * w / max(w + l, 1), 1), roi=round(100 * roi, 1),
                roi_low=round(100 * (roi - 1.96 * sd), 1), roi_high=round(100 * (roi + 1.96 * sd), 1))


def rules():
    """name -> function(game) returning a list of bet results (empty = no bet)."""
    R = {}
    model_side = lambda g: "home" if g["edge"] > 0 else "away"
    for t in (0, 1, 2, 3, 4, 5, 6, 7, 8, 10):
        R[f"model side, disagrees by {t}+"] = lambda g, t=t: [ats(g, model_side(g))] if abs(g["edge"]) >= t and g["edge"] else []
        R[f"against model, disagrees by {t}+"] = lambda g, t=t: [ats(g, "away" if model_side(g) == "home" else "home")] if abs(g["edge"]) >= t and g["edge"] else []
    R["every home team"] = lambda g: [ats(g, "home")]
    R["every away team"] = lambda g: [ats(g, "away")]
    dog = lambda g: "home" if g["spread"] > 0 else "away"
    fav = lambda g: "away" if g["spread"] > 0 else "home"
    R["every underdog"] = lambda g: [ats(g, dog(g))] if g["spread"] else []
    R["every favorite"] = lambda g: [ats(g, fav(g))] if g["spread"] else []
    R["home underdogs"] = lambda g: [ats(g, "home")] if g["spread"] > 0 and not g["neutral"] else []
    R["road favorites"] = lambda g: [ats(g, "away")] if g["spread"] > 0 and not g["neutral"] else []
    for big in (3, 7, 10, 14):
        R[f"underdogs of {big}+"] = lambda g, big=big: [ats(g, dog(g))] if abs(g["spread"]) >= big else []
        R[f"model side on underdogs of {big}+"] = lambda g, big=big: [ats(g, dog(g))] if abs(g["spread"]) >= big and model_side(g) == dog(g) and abs(g["edge"]) >= 2 else []
    R["every under"] = lambda g: [ou(g, "under")] if g["total"] else []
    R["every over"] = lambda g: [ou(g, "over")] if g["total"] else []
    return R


def by_season(rows, rule):
    out = collections.defaultdict(list)
    for g in rows:
        out[g["season"]] += rule(g)
    return out


def daily_top3(rows, min_edge):
    """The three games each day where the model disagrees most (any sport), betting the model's side."""
    days = collections.defaultdict(list)
    for g in rows:
        if abs(g["edge"]) >= min_edge:
            days[(g["season"], g["day"])].append(g)
    out = collections.defaultdict(list)
    for (season, _), gs in days.items():
        for g in sorted(gs, key=lambda g: -abs(g["edge"]))[:3]:
            out[season].append(ats(g, "home" if g["edge"] > 0 else "away"))
    return out, len(days)


def main():
    rows = [g for sp in ("nfl", "nba", "cfb") for g in games(sp)]
    report = []
    scopes = {"all sports": rows, **{sp.upper(): [g for g in rows if g["sport"] == sp] for sp in ("nfl", "nba", "cfb")}}
    for scope, rs in scopes.items():
        for name, rule in rules().items():
            s = by_season(rs, rule)
            train = stats(s[TRAIN[0]] + s[TRAIN[1]])
            if train["n"] < 100:
                continue
            report.append(dict(rule=f"{scope}: {name}", train=train, test=stats(s[TEST])))
    for t in (0, 2, 4, 6):
        s, _ = daily_top3(rows, t)
        report.append(dict(rule=f"daily top 3 disagreements (any sport, {t}+ pts)",
                           train=stats(s[TRAIN[0]] + s[TRAIN[1]]), test=stats(s[TEST])))
    report.sort(key=lambda r: -r["train"]["roi"])
    passed_train = [r for r in report if r["train"]["roi"] >= 100 * TARGET]
    passed_both = [r for r in passed_train if r["test"].get("roi", -99) >= 100 * TARGET and r["test"]["n"] >= 100]
    json.dump(dict(target_roi=TARGET, rules_tested=len(report), passed_train=passed_train, passed_train_and_test=passed_both,
                   all=report), open(os.path.join(os.path.dirname(__file__), "results.json"), "w"), indent=1)
    print(f"{len(report)} rules tested. Hit 10%+ on 2023-24: {len(passed_train)}. Also hit 10%+ on 2025 (100+ bets): {len(passed_both)}")
    for r in report[:15]:
        print(f'{r["rule"]:<60} train {r["train"]["roi"]:>6}% ({r["train"]["n"]})  test {r["test"].get("roi")}% ({r["test"]["n"]}, {r["test"].get("roi_low")} to {r["test"].get("roi_high")})')


if __name__ == "__main__":
    main()
