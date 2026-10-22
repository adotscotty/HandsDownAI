"""Make predictions for upcoming games using current ratings, ESPN's injury report and ESPN's odds.

Run: python -m sportsai.predict
Writes data/predictions.json (upcoming games) and data/season_<sport>.csv (this season so far,
each game predicted using only earlier games, for the track record).
Designed to run every 15 minutes: past games come from the cache, only today/upcoming are refetched.
"""
import csv, datetime as dt, json, os, sys
from .espn import get_json, get_many, scoreboard_url, summary_url
from .fetch_history import DATA, days, main_teams, add_lineups, add_closing_spreads, fbs_teams_from_games
from .backtest import load
from .model import run, RatingModel, win_prob

CURRENT = {"nfl": (2026, "2026-09-01"), "nba": (2026, "2026-10-01"), "cfb": (2026, "2026-08-22")}
LOOKAHEAD = {"nfl": 7, "nba": 2, "cfb": 7}
# How likely a listed player is to miss the game, by injury-report status
STATUS_WEIGHT = {"out": 1.0, "injured reserve": 1.0, "suspension": 1.0, "doubtful": 0.75,
                 "questionable": 0.3, "day-to-day": 0.3, "probable": 0.05}


def parse_event(sport, ev, known):
    comp = ev["competitions"][0]
    side = {c["homeAway"]: c for c in comp["competitors"]}
    h, a = side["home"], side["away"]
    ids = {h["team"]["id"], a["team"]["id"]}
    if sport != "cfb" and not ids <= known:
        return None
    if ev.get("season", {}).get("type") not in (2, 3):
        return None
    odds = (comp.get("odds") or [{}])[0]
    ps = odds.get("pointSpread") or {}

    def price(side):  # American odds for betting this side's spread (default -110)
        try:
            return int(str(ps[side]["close"]["odds"]).replace("+", ""))
        except (KeyError, TypeError, ValueError):
            return -110
    return dict(
        sport=sport, season=CURRENT[sport][0], event_id=ev["id"], date=ev["date"], name=ev.get("name"),
        season_type=ev["season"]["type"],
        neutral=int(comp.get("neutralSite", False)), completed=comp["status"]["type"]["completed"],
        status=comp["status"]["type"].get("shortDetail"), state=comp["status"]["type"].get("state"),
        home_id=h["team"]["id"], home=h["team"]["abbreviation"], home_name=h["team"].get("displayName"),
        home_logo=h["team"].get("logo"), home_score=int(h.get("score") or 0),
        away_id=a["team"]["id"], away=a["team"]["abbreviation"], away_name=a["team"].get("displayName"),
        away_logo=a["team"].get("logo"), away_score=int(a.get("score") or 0),
        spread=odds.get("spread"), total=odds.get("overUnder"), odds_detail=odds.get("details"),
        book=(odds.get("provider") or {}).get("name"),
        home_spread_odds=price("home"), away_spread_odds=price("away"),
    )


CURRENT_COLS = ["sport", "season", "event_id", "date", "name", "neutral", "completed", "home_id", "home",
                "home_name", "home_score", "away_id", "away", "away_name", "away_score", "spread", "total",
                "book", "home_players", "away_players", "home_qb", "home_qb_name", "away_qb", "away_qb_name",
                "home_qb_pts", "home_qb_db", "away_qb_pts", "away_qb_db", "season_type"] + [
                f"{side}_{k}" for side in ("home", "away") for k in ("fga", "fgm", "tpa", "tpm", "fta", "ftm", "oreb", "tov")]


def load_current(sport):
    path = os.path.join(DATA, f"current_{sport}.csv")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in ("season", "home_score", "away_score", "neutral"):
            r[k] = int(r[k] or 0)
        r["spread"] = float(r["spread"]) if r.get("spread") else None
        r["season_type"] = int(r.get("season_type") or 2)
        r["completed"], r["_stored"] = True, True
    return rows


