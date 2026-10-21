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
import math
from collections import defaultdict, deque

DEFAULTS = {
    #       k: learning rate, early: extra learning for first games, carry: share of rating kept
    #       across seasons, hfa: home edge in points, cap: biggest margin we learn from,
    #       beta: points per unit of missing value, sigma: spread of outcomes (for win %)
    "nfl": dict(k=0.10, early=2.0, carry=0.6, hfa=1.8, cap=24, beta=4.0, sigma=13.0, new=0.0),
    "nba": dict(k=0.06, early=2.0, carry=0.6, hfa=2.5, cap=25, beta=0.5, sigma=12.5, new=0.0),
    "cfb": dict(k=0.12, early=2.0, carry=0.7, hfa=2.8, cap=35, beta=5.0, sigma=15.5, new=-18.0),
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

    def usual_qb(self, team):
        q = self.qbs[team]
        if len(q) < 2:
            return None
        best = max(set(q), key=list(q).count)
        return best if list(q).count(best) >= 2 else None

    # ---------- predict / update ----------
    def predict(self, home, away, neutral=False, home_main=True, away_main=True,
                home_missing=0.0, away_missing=0.0):
        p = self.p
        m = (0 if neutral else p["hfa"]) + self.rating(home, home_main) - self.rating(away, away_main)
        m -= p["beta"] * (home_missing - away_missing)
        return m, win_prob(m, p["sigma"])

    def update(self, home, away, margin, pred):
        p = self.p
        err = max(-p["cap"], min(p["cap"], margin)) - pred
        for team, sign in ((home, 1), (away, -1)):
            k = p["k"] * (1 + p["early"] / (1 + self.n[team]))
            self.r[team] += sign * k * err
            self.n[team] += 1

    def record_lineup(self, team, players=None, qb=None):
        if players is not None:   # NBA: {pid: (minutes, game_score)}
            self.recent[team].append(set(players))
            for pid, (mins, gs) in players.items():
                self.pmin[(team, pid)].append(mins)
                self.pval[(team, pid)].append(gs)
        if qb:
            self.qbs[team].append(qb)


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
        if sport == "nba":
            hp, ap = parse_players(g.get("home_players")), parse_players(g.get("away_players"))
            if hp and ap:  # missing = regulars who did not play
                hm = model.missing_value(h, {pid: 1.0 for pid in model.regulars(h) if pid not in hp})
                am = model.missing_value(a, {pid: 1.0 for pid in model.regulars(a) if pid not in ap})
        else:
            for side, team in (("home", h), ("away", a)):
                usual, played = model.usual_qb(team), g.get(side + "_qb")
                miss = 1.0 if usual and played and played != usual else 0.0
                if side == "home": hm = miss
                else: am = miss
        pred, wp = model.predict(h, a, g["neutral"], g.get("home_fbs", 1), g.get("away_fbs", 1), hm, am)
        margin = g["home_score"] - g["away_score"]
        out.append({**g, "pred": pred, "win_prob": wp, "home_missing": hm, "away_missing": am,
                    "pred_no_injury": pred + model.p["beta"] * (hm - am)})
        model.update(h, a, margin, pred)
        if sport == "nba":
            model.record_lineup(h, players=hp); model.record_lineup(a, players=ap)
        else:
            model.record_lineup(h, qb=g.get("home_qb")); model.record_lineup(a, qb=g.get("away_qb"))
    return out, model
