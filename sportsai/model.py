"""Team-rating model that predicts margin of victory and win probability.

How it works, in plain terms:
- Every team has a rating in points (how much better than an average team it is).
- Predicted home margin = home edge + home rating - away rating - injury penalty.
- After each game, both teams' ratings move toward what the result says
  (a bit more early in the season, when we know less).
- Between seasons, ratings are pulled part of the way back toward average.
- Injury penalty: NBA uses the value of regular players who are missing;
  NFL / college use whether the team's usual starting quarterback is missing.
"""
import datetime as dt
import math
from collections import defaultdict, deque

DEFAULTS = {
    #       k: learning rate, early: extra learning for first games, carry: share of rating kept
    #       across seasons, hfa: home edge in points, cap: biggest margin we learn from,
    #       beta: points per unit of missing value, sigma: spread of outcomes (for win %),
    #       rest: points per extra day of rest vs the opponent (counted up to rest_cap days),
    #       qbq: points per unit of QB quality drop (adjusted net yards per dropback) when the
    #       usual starter is replaced, qb_repl: assumed quality of a QB we know nothing about,
    #       epa_w: how much the ratings learn from play-by-play efficiency instead of the final
    #       score (0 = score only), epa_scale: points per unit of efficiency margin,
    #       epa_close: 1 = only count plays while the game was still competitive, 2 = leave out turnovers
    "nfl": dict(k=0.10, early=2.0, carry=0.6, hfa=1.8, cap=24, beta=4.0, sigma=13.0, new=0.0,
                rest=0.0, rest_cap=14, qbq=0.0, qb_repl=4.5, epa_w=0.0, epa_scale=0.8, epa_close=0),
    "nba": dict(k=0.06, early=2.0, carry=0.6, hfa=2.5, cap=25, beta=0.5, sigma=12.5, new=0.0,
                rest=0.0, rest_cap=3, qbq=0.0, qb_repl=0.0),
    "cfb": dict(k=0.12, early=2.0, carry=0.7, hfa=2.8, cap=35, beta=5.0, sigma=15.5, new=-18.0,
                rest=0.0, rest_cap=14, qbq=0.0, qb_repl=5.0),
}


def win_prob(margin, sigma):
    return 0.5 * (1 + math.erf(margin / (sigma * math.sqrt(2))))


class RatingModel:
    def __init__(self, sport, **params):
        self.sport = sport
        self.p = {**DEFAULTS[sport], **params}
        self.r = defaultdict(float)          # team -> rating
        self.n = defaultdict(int)            # team -> games this season
        self.season = None
        # injury bookkeeping
        self.recent = defaultdict(lambda: deque(maxlen=10))   # team -> recent games' player sets
        self.pval = defaultdict(lambda: deque(maxlen=20))     # (team, player) -> recent game scores
        self.pmin = defaultdict(lambda: deque(maxlen=10))     # (team, player) -> recent minutes
        self.qbs = defaultdict(lambda: deque(maxlen=6))       # team -> recent starting QBs
        self.qbstats = defaultdict(lambda: deque(maxlen=24))  # QB -> recent (adj. net yards, dropbacks)
        self.last_game = {}                                   # team -> date of last game

    # ---------- season handling ----------
    def start_season(self, season):
        if self.season is not None and season != self.season:
            for t in self.r:
                self.r[t] *= self.p["carry"]
            self.n.clear()
            # Player history and QBs carry over, so injuries count from opening night.
        self.season = season

    def rating(self, team, is_main=True):
        if team not in self.r and not is_main:
            self.r[team] = self.p["new"]   # e.g. small-division college teams start low
        return self.r[team]

    # ---------- injuries ----------
    def regulars(self, team):
        """NBA: players who usually play real minutes, with their value."""
        games = self.recent[team]
        if len(games) < 3:
            return {}
        out = {}
        for (t, pid), mins in list(self.pmin.items()):
            if t != team:
                continue
            played = sum(pid in g for g in games)
            avg_min = sum(mins) / len(mins)
            if played >= 0.5 * len(games) and avg_min >= 15:
                vals = self.pval[(t, pid)]
                out[pid] = max(sum(vals) / len(vals), 0.0)
        return out

    def missing_value(self, team, available):
        """Total value of regulars not in `available` (dict pid -> weight 0..1 of missing)."""
        if self.sport == "nba":
            regs = self.regulars(team)
            return sum(v * available.get(pid, 0.0) for pid, v in regs.items())
        return available.get("__qb__", 0.0)

    def qb_value(self, pid):
        """A QB's adjusted net yards per dropback, blended with a backup-level guess
        until he has a few games of data."""
        hist = self.qbstats.get(pid, ())
        prior = 120  # about 4 games' worth of dropbacks
        pts = sum(h[0] for h in hist) + prior * self.p["qb_repl"]
        db = sum(h[1] for h in hist) + prior
        return pts / db

    def qb_drop(self, team, starter):
        """How much worse (per dropback) this game's starter is than the team's usual QB."""
        usual = self.usual_qb(team)
        if not usual or not starter or starter == usual:
            return 0.0
        return self.qb_value(usual) - self.qb_value(starter)

    def backup_qb(self, team):
        """Most recent starter for this team other than the usual one (None if none)."""
        usual = self.usual_qb(team)
        for pid in reversed(self.qbs[team]):
            if pid != usual:
                return pid
        return None

    def rest_days(self, team, when):
        last = self.last_game.get(team)
        if last is None or (when - last).days > 60:
            return self.p["rest_cap"]  # first game of the season: fully rested
        return min((when - last).total_seconds() / 86400, self.p["rest_cap"])

    def usual_qb(self, team):
        q = self.qbs[team]
        if len(q) < 2:
            return None
        recent = list(q)
        # most starts; ties go to whoever started most recently
        best = max(recent, key=lambda pid: (recent.count(pid), max(i for i, x in enumerate(recent) if x == pid)))
        return best if list(q).count(best) >= 2 else None

    # ---------- predict / update ----------
    def predict(self, home, away, neutral=False, home_main=True, away_main=True,
                home_missing=0.0, away_missing=0.0, rest_diff=0.0, home_qb_drop=0.0, away_qb_drop=0.0):
        p = self.p
        m = (0 if neutral else p["hfa"]) + self.rating(home, home_main) - self.rating(away, away_main)
        m -= p["beta"] * (home_missing - away_missing)
        m += p["rest"] * rest_diff
        m -= p["qbq"] * (home_qb_drop - away_qb_drop)
        return m, win_prob(m, p["sigma"])

    def update(self, home, away, margin, pred, eff_margin=None):
        p = self.p
        target = max(-p["cap"], min(p["cap"], margin))
        if eff_margin is not None and p.get("epa_w"):
            eff = max(-p["cap"], min(p["cap"], p["epa_scale"] * eff_margin))
            target = (1 - p["epa_w"]) * target + p["epa_w"] * eff
        err = target - pred
        for team, sign in ((home, 1), (away, -1)):
            k = p["k"] * (1 + p["early"] / (1 + self.n[team]))
            self.r[team] += sign * k * err
            self.n[team] += 1

    def record_lineup(self, team, players=None, qb=None, qb_line=None, when=None):
        if when is not None:
            self.last_game[team] = when
        if qb and qb_line and qb_line[1] > 0:
            self.qbstats[qb].append(qb_line)
        if players is not None:   # NBA: {pid: (minutes, game_score)}
            self.recent[team].append(set(players))
            for pid, (mins, gs) in players.items():
                self.pmin[(team, pid)].append(mins)
                self.pval[(team, pid)].append(gs)
        if qb:
            self.qbs[team].append(qb)