def save_current(sport, done):
    with open(os.path.join(DATA, f"current_{sport}.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, CURRENT_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(done)


def injury_list(summary, team_id):
    out = []
    for team in summary.get("injuries", []):
        if team["team"]["id"] != team_id:
            continue
        for inj in team.get("injuries", []):
            status = (inj.get("status") or "").lower()
            ath = inj.get("athlete", {})
            out.append(dict(id=ath.get("id"), name=ath.get("displayName"),
                            pos=(ath.get("position") or {}).get("abbreviation"), status=inj.get("status"),
                            weight=STATUS_WEIGHT.get(status, 0.0)))
    return out


def blend(model_margin, spread, w):
    """Main prediction: mostly the betting line, tilted toward our model by weight w."""
    if spread is None:
        return model_margin
    return w * model_margin + (1 - w) * -spread


def predict_sport(sport, settings, blend_w=0.0):
    known = main_teams(sport)
    season, start = CURRENT[sport]
    today = dt.datetime.now(dt.timezone.utc).date()
    # 1) this season's games. Finished games are stored in data/current_<sport>.csv, so each
    #    run only re-reads the last few days plus the days ahead.
    stored = load_current(sport)
    last = max((g["date"][:10] for g in stored), default=start)
    first_day = max(start, (dt.date.fromisoformat(last) - dt.timedelta(days=3)).isoformat())
    games = {g["event_id"]: g for g in stored}
    for d in days(first_day, (today + dt.timedelta(days=LOOKAHEAD[sport])).isoformat()):
        board = get_json(scoreboard_url(sport, d), cache=False)
        for ev in board.get("events", []):
            g = parse_event(sport, ev, known)
            if g and not (g["event_id"] in games and games[g["event_id"]].get("completed")):
                games[g["event_id"]] = g
    games = sorted(games.values(), key=lambda g: g["date"])
    history = load(sport)
    if sport == "cfb":  # FBS = FBS last season, or already 5+ games in ESPN's FBS list this season
        fbs = {t for _, t in fbs_teams_from_games(games)}
        fbs |= {g[s + "_id"] for g in history if g["season"] == season - 1 for s in ("home", "away") if g[s + "_fbs"]}
    for g in games:
        g["home_fbs"] = int(sport != "cfb" or g["home_id"] in fbs)
        g["away_fbs"] = int(sport != "cfb" or g["away_id"] in fbs)
    done = [g for g in games if g["completed"]]
    upcoming = [g for g in games if not g["completed"] and g.get("state", "pre") == "pre"]  # skip live games
    new_done = [g for g in done if not g.get("_stored")]
    add_lineups(sport, new_done)
    add_closing_spreads(sport, new_done, all_seasons=True)
    save_current(sport, done)

    # 2) walk through history + this season so ratings are current
    out, model = run(sport, history + done, settings)
    this_season = [g for g in out if g["season"] == season]

    # 3) upcoming games: injury report + current odds
    sums = get_many([summary_url(sport, g["event_id"]) for g in upcoming], cache=False)
    preds = []
    for g, s in zip(upcoming, sums):
        side_info = {}
        for side in ("home", "away"):
            team = g[side + "_id"]
            injuries = injury_list(s or {}, team)
            weights = {i["id"]: i["weight"] for i in injuries}
            if sport == "nba":
                regs = model.regulars(team)
                missing = model.missing_value(team, weights)
                key = [dict(i, value=round(regs[i["id"]], 1)) for i in injuries if i["id"] in regs and i["weight"]]
            else:
                qb = model.usual_qb(team)
                missing = weights.get(qb, 0.0) if qb else 0.0
                key = [i for i in injuries if i["id"] == qb and i["weight"]]
                qb_drop = 0.0
                if missing:  # compare the usual QB with his most likely replacement
                    sub = model.backup_qb(team)
                    sub_value = model.qb_value(sub) if sub else model.p["qb_repl"]
                    qb_drop = missing * (model.qb_value(qb) - sub_value)
            side_info[side] = dict(weights=weights, qb_drop=qb_drop if sport != "nba" else 0.0, missing=missing, key_injuries=key,
                                   all_injuries=[i for i in injuries if i["weight"] >= 0.75])
        when = dt.datetime.fromisoformat(g["date"].replace("Z", "+00:00"))
        rest = model.rest_days(g["home_id"], when) - model.rest_days(g["away_id"], when)
        hi, ai = side_info["home"], side_info["away"]
        pf, lud, late = 1.0, 0.0, (0, 0, 0, 0)
        if sport == "nba":  # who is expected to play, game pace, late-season tanking / top seeds
            h, a = g["home_id"], g["away_id"]
            hd, _ = model.lineup_delta(h, model.expected_players(h, hi["weights"]))
            ad, _ = model.lineup_delta(a, model.expected_players(a, ai["weights"]))
            lud = hd - ad
            pf = model.pace_factor(h, a)
            late = model.late_flags(h, when, g.get("season_type")) + model.late_flags(a, when, g.get("season_type"))
        m, wp = model.predict(g["home_id"], g["away_id"], g["neutral"], g["home_fbs"], g["away_fbs"],
                              hi["missing"], ai["missing"], rest, hi["qb_drop"], ai["qb_drop"], pf, lud, late)
        injury_pts = (-model.p["beta"] * (hi["missing"] - ai["missing"])
                      - model.p["qbq"] * (hi["qb_drop"] - ai["qb_drop"]))
        main = blend(m, g["spread"], blend_w)
        sigma = model.p["sigma"]
        preds.append(dict(
            {k: g[k] for k in ("sport", "event_id", "date", "name", "status", "neutral", "home", "home_name",
                               "home_logo", "away", "away_name", "away_logo", "spread", "total",
                               "odds_detail", "book", "home_spread_odds", "away_spread_odds")},
            predicted_home_margin=round(main, 1), home_win_prob=round(win_prob(main, sigma), 3),
            model_home_margin=round(m, 1), model_home_win_prob=round(wp, 3),
            home_cover_prob=round(win_prob(main + g["spread"], sigma), 3) if g["spread"] is not None else None,
            injury_adjustment=round(injury_pts, 1),
            rest_adjustment=round(model.p["rest"] * rest, 1),
            edge_vs_spread=round(m + g["spread"], 1) if g["spread"] is not None else None,
            home_injuries={k: v for k, v in hi.items() if k != "weights"},
            away_injuries={k: v for k, v in ai.items() if k != "weights"},
        ))
    return preds, this_season


LOG_COLS = ["sport", "event_id", "date", "home", "away", "spread", "predicted_home_margin", "home_win_prob",
            "injury_adjustment", "logged_at"]


def lock_pregame(preds):
    """Keep the last prediction made before each game starts, in data/pregame_log.csv.
    Only games starting within 45 minutes are written, so the file changes only near game time."""
    path = os.path.join(DATA, "pregame_log.csv")
    log = {}
    if os.path.exists(path):
        with open(path) as f:
            log = {r["event_id"]: r for r in csv.DictReader(f)}
    now = dt.datetime.now(dt.timezone.utc)
    changed = False
    for p in preds:
        start = dt.datetime.fromisoformat(p["date"].replace("Z", "+00:00"))
        if now <= start <= now + dt.timedelta(minutes=45):
            row = {k: p.get(k) for k in LOG_COLS}
            row["logged_at"] = now.isoformat(timespec="minutes")
            log[p["event_id"]] = row
            changed = True
    if changed or not os.path.exists(path):
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, LOG_COLS)
            w.writeheader()
            w.writerows(sorted(log.values(), key=lambda r: r["date"]))


def main(sports):
    summary = json.load(open(os.path.join(DATA, "backtest_summary.json")))
    allpreds = []
    for sport in sports:
        settings, w = summary[sport]["settings"], summary[sport].get("blend_w", 0.0)
        preds, season = predict_sport(sport, settings, w)
        for g in season:  # track record grades the main (line-leaning) prediction
            g["pred_model"] = g["pred"]
            g["pred"] = blend(g["pred"], g.get("spread"), w)
            g["win_prob"] = win_prob(g["pred"], settings["sigma"])
        allpreds += preds
        cols = ["sport", "event_id", "date", "home", "home_name", "away", "away_name", "home_score",
                "away_score", "spread", "pred", "pred_model", "win_prob", "home_missing", "away_missing", "home_fbs", "away_fbs"]
        with open(os.path.join(DATA, f"season_{sport}.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, cols, extrasaction="ignore")
            w.writeheader()
            for g in season:
                w.writerow({k: (round(g[k], 2) if isinstance(g.get(k), float) else g.get(k)) for k in cols})
        print(sport, len(preds), "upcoming,", len(season), "played this season")
    allpreds.sort(key=lambda p: p["date"])
    lock_pregame(allpreds)
    from .parlays import update_parlays
    update_parlays(allpreds)
    stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    json.dump(dict(updated=stamp, games=allpreds), open(os.path.join(DATA, "predictions.json"), "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv[1:] or ["nfl", "nba", "cfb"])
