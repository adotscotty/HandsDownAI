"""Tune the model on 2024 and grade it on 2025 (last season), compared with the betting spread.

Run: python -m sportsai.backtest [nfl nba cfb]
Writes data/backtest_<sport>.csv (every game) and data/backtest_summary.json.
"""
import csv, itertools, json, math, os, sys
from .model import run, win_prob, DEFAULTS
from .fetch_history import TEST_SEASON, DATA

GRID = {
    "nfl": dict(k=[0.04, 0.06, 0.08, 0.10, 0.13], carry=[0.4, 0.5, 0.65, 0.8], hfa=[1.0, 1.5, 2.0, 2.5],
                beta=[0, 1.5, 3, 5], early=[0.5, 1, 2, 4], rest=[0, 0.15, 0.3, 0.5], qbq=[0, 1, 2, 3, 4]),
    "nba": dict(k=[0.03, 0.045, 0.06, 0.08], carry=[0.5, 0.65, 0.8], hfa=[2.0, 2.5, 3.0], beta=[0, 0.08, 0.12, 0.16, 0.22]),
    "cfb": dict(k=[0.08, 0.11, 0.14, 0.18], carry=[0.55, 0.7, 0.85], hfa=[2.0, 2.75, 3.5], beta=[0, 4, 7]),
}


def load(sport):
    with open(os.path.join(DATA, f"games_{sport}.csv")) as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in ("season", "home_score", "away_score", "neutral", "season_type", "home_fbs", "away_fbs"):
            r[k] = int(r[k]) if r.get(k) not in (None, "") else 0
        r["spread"] = float(r["spread"]) if r.get("spread") not in (None, "") else None
    return rows


def graded(sport, rows):
    """Games we score: both main-division teams (FBS vs FBS for college)."""
    return [r for r in rows if r.get("home_fbs", 1) and r.get("away_fbs", 1)]


def mae(rows, key):
    return sum(abs(r["home_score"] - r["away_score"] - r[key]) for r in rows) / len(rows)


def tune(sport, games, train=None):
    """Pick settings that predicted the training games best (after the first few weeks).
    By default the training games are the 2024 season."""
    if train is None:
        train = [g for g in games if g["season"] < TEST_SEASON]
    seasons = sorted({g["season"] for g in train})
    if len(seasons) > 1:  # the first season only warms up the ratings
        cutoff = min(g["date"] for g in train if g["season"] == seasons[1])
    else:  # skip the cold start, when every team was rated 0
        cutoff = train[len(train) // 4]["date"]

    def score(params):
        out, _ = run(sport, train, params)
        return mae(graded(sport, [g for g in out if g["date"] >= cutoff]), "pred")

    keys = list(GRID[sport])
    if math.prod(len(v) for v in GRID[sport].values()) <= 1000:  # small grid: try everything
        best = min(((score(dict(zip(keys, c))), dict(zip(keys, c)))
                    for c in itertools.product(*GRID[sport].values())), key=lambda x: x[0])
    else:  # big grid: improve one setting at a time until nothing changes
        params = {k: v[len(v) // 2] for k, v in GRID[sport].items()}
        best = (score(params), params)
        for _ in range(4):
            improved = False
            for k in keys:
                for v in GRID[sport][k]:
                    trial = {**best[1], k: v}
                    sc = score(trial)
                    if sc < best[0] - 1e-9:
                        best, improved = (sc, trial), True
            if not improved:
                break
    # Win probability: pick the outcome spread that best matched who actually won in 2024.
    # (Fitting it to wins/losses, not raw margins, keeps blowouts from making us too timid.)
    out, _ = run(sport, train, best[1])
    fit = [g for g in graded(sport, out) if g["date"] >= cutoff]

    def log_loss(sigma):
        total = 0.0
        for g in fit:
            p = min(max(win_prob(g["pred"], sigma), 1e-6), 1 - 1e-6)
            total -= math.log(p if g["home_score"] > g["away_score"] else 1 - p)
        return total / len(fit)
    # Search near the typical miss size so a small sample (like one NFL season) can't push it too far.
    rms = math.sqrt(sum((g["home_score"] - g["away_score"] - g["pred"]) ** 2 for g in fit) / len(fit))
    choices = [round(rms * f, 2) for f in (0.8, 0.85, 0.9, 0.95, 1.0)]
    best[1]["sigma"] = min(choices, key=log_loss)
    return best[1]


def summarize(sport, test):
    with_line = [g for g in test if g["spread"] is not None]
    for g in with_line:
        g["vegas"] = -g["spread"]
    s = dict(games=len(test), games_with_spread=len(with_line))
    s["model_avg_miss"] = round(mae(test, "pred"), 2)
    s["model_no_injury_avg_miss"] = round(mae(test, "pred_no_injury"), 2)
    if with_line:
        s["model_avg_miss_same_games"] = round(mae(with_line, "pred"), 2)
        s["vegas_avg_miss_same_games"] = round(mae(with_line, "vegas"), 2)
    s["picked_winner_pct"] = round(100 * sum(
        (g["pred"] > 0) == (g["home_score"] > g["away_score"]) for g in test if g["home_score"] != g["away_score"]
    ) / len(test), 1)
    if with_line:
        s["vegas_picked_winner_pct"] = round(100 * sum(
            (g["vegas"] > 0) == (g["home_score"] > g["away_score"]) for g in with_line if g["vegas"] != 0
        ) / len(with_line), 1)
    # Win-probability calibration: Brier score (lower is better; always saying 50% = 0.25)
    s["brier"] = round(sum((g["win_prob"] - (g["home_score"] > g["away_score"])) ** 2 for g in test) / len(test), 4)
    # Against the spread: bet the side the model likes when it disagrees with the line by >= edge
    ats = {}
    for edge in (0, 2, 4, 6):
        w = l = p = 0
        for g in with_line:
            diff = g["pred"] - g["vegas"]
            if abs(diff) < edge or diff == 0:
                continue
            cover = (g["home_score"] - g["away_score"]) - g["vegas"]
            if cover == 0:
                p += 1
            elif (cover > 0) == (diff > 0):
                w += 1
            else:
                l += 1
        ats[f"edge_{edge}+"] = dict(wins=w, losses=l, pushes=p,
                                     win_pct=round(100 * w / (w + l), 1) if w + l else None)
    s["against_spread"] = ats
    return s


def main(sports):
    summary_path = os.path.join(DATA, "backtest_summary.json")
    allsum = json.load(open(summary_path)) if os.path.exists(summary_path) else {}
    for sport in sports:
        games = load(sport)
        params = tune(sport, games)
        out, model = run(sport, games, params)
        test = graded(sport, [g for g in out if g["season"] == TEST_SEASON])
        s = summarize(sport, test)
        s["settings"] = {**DEFAULTS[sport], **params}
        allsum[sport] = s
        print(sport, json.dumps(s, indent=1))
        cols = ["date", "season", "home", "away", "home_score", "away_score", "spread", "pred",
                "pred_no_injury", "win_prob", "home_missing", "away_missing", "home_qb_name", "away_qb_name"]
        with open(os.path.join(DATA, f"backtest_{sport}.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, cols, extrasaction="ignore")
            w.writeheader()
            for g in test:
                w.writerow({k: (round(g[k], 2) if isinstance(g.get(k), float) else g.get(k)) for k in cols})
    json.dump(allsum, open(summary_path, "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv[1:] or ["nfl", "nba", "cfb"])
