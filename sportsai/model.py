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
import datetime as dt, json, os
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
    # NBA only:
    #       lu: points per unit of tonight's lineup strength vs. the team's usual lineup,
    #       lu_mix: how lineup strength rates players (1 = on-court plus-minus, 0 = box-score Game Score),
    #       luck: share of three-point shooting luck removed before ratings learn from a game,
    #       pace_adj: 1 = rate teams per possession and scale by tonight's expected pace,
    #       late_tank / late_top: points taken off weak / strong teams in the last weeks of the season
    "nfl": dict(k=0.10, early=2.0, carry=0.6, hfa=1.8, cap=24, beta=4.0, sigma=13.0, new=0.0,
                rest=0.0, rest_cap=14, qbq=0.0, qb_repl=4.5, epa_w=0.0, epa_scale=0.8, epa_close=0),
    "nba": dict(wt_w=0.75, wt_k=2.7, k=0.06, early=2.0, carry=0.6, hfa=2.5, cap=25, beta=0.5, sigma=12.5, new=0.0,
                rest=0.0, rest_cap=3, qbq=0.0, qb_repl=0.0,
                lu=0.7, lu_mix=0.0, luck=0.25, pace_adj=1, late_tank=5.0, late_top=0.0),
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
        self.roster = defaultdict(set)                        # team -> players seen (NBA)
        self.pstats = defaultdict(lambda: deque(maxlen=40))   # player -> recent (minutes, game score, +/-)
        self.lu_hist = defaultdict(lambda: deque(maxlen=10))  # team -> lineup strength in recent games
        self.pace = {}                                        # team -> possessions per game (smoothed)
        self.lg_pace, self.lg_3p = 99.0, 0.36
        self.wl = defaultdict(lambda: [0, 0])                 # team -> [wins, games] this season
        self.preseason = {}                                   # season -> {team: preseason win total}
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", f"wintotals_{sport}.json")
        if os.path.exists(path):
            self.preseason = json.load(open(path)).get("wins", {})

    # ---------- season handling ----------
    def start_season(self, season):
        if self.season is not None and season != self.season:
            for t in self.r:
                self.r[t] *= self.p["carry"]
            # Preseason win totals know about offseason trades and signings: mix them in
            # (NBA test 2023-25: first-month spread picks 51% -> 55%, average miss 10.2 -> 10.0)
            wt = self.preseason.get(str(season), {})
            w = self.p.get("wt_w", 0.0)
            for t, wins in wt.items():
                if w and wins:
                    self.r[t] = (1 - w) * self.r[t] + w * (wins - 41) / self.p.get("wt_k", 2.7)
            self.n.clear()
            self.wl.clear()
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
        for pid in self.roster[team]:
            mins = self.pmin[(team, pid)]
            played = sum(pid in g for g in games)
            avg_min = sum(mins) / len(mins)
            if played >= 0.5 * len(games) and avg_min >= 15:
                vals = self.pval[(team, pid)]
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

    # ---------- NBA lineup strength ----------
    def impact(self, pid):
        """Per-48-minute value of a player, blended toward zero until he has played a lot."""
        hist = self.pstats.get(pid, ())
        mins = sum(h[0] for h in hist) + 300
        pm48 = 48 * sum(h[2] for h in hist) / mins
        gs48 = 48 * (sum(h[1] for h in hist) + 300 * 0.25) / mins - 16
        mix = self.p["lu_mix"]
        return mix * pm48 + (1 - mix) * gs48

    def expected_minutes(self, team, pid):
        m = self.pmin.get((team, pid))
        if m:
            return sum(m) / len(m)
        hist = list(self.pstats.get(pid, ()))[-10:]  # new to this team: his recent minutes anywhere
        return sum(h[0] for h in hist) / len(hist) if hist else 12.0

    def lineup_strength(self, team, players):
        """players: {player: share of normal minutes he'll play (1 = full)}"""
        mins = {pid: self.expected_minutes(team, pid) * w for pid, w in players.items() if w > 0}
        total = sum(mins.values())
        if total <= 0:
            return None
        return sum(m / total * self.impact(pid) for pid, m in mins.items())

    def lineup_delta(self, team, players):
        hist = self.lu_hist[team]
        if len(hist) < 3 or not players:
            return 0.0, None
        now = self.lineup_strength(team, players)
        if now is None:
            return 0.0, None
        return now - sum(hist) / len(hist), now

    def expected_players(self, team, injury_weights, roster=None):
        """Live: who should play tonight = recent rotation players, less the injured ones.
        With today's roster from ESPN, use the current roster instead, so trades and signings
        count right away and departed players drop out."""
        if roster:
            known = [pid for pid in roster if self.pstats.get(pid)]
            top = sorted(known, key=lambda pid: -self.expected_minutes(team, pid))[:10]
            return {pid: 1.0 - injury_weights.get(pid, 0.0) for pid in top if self.expected_minutes(team, pid) >= 10}
        games = self.recent[team]
        out = {}
        for pid in self.roster[team]:
            if sum(pid in g for g in games) >= 3:
                out[pid] = 1.0 - injury_weights.get(pid, 0.0)
        return out

    def pace_factor(self, home, away):
        if not self.p.get("pace_adj") or home not in self.pace or away not in self.pace:
            return 1.0
        return (self.pace[home] + self.pace[away]) / 2 / self.lg_pace

    def late_flags(self, team, when, season_type):
        """(tanking, top team) late in the NBA regular season."""
        if season_type != 2:
            return 0, 0
        end = dt.datetime(when.year if when.month < 7 else when.year + 1, 4, 13, tzinfo=dt.timezone.utc)
        if (end - when).days > 25:
            return 0, 0
        w, n = self.wl[team]
        if n < 20:
            return 0, 0
        pct = w / n
        return int(pct < 0.38), int(pct > 0.68)

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
                home_missing=0.0, away_missing=0.0, rest_diff=0.0, home_qb_drop=0.0, away_qb_drop=0.0,
                pace_factor=1.0, lineup_diff=0.0, late=(0, 0, 0, 0)):
        p = self.p
        m = (0 if neutral else p["hfa"]) + self.rating(home, home_main) - self.rating(away, away_main)
        m *= pace_factor
        m += p.get("lu", 0) * lineup_diff
        ht, htop, at, atop = late
        m -= p.get("late_tank", 0) * (ht - at) + p.get("late_top", 0) * (htop - atop)
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
            for pid, (mins, gs, *rest) in players.items():
                self.pstats[pid].append((mins, gs, rest[0] if rest else 0.0))
                self.roster[team].add(pid)
                self.pmin[(team, pid)].append(mins)
                self.pval[(team, pid)].append(gs)
        if qb:
            self.qbs[team].append(qb)


