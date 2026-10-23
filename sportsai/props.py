"""Player props (NBA + NFL): project each player's stats, compare with DraftKings' over/under
(free through ESPN), and pick the one best prop per game. Picks are locked before tip-off/kickoff
and graded at $20 each in data/props_log.csv.

Player game logs live in data/players_<sport>.csv (built from ESPN box scores).
Run `python -m sportsai.props build` once to create them from history.
"""
import csv, datetime as dt, json, math, os, sys
from collections import defaultdict
from .espn import get_json, get_many, summary_url, CORE, LEAGUES
from .fetch_history import DATA

SPORTS = ("nba", "nfl")
BASE = {"nba": ["min", "pts", "reb", "ast", "tpm"],
        "nfl": ["pass_yds", "pass_cmp", "pass_att", "rush_yds", "carries", "rec_yds", "rec", "tgt"]}
COMBOS = {"pr": ("pts", "reb"), "pa": ("pts", "ast"), "ar": ("ast", "reb"), "pra": ("pts", "reb", "ast"),
          "rr_yds": ("rush_yds", "rec_yds"), "pr_yds": ("pass_yds", "rush_yds")}
PROP_TYPES = {
    "nba": {"Total Points": "pts", "Total Rebounds": "reb", "Total Assists": "ast", "Total 3-Point Field Goals": "tpm",
            "Total Points and Rebounds": "pr", "Total Points and Assists": "pa", "Total Assists and Rebounds": "ar",
            "Total Points, Rebounds, and Assists": "pra"},
    "nfl": {f"Total {k} (incl. overtime)": v for k, v in {
        "Passing Yards": "pass_yds", "Pass Completions": "pass_cmp", "Passing Attempts": "pass_att",
        "Rushing Yards": "rush_yds", "Carries": "carries", "Receiving Yards": "rec_yds", "Receptions": "rec",
        "Rushing Plus Receiving Yards": "rr_yds", "Passing Plus Rushing Yards": "pr_yds"}.items()},
}
LABEL = {"pts": "points", "reb": "rebounds", "ast": "assists", "tpm": "threes", "pr": "points + rebounds",
         "pa": "points + assists", "ar": "assists + rebounds", "pra": "points + rebounds + assists",
         "pass_yds": "passing yards", "pass_cmp": "completions", "pass_att": "pass attempts",
         "rush_yds": "rushing yards", "carries": "carries", "rec_yds": "receiving yards", "rec": "receptions",
         "rr_yds": "rushing + receiving yards", "pr_yds": "passing + rushing yards"}
# How spread out results are around our projection: sd = c * projection ** b (fitted on the 2025 season)
SPREAD = {"pts": (3.015, 0.3), "reb": (1.442, 0.4), "ast": (1.277, 0.4), "tpm": (1.169, 0.4), "pr": (3.297, 0.3),
          "pa": (3.136, 0.3), "ar": (1.972, 0.3), "pra": (3.447, 0.3),
          "pass_yds": (18.679, 0.3), "pass_cmp": (3.274, 0.3), "pass_att": (4.291, 0.3), "rush_yds": (3.258, 0.6),
          "carries": (1.088, 0.7), "rec_yds": (4.439, 0.5), "rec": (0.923, 0.6), "rr_yds": (7.069, 0.4),
          "pr_yds": (18.653, 0.3)}
MODEL_W = 0.5      # how much to trust our projection vs DraftKings' (no-vig) price
MIN_EV = 0.03      # only pick a prop that looks at least 3% profitable
STAKE = 20.0


# ---------- player game logs ----------

def _num(x):
    try:
        return float(str(x).replace("+", ""))
    except (TypeError, ValueError):
        return 0.0


