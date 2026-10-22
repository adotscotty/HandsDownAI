"""Free NFL play-by-play from nflverse: how efficiently each team moved the ball in each game.

EPA ("expected points added") says how many points each play was worth, given the down, distance and
field position. Adding up a team's offensive plays gives an efficiency score for the game that is
less affected by luck (fumble bounces, last-second scores) than the final score.
"""
import csv, datetime as dt, gzip, io, os, urllib.request

URL = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.csv.gz"
CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "cache", "pbp")
TO_ESPN = {"WAS": "WSH", "LA": "LAR"}  # nflverse team code -> ESPN team code


def download(season, refresh=False):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"pbp_{season}.csv.gz")
    if refresh or not os.path.exists(path):
        req = urllib.request.Request(URL.format(season=season), headers={"User-Agent": "sports-ai/0.1"})
        with urllib.request.urlopen(req, timeout=300) as r, open(path, "wb") as f:
            f.write(r.read())
    return path


def game_efficiency(season, refresh=False):
    """{(eastern date 'YYYY-MM-DD', ESPN home code): dict(home_epa, away_epa, home_epa_close, away_epa_close)}
    *_epa: total EPA on the team's runs and passes. *_epa_close: same, but only while the game was
    still competitive (win chance between 10% and 90%), so garbage time counts less."""
    games = {}
    with gzip.open(download(season, refresh), "rt", newline="") as f:
        for row in csv.DictReader(f):
            if row["play_type"] not in ("pass", "run") or row["qb_kneel"] == "1" or row["qb_spike"] == "1":
                continue
            try:
                epa = float(row["epa"])
            except ValueError:
                continue
            home = TO_ESPN.get(row["home_team"], row["home_team"])
            key = (row["game_date"], home)
            g = games.setdefault(key, dict(home_epa=0.0, away_epa=0.0, home_epa_close=0.0, away_epa_close=0.0,
                                           home_epa_noto=0.0, away_epa_noto=0.0))
            side = "home" if row["posteam"] == row["home_team"] else "away"
            g[side + "_epa"] += epa
            if row.get("interception") != "1" and row.get("fumble_lost") != "1":
                g[side + "_epa_noto"] += epa  # turnovers are partly luck, so also keep a version without them
            try:
                wp = float(row["wp"])
            except ValueError:
                wp = 0.5
            if 0.1 <= wp <= 0.9:
                g[side + "_epa_close"] += epa
    return games


def eastern_date(iso):
    when = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (when - dt.timedelta(hours=5)).date().isoformat()  # close enough: NFL games end before 1am ET


def attach(games, seasons=None, refresh=False):
    """Add efficiency columns to ESPN game rows (in place). Returns how many games matched."""
    by_season = {}
    for g in games:
        by_season.setdefault(int(g["season"]), []).append(g)
    matched = 0
    for season, rows in by_season.items():
        if seasons and season not in seasons:
            continue
        try:
            eff = game_efficiency(season, refresh)
        except Exception as e:  # no data yet for this season, or download failed
            print("nflverse:", season, e)
            continue
        for g in rows:
            e = eff.get((eastern_date(g["date"]), g["home"]))
            if e:
                g.update({k: round(v, 2) for k, v in e.items()})
                matched += 1
    return matched