def _num(g, k):
    try:
        return float(g.get(k))
    except (TypeError, ValueError):
        return None


def nba_adjusted_margin(model, g, margin, h, a):
    """NBA: take out three-point shooting luck, and put the margin on a per-possession basis.
    Also keeps the league's three-point % and pace up to date."""
    p = model.p
    vals = {f"{side}_{k}": _num(g, f"{side}_{k}") for side in ("home", "away")
            for k in ("tpm", "tpa", "fga", "oreb", "tov", "fta")}
    if any(v is None for v in vals.values()):
        return margin
    adj = margin
    if p.get("luck"):
        luck_h = vals["home_tpm"] - vals["home_tpa"] * model.lg_3p
        luck_a = vals["away_tpm"] - vals["away_tpa"] * model.lg_3p
        adj -= p["luck"] * 3 * (luck_h - luck_a)
    poss = {side: vals[f"{side}_fga"] - vals[f"{side}_oreb"] + vals[f"{side}_tov"] + 0.44 * vals[f"{side}_fta"]
            for side in ("home", "away")}
    game_pace = (poss["home"] + poss["away"]) / 2
    if p.get("pace_adj") and game_pace > 50:
        adj *= model.lg_pace / game_pace
    # keep running averages
    tpa = vals["home_tpa"] + vals["away_tpa"]
    if tpa:
        model.lg_3p += 0.002 * ((vals["home_tpm"] + vals["away_tpm"]) / tpa - model.lg_3p)
    if game_pace > 50:
        model.lg_pace += 0.002 * (game_pace - model.lg_pace)
        for team in (h, a):
            model.pace[team] = model.pace.get(team, game_pace) * 0.9 + 0.1 * game_pace
    return adj


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
            bits = part.split(":")
            out[bits[0]] = (float(bits[1]), float(bits[2]), float(bits[3]) if len(bits) > 3 else 0.0)
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
        pf, lud, late = 1.0, 0.0, (0, 0, 0, 0)
        if sport == "nba":
            hp, ap = parse_players(g.get("home_players")), parse_players(g.get("away_players"))
            if hp and ap:  # missing = regulars who did not play
                hm = model.missing_value(h, {pid: 1.0 for pid in model.regulars(h) if pid not in hp})
                am = model.missing_value(a, {pid: 1.0 for pid in model.regulars(a) if pid not in ap})
            hd, h_now = model.lineup_delta(h, {pid: 1.0 for pid in hp})
            ad, a_now = model.lineup_delta(a, {pid: 1.0 for pid in ap})
            lud = hd - ad
            pf = model.pace_factor(h, a)
            late = model.late_flags(h, when, g.get("season_type")) + model.late_flags(a, when, g.get("season_type"))
        else:
            for side, team in (("home", h), ("away", a)):
                usual, played = model.usual_qb(team), g.get(side + "_qb")
                miss = 1.0 if usual and played and played != usual else 0.0
                drop = model.qb_drop(team, played) if miss else 0.0
                if side == "home": hm, hq = miss, drop
                else: am, aq = miss, drop
        pred, wp = model.predict(h, a, g["neutral"], g.get("home_fbs", 1), g.get("away_fbs", 1), hm, am,
                                 rest, hq, aq, pf, lud, late)
        margin = g["home_score"] - g["away_score"]
        learn = margin
        if sport == "nba":
            learn = nba_adjusted_margin(model, g, margin, h, a)
        out.append({**g, "pred": pred, "win_prob": wp, "home_missing": hm, "away_missing": am,
                    "pred_no_injury": pred + model.p["beta"] * (hm - am) + model.p["qbq"] * (hq - aq),
                    "rest_diff": rest, "home_qb_drop": hq, "away_qb_drop": aq})
        # ratings learn from the margin after removing what the lineup/late-season terms explain
        model.update(h, a, learn, pred - model.p.get("lu", 0) * lud if sport == "nba" else pred,
                     eff_margin(g, model.p))
        if sport == "nba":
            model.record_lineup(h, players=hp, when=when); model.record_lineup(a, players=ap, when=when)
            for team, plist in ((h, hp), (a, ap)):
                strength = model.lineup_strength(team, {pid: 1.0 for pid in plist}) if plist else None
                if strength is not None:
                    model.lu_hist[team].append(strength)
            model.wl[h][0] += margin > 0; model.wl[h][1] += 1
            model.wl[a][0] += margin < 0; model.wl[a][1] += 1
        else:
            for side, team in (("home", h), ("away", a)):
                model.record_lineup(team, qb=g.get(side + "_qb"), qb_line=qb_line(g, side), when=when)
    return out, model