def player_rows(sport, summary, game):
    """One row per player per game with the stats we project."""
    rows = {}
    for team in summary.get("boxscore", {}).get("players", []):
        tid = team["team"]["id"]
        opp = game["away_id"] if tid == game["home_id"] else game["home_id"]
        for group in team.get("statistics", []):
            keys = group.get("keys") or []
            for a in group.get("athletes", []):
                pid = (a.get("athlete") or {}).get("id")
                st = dict(zip(keys, a.get("stats", [])))
                if not pid or not st:
                    continue
                r = rows.setdefault(pid, dict(season=game["season"], date=game["date"], event_id=game["event_id"],
                                              team_id=tid, opp_id=opp, pid=pid,
                                              name=a["athlete"].get("displayName", ""),
                                              **{k: 0.0 for k in BASE[sport]}))
                if sport == "nba":
                    if not _num(st.get("minutes")):
                        rows.pop(pid)
                        continue
                    r.update(min=_num(st.get("minutes")), pts=_num(st.get("points")), reb=_num(st.get("rebounds")),
                             ast=_num(st.get("assists")),
                             tpm=_num(str(st.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted", "0-0")).split("-")[0]))
                elif group.get("name") == "passing":
                    c, att = (str(st.get("completions/passingAttempts", "0/0")) + "/0").split("/")[:2]
                    r.update(pass_yds=_num(st.get("passingYards")), pass_cmp=_num(c), pass_att=_num(att))
                elif group.get("name") == "rushing":
                    r.update(rush_yds=_num(st.get("rushingYards")), carries=_num(st.get("rushingAttempts")))
                elif group.get("name") == "receiving":
                    r.update(rec_yds=_num(st.get("receivingYards")), rec=_num(st.get("receptions")),
                             tgt=_num(st.get("receivingTargets")))
    if sport == "nfl":  # keep only players with a passing, rushing or receiving line
        rows = {k: v for k, v in rows.items() if any(v[s] for s in ("pass_att", "carries", "rec", "rec_yds", "rush_yds"))}
    return list(rows.values())


def cols(sport):
    return ["season", "date", "event_id", "team_id", "opp_id", "pid", "name"] + BASE[sport]


def load_players(sport):
    path = os.path.join(DATA, f"players_{sport}.csv")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["season"] = int(r["season"])
        for k in BASE[sport]:
            r[k] = float(r[k] or 0)
    return rows


def save_players(sport, rows):
    rows = sorted(rows, key=lambda r: (r["date"], r["event_id"], r["pid"]))
    with open(os.path.join(DATA, f"players_{sport}.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, cols(sport), extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (f"{r[k]:g}" if isinstance(r[k], float) else r[k]) for k in cols(sport)})


def add_games(sport, rows, games):
    """Add box-score rows for finished games that aren't in the log yet."""
    have = {r["event_id"] for r in rows}
    new = [g for g in games if g.get("completed") and g["event_id"] not in have]
    if not new:
        return rows, 0
    sums = get_many([summary_url(sport, g["event_id"]) for g in new])
    for g, s in zip(new, sums):
        rows.extend(player_rows(sport, s or {}, g))
    return rows, len(new)


def build(sports, seasons=(2024, 2025)):
    from .backtest import load
    for sport in sports:
        games = [dict(g, completed=True) for g in load(sport) if g["season"] in seasons]
        rows, n = add_games(sport, [], games)
        save_players(sport, rows)
        print(sport, n, "games", len(rows), "player rows")


# ---------- projections ----------

class Projector:
    """Walks through player game logs in date order; projects the next game from earlier games only."""
    DECAY = {"nba": 0.92, "nfl": 0.88}
    MIN_DECAY = 0.8

    def __init__(self, sport):
        self.sport = sport
        self.hist = defaultdict(list)    # pid -> rows, oldest first
        self.team = {}
        self.names = {}

    def add(self, r):
        self.hist[r["pid"]].append(r)
        self.team[r["pid"]] = r["team_id"]
        self.names[r["pid"]] = r["name"]

    def project(self, pid, stat):
        """Projected value for this stat next game, or None if we know too little."""
        if stat in COMBOS:
            parts = [self.project(pid, s) for s in COMBOS[stat]]
            return None if any(p is None for p in parts) else sum(parts)
        rows = self.hist.get(pid, [])[-40:]
        if self.sport == "nba":
            if len(rows) < 5:
                return None
            d, wsum, ssum, msum = self.DECAY["nba"], 0.0, 0.0, 0.0
            for i, r in enumerate(reversed(rows)):
                w = d ** i
                ssum += w * r[stat]; msum += w * r["min"]; wsum += w
            rate = ssum / max(msum, 1e-9)
            mw = [(self.MIN_DECAY ** i, r["min"]) for i, r in enumerate(reversed(rows[-10:]))]
            exp_min = sum(w * m for w, m in mw) / sum(w for w, _ in mw)
            return rate * exp_min
        # NFL: weighted average over games where the player had this kind of line
        group = {"pass_yds": "pass_att", "pass_cmp": "pass_att", "pass_att": "pass_att",
                 "rush_yds": "carries", "carries": "carries", "rec_yds": "tgt", "rec": "tgt"}[stat]
        rows = [r for r in rows if r[group] > 0]
        rows = rows[-16:]
        if len(rows) < 3:
            return None
        d, wsum, ssum = self.DECAY["nfl"], 0.0, 0.0
        for i, r in enumerate(reversed(rows)):
            w = d ** i
            ssum += w * r[stat]; wsum += w
        return ssum / wsum

    def sd(self, proj, stat):
        c, b = SPREAD[stat]
        return max(c * max(proj, 0.5) ** b, 0.5)


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def p_over(proj, sd, line):
    """Chance of going over the line (a whole-number line counts a push as half)."""
    if float(line).is_integer():
        return 1 - phi((line + 0.5 - proj) / sd) + 0.5 * (phi((line + 0.5 - proj) / sd) - phi((line - 0.5 - proj) / sd))
    return 1 - phi((line - proj) / sd)


def dec(american):
    a = _num(american)
    return 1 + (a / 100 if a > 0 else 100 / abs(a)) if a else 1.909


# ---------- DraftKings props from ESPN ----------

def props_url(sport, event_id, page=1):
    sport_path, league = LEAGUES[sport].split("/")
    return (f"{CORE}/{sport_path}/leagues/{league}/events/{event_id}/competitions/{event_id}"
            f"/odds/100/propBets?limit=1000&page={page}")


def fetch_props(sport, event_id, cache=False):
    """[(pid, stat, line, over_price, under_price)] for the stats we project. ESPN lists the over first."""
    items = []
    for page in range(1, 6):
        try:
            d = get_json(props_url(sport, event_id, page), cache=cache)
        except Exception:
            break
        items += d.get("items", [])
        if page >= d.get("pageCount", 1):
            break
    pairs = defaultdict(list)
    for it in items:
        stat = PROP_TYPES[sport].get((it.get("type") or {}).get("name"))
        ref = (it.get("athlete") or {}).get("$ref", "")
        if not stat or "/athletes/" not in ref:
            continue
        pid = ref.split("/athletes/")[1].split("?")[0]
        line = ((it.get("current") or {}).get("target") or {}).get("value")
        price = ((it.get("odds") or {}).get("american") or {}).get("value")
        if line is None or price is None:
            continue
        pairs[(pid, stat, float(line))].append(price)
    return [(pid, stat, line, v[0], v[1]) for (pid, stat, line), v in pairs.items() if len(v) == 2]


def evaluate(proj_obj, pid, stat, line, over, under, w=MODEL_W):
    """Our chance and expected profit per $1 for the better side of one prop."""
    proj = proj_obj.project(pid, stat)
    if proj is None:
        return None
    do, du = dec(over), dec(under)
    fair_over = (1 / do) / (1 / do + 1 / du)
    p = w * p_over(proj, proj_obj.sd(proj, stat), line) + (1 - w) * fair_over
    ev_over, ev_under = p * do - 1, (1 - p) * du - 1
    side, ev, price, prob = ("over", ev_over, over, p) if ev_over >= ev_under else ("under", ev_under, under, 1 - p)
    return dict(pid=pid, stat=stat, line=line, side=side, price=str(price), ev=ev, prob=prob, projection=proj)


PICK = "market"      # "market": DraftKings' most likely side; "edge": our projection's biggest edge
MIN_DEC = 1.33       # skip prices worse than -300


def best_prop(proj_obj, props, skip=(), mode=PICK):
    """The single best prop for one game.
    Tested on 2025-26 NBA playoff props: our biggest edges went 29-52 (DraftKings knew better),
    while DraftKings' most likely side went 57-24 with prices no worse than -300."""
    best = None
    for pid, stat, line, over, under in props:
        if pid in skip:
            continue
        e = evaluate(proj_obj, pid, stat, line, over, under)
        if not e:
            continue
        if mode == "market":
            do, du = dec(over), dec(under)
            fair_over = (1 / do) / (1 / do + 1 / du)
            side, fair, price = ("over", fair_over, over) if fair_over >= 0.5 else ("under", 1 - fair_over, under)
            if dec(price) < MIN_DEC:
                continue
            our = e["prob"] if e["side"] == side else 1 - e["prob"]
            e.update(side=side, price=str(price), market_prob=fair, prob=our, ev=our * dec(price) - 1, score=fair)
        else:
            e["score"] = e["ev"]
            if e["ev"] < MIN_EV:
                continue
        if best is None or e["score"] > best["score"]:
            best = e
    if best:
        best["name"] = proj_obj.names.get(best["pid"], "")
        best["label"] = LABEL[best["stat"]]
    return best


def stat_value(row, stat):
    return sum(row[s] for s in COMBOS[stat]) if stat in COMBOS else row[stat]


# ---------- live: pick, lock and grade ----------

LOG_COLS = ["sport", "event_id", "date", "game", "pid", "name", "stat", "label", "side", "line", "price",
            "projection", "prob", "ev", "actual", "result", "profit", "logged_at"]


def load_log():
    path = os.path.join(DATA, "props_log.csv")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return list(csv.DictReader(f))


def save_log(rows):
    with open(os.path.join(DATA, "props_log.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, LOG_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["date"], r["event_id"])))


def update_sport(sport, preds, done_games):
    """Refresh player logs, attach the best prop to each upcoming game, return the projector's player rows."""
    rows = load_players(sport)
    rows, n = add_games(sport, rows, done_games)
    if n:
        save_players(sport, rows)
    proj = Projector(sport)
    for r in sorted(rows, key=lambda r: r["date"]):
        proj.add(r)
    games = [p for p in preds if p["sport"] == sport]
    lists = get_many([props_url(sport, p["event_id"]) for p in games], cache=False)
    for p, first in zip(games, lists):
        p["best_prop"] = None
        if not first or not first.get("items"):
            continue
        props = fetch_props(sport, p["event_id"])
        out = {i["id"] for side in ("home_injuries", "away_injuries") for i in (p.get(side) or {}).get("all_injuries", [])}
        best = best_prop(proj, props, skip=out)
        if best:
            p["best_prop"] = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in best.items()}
    return rows


def lock_and_grade(preds, player_rows):
    """Lock each game's best prop 45 minutes before start; grade finished ones from the box score."""
    now = dt.datetime.now(dt.timezone.utc)
    log = load_log()
    have = {(r["sport"], r["event_id"]) for r in log}
    for p in preds:
        bp = p.get("best_prop")
        if not bp or (p["sport"], p["event_id"]) in have:
            continue
        start = dt.datetime.fromisoformat(p["date"].replace("Z", "+00:00"))
        if start - now <= dt.timedelta(minutes=45):
            log.append(dict(sport=p["sport"], event_id=p["event_id"], date=p["date"], game=p["name"], pid=bp["pid"],
                            name=bp["name"], stat=bp["stat"], label=bp["label"], side=bp["side"], line=bp["line"],
                            price=bp["price"], projection=round(bp["projection"], 1), prob=bp["prob"], ev=bp["ev"],
                            actual="", result="", profit="", logged_at=now.isoformat(timespec="minutes")))
    by_game = defaultdict(dict)
    played = defaultdict(set)
    for sport, rows in player_rows.items():
        for r in rows:
            by_game[(sport, r["event_id"])][r["pid"]] = r
    for r in log:
        if r["result"] or (r["sport"], r["event_id"]) not in by_game:
            continue
        box = by_game[(r["sport"], r["event_id"])]
        if r["pid"] not in box:   # player sat out: sportsbooks void (refund) the bet
            r.update(actual="", result="void", profit="0")
            continue
        val = stat_value(box[r["pid"]], r["stat"])
        line = float(r["line"])
        if val == line:
            res = "push"
        else:
            res = "win" if (val > line) == (r["side"] == "over") else "loss"
        profit = (dec(r["price"]) - 1) * STAKE if res == "win" else (-STAKE if res == "loss" else 0.0)
        r.update(actual=f"{val:g}", result=res, profit=f"{profit:.2f}")
    save_log(log)
    return log


def record(log):
    """Won-lost and profit overall and per sport, for the site."""
    out = {}
    for key in ("all",) + SPORTS:
        rs = [r for r in log if r["result"] in ("win", "loss", "push") and (key == "all" or r["sport"] == key)]
        w = sum(r["result"] == "win" for r in rs); l = sum(r["result"] == "loss" for r in rs)
        profit = sum(float(r["profit"]) for r in rs)
        staked = STAKE * (w + l)
        out[key] = dict(wins=w, losses=l, pushes=len(rs) - w - l, profit=round(profit, 2),
                        roi=round(100 * profit / staked, 1) if staked else None)
    recent = [r for r in log if r["result"]][-30:][::-1]
    return dict(record=out, recent=recent, stake=STAKE)


if __name__ == "__main__":
    if sys.argv[1:2] == ["build"]:
        build(sys.argv[2:] or SPORTS)
