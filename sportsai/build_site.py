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


# ---------- daily results and recap ----------

def _csv(name):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return list(csv.DictReader(f))


def line_txt(x):
    return "PK" if x == 0 else f"{x:+g}"


def leg_txt(l):
    if l["type"] == "prop":
        return f'{l["name"]} {l["side"]} {l["line"]:g} {l["label"]}'
    if l["type"] == "ml":
        return f'{l.get("team_name") or l["team"]} to win'
    return f'{l["team"]} {line_txt(l["line"])}'


BET_NAMES = {"winner": "Best winner", "spread": "Best spread", "parlay": "Best parlay", "prop": "Best prop",
             "sgp": "Best same-game parlay"}


def daily(day):
    """Everything we picked on one Eastern date, with results for games that have finished."""
    from .parlays import results, decimal
    games = []
    for sport in ("nfl", "nba", "cfb"):
        for r in load_season(sport):
            if eastern_date(r["date"]).isoformat() != day:
                continue
            m = r["home_score"] - r["away_score"]
            g = dict(sport=sport, date=r["date"], home=r["home"], away=r["away"], home_score=r["home_score"],
                     away_score=r["away_score"], pred=round(r["pred"], 1), spread=r["spread"],
                     winner_right=(r["pred"] > 0) == (m > 0))
            if r["spread"] is not None and r["pred"] + r["spread"] != 0:
                home = r["pred"] + r["spread"] > 0
                by = (m + r["spread"]) if home else -(m + r["spread"])
                g.update(pick=f'{r["home"] if home else r["away"]} {line_txt(r["spread"] if home else -r["spread"])}',
                         ats="win" if by > 0 else "loss" if by < 0 else "push", by=by)
            games.append(g)
    games.sort(key=lambda g: g["date"])
    props = [dict(r, line=float(r["line"]), profit=float(r["profit"]) if r["profit"] else None)
             for r in _csv("props_log.csv") if eastern_date(r["date"]).isoformat() == day]
    finals = results()
    parlays = []
    for r in _csv("parlays_log.csv"):
        if not r["slot"].startswith(day + "|"):
            continue
        legs = json.loads(r["legs"])
        for l in legs:
            if l["event_id"] in finals:
                hs, as_ = finals[l["event_id"]]
                l["by"] = ((hs - as_) if l["side"] == "home" else (as_ - hs)) + l["line"]
                l["type"] = "spread"
        parlays.append(dict(sport=r["sport"], kind=r["kind"], legs=legs, status=r["status"],
                            payout=float(r["payout"]), profit=float(r["profit"]) if r["profit"] else None))
    best = []
    for r in _csv("bestbets_log.csv"):
        if r["date"] == day:
            b = json.loads(r["bet"])
            best.append(dict(b, status=r["status"], profit=float(r["profit"]) if r["profit"] else None))

    def tally(items, key, win, loss):
        w = sum(i.get(key) == win for i in items); l = sum(i.get(key) == loss for i in items)
        return [w, l]
    summary = dict(
        games=len(games),
        winners=[sum(g["winner_right"] for g in games), sum(not g["winner_right"] for g in games)],
        ats=tally(games, "ats", "win", "loss"),
        props=tally(props, "result", "win", "loss"),
        parlays=tally(parlays, "status", "won", "lost"),
        best_bets=tally(best, "status", "won", "lost"),
        profit=round(sum(x["profit"] or 0 for x in props + parlays + best), 2),
    )

    # Best win: biggest money win, else the biggest cover
    wins = [(x["profit"], f'{BET_NAMES[x["kind"]]}: ' + " + ".join(leg_txt(l) for l in x["legs"]),
             f'won ${x["profit"]:.2f} on $20') for x in best if x["status"] == "won"]
    wins += [(x["profit"], f'{"2" if x["kind"] == "two" else "3"}-game parlay: ' + ", ".join(leg_txt(l) for l in x["legs"]),
              f'won ${x["profit"]:.2f} on $20') for x in parlays if x["status"] == "won"]
    wins += [(x["profit"], f'{x["name"]} {x["side"]} {x["line"]:g} {x["label"]}', f'hit with {x["actual"]}, won ${x["profit"]:.2f}')
             for x in props if x["result"] == "win"]
    best_win = None
    if wins:
        w = max(wins, key=lambda t: t[0])
        best_win = dict(title=w[1], detail=w[2])
    else:
        covers = [g for g in games if g.get("ats") == "win"]
        if covers:
            g = max(covers, key=lambda g: g["by"])
            best_win = dict(title=f'{g["pick"]} ({g["away"]} {g["away_score"]} @ {g["home"]} {g["home_score"]})',
                            detail=f'covered by {g["by"]:g} points')
    # Bad beat: the loss that missed by the least
    misses = []
    for g in games:
        if g.get("ats") == "loss":
            misses.append((-g["by"], f'{g["pick"]} ({g["away"]} {g["away_score"]} @ {g["home"]} {g["home_score"]})',
                           f'missed the spread by {-g["by"]:g}'))
    for x in props:
        if x["result"] == "loss":
            miss = abs(float(x["actual"]) - x["line"])
            misses.append((miss, f'{x["name"]} {x["side"]} {x["line"]:g} {x["label"]}', f'finished with {x["actual"]}, missed by {miss:g}'))
    for x in parlays + best:
        if x["status"] != "lost":
            continue
        lost = [l for l in x["legs"] if l.get("by") is not None and l["by"] < 0]
        if len(lost) == 1 and len(x["legs"]) > 1:
            l = lost[0]
            name = BET_NAMES.get(x["kind"]) or ("2-game parlay" if x["kind"] == "two" else "3-game parlay")
            misses.append((-l["by"], f'{name}: ' + ", ".join(leg_txt(k) for k in x["legs"]),
                           f'lost on one leg: {leg_txt(l)} missed by {-l["by"]:g}'))
    bad_beat = None
    if misses:
        m = min(misses, key=lambda t: t[0])
        bad_beat = dict(title=m[1], detail=m[2])
    return dict(date=day, summary=summary, games=games, props=props, parlays=parlays, best_bets=best,
                best_win=best_win, bad_beat=bad_beat)


def main():
    os.makedirs(os.path.join(SITE, "data"), exist_ok=True)
    shutil.copy(os.path.join(DATA, "predictions.json"), os.path.join(SITE, "data", "predictions.json"))
    for extra in ("parlays.json", "props.json", "bestbets.json"):
        if os.path.exists(os.path.join(DATA, extra)):
            shutil.copy(os.path.join(DATA, extra), os.path.join(SITE, "data", extra))
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
    today = eastern_now().date()
    json.dump(dict(today=daily(today.isoformat()), yesterday=daily((today - dt.timedelta(days=1)).isoformat())),
              open(os.path.join(SITE, "data", "daily.json"), "w"))
    print("site data written")


if __name__ == "__main__":
    main()