def eff_margin(g, p):
    """Home team's play-by-play efficiency edge in the game (None if we don't have it)."""
    suffix = {0: "_epa", 1: "_epa_close", 2: "_epa_noto"}[int(p.get("epa_close") or 0)]
    try:
        return float(g["home" + suffix]) - float(g["away" + suffix])
    except (KeyError, TypeError, ValueError):
        return None


def qb_line(g, side):
    try:
        return (float(g.get(side + "_qb_pts")), float(g.get(side + "_qb_db")))
    except (TypeError, ValueError):
        return None


def parse_players(s):
    out = {}
    for part in (s or "").split(";"):
        if part:
            pid, m, gs = part.split(":")
            out[pid] = (float(m), float(gs))
    return out


def run(sport, games, params=None):
    """Walk through games in date order. Each prediction uses only earlier games.
    Returns the games with 'pred' and 'win_prob' filled in."""
    model = RatingModel(sport, **(params or {}))
    out = []
    for g in games:
        model.start_season(g["season"])
        h, a = g["home_id"], g["away_id"]
        hm = am = 0.0
        hq = aq = 0.0
        when = dt.datetime.fromisoformat(g["date"].replace("Z", "+00:00"))
        rest = model.rest_days(h, when) - model.rest_days(a, when)
        if sport == "nba":
            hp, ap = parse_players(g.get("home_players")), parse_players(g.get("away_players"))
            if hp and ap:  # missing = regulars who did not play
                hm = model.missing_value(h, {pid: 1.0 for pid in model.regulars(h) if pid not in hp})
                am = model.missing_value(a, {pid: 1.0 for pid in model.regulars(a) if pid not in ap})
        else:
            for side, team in (("home", h), ("away", a)):
                usual, played = model.usual_qb(team), g.get(side + "_qb")
                miss = 1.0 if usual and played and played != usual else 0.0
                drop = model.qb_drop(team, played) if miss else 0.0
                if side == "home": hm, hq = miss, drop
                else: am, aq = miss, drop
        pred, wp = model.predict(h, a, g["neutral"], g.get("home_fbs", 1), g.get("away_fbs", 1), hm, am,
                                 rest, hq, aq)
        margin = g["home_score"] - g["away_score"]
        out.append({**g, "pred": pred, "win_prob": wp, "home_missing": hm, "away_missing": am,
                    "pred_no_injury": pred + model.p["beta"] * (hm - am) + model.p["qbq"] * (hq - aq),
                    "rest_diff": rest, "home_qb_drop": hq, "away_qb_drop": aq})
        model.update(h, a, margin, pred, eff_margin(g, model.p))
        if sport == "nba":
            model.record_lineup(h, players=hp, when=when); model.record_lineup(a, players=ap, when=when)
        else:
            for side, team in (("home", h), ("away", a)):
                model.record_lineup(team, qb=g.get(side + "_qb"), qb_line=qb_line(g, side), when=when)
    return out, model
