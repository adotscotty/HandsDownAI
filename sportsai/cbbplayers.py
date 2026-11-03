"""College basketball preseason team strength built from players, not last season's team.

Rosters turn over a lot every year (transfers, freshmen, players leaving early), so each team's
opening rating mixes in a player-based estimate: every player on this season's roster is valued by
last season's Box Plus/Minus (from barttorvik.com, any school he played for), or by his recruiting
rank if he is new to college basketball. The best players get the most minutes.
Player files: data/cbb_players/<season end year>.json  {player id: [name, team, min%, bpm, recruit rank, class, games]}
"""
import json, os, re
from .fetch_history import DATA
from .espn import get_json, teams_url

FOLDER = os.path.join(DATA, "cbb_players")
MINUTES = [85, 80, 75, 70, 65, 50, 40, 20, 15]   # share of team minutes (%) by player rank; sums to 500
GROWTH = {"Fr": 1.5, "So": 1.0, "Jr": 0.5}       # typical BPM gain going into next season, by last season's class
ALIASES = {"Albany": "399", "Appalachian St.": "2026", "Cal Baptist": "2856", "Connecticut": "41",
           "Grambling St.": "2755", "Illinois Chicago": "82", "LIU": "112358", "Louisiana Monroe": "2433",
           "McNeese St.": "2377", "Miami FL": "2390", "Miami OH": "193", "Mississippi": "145", "N.C. State": "152",
           "Nebraska Omaha": "2437", "New Orleans": "2443", "Nicholls St.": "2447", "Sam Houston St.": "2534",
           "San Jose St.": "23", "Seattle": "2547", "Southeastern Louisiana": "2545", "Tennessee Martin": "2630",
           "Texas A&M Corpus Chris": "357", "UMKC": "140", "USC Upstate": "2908"}


def _norm(s):
    s = s.lower().replace("&", " and ").replace("st.", "state").replace("saint", "st").replace("'", "")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\bstate\b", "st", s)
    return " ".join(s.split())


_IDS = None


def team_id(name):
    global _IDS
    if _IDS is None:
        _IDS = {}
        try:
            for t in get_json(teams_url("cbb"))["sports"][0]["leagues"][0]["teams"]:
                t = t["team"]
                for k in (t["location"], t["shortDisplayName"], t.get("nickname") or "", t["displayName"]):
                    if k:
                        _IDS.setdefault(_norm(k), t["id"])
        except Exception as e:
            print("college basketball team list not loaded:", e)
    return ALIASES.get(name) or _IDS.get(_norm(name))


def load(end_year):
    try:
        with open(os.path.join(FOLDER, f"{end_year}.json")) as f:
            return json.load(f)
    except Exception:
        return {}


def player_value(pid, now, before, rec_w=0.07, fresh=-3.0, unknown=-4.0):
    """Expected BPM this season."""
    if pid in before and before[pid][2] >= 10:          # played real minutes last season
        _, _, _, bpm, _, cls, _ = before[pid]
        return bpm + GROWTH.get(cls, 0.0)
    rec = now[pid][4]
    if rec is not None:                                    # new to college: recruiting rank (0-100)
        return fresh + rec_w * rec
    return unknown


def preseason(season, **kw):
    """{ESPN team id: player-based strength in points per game vs an average team}, for the season
    starting in `season` (2025 = 2025-26). Uses that season's roster file and the one before."""
    now, before = load(season + 1), load(season)
    if not now:
        return {}
    teams = {}
    for pid, row in now.items():
        teams.setdefault(row[1], []).append(player_value(pid, now, before, **kw))
    out = {}
    for name, vals in teams.items():
        tid = team_id(name)
        if not tid:
            continue
        vals = sorted(vals, reverse=True)
        out[tid] = 0.68 * sum(v * m / 100 for v, m in zip(vals, MINUTES))  # per 100 possessions -> per game
    return out


def update(end_year=None):
    """Refresh this season's player file from barttorvik.com (about once a day)."""
    import csv, datetime as dt, io, time, urllib.request
    today = dt.date.today()
    end_year = end_year or (today.year + 1 if today.month >= 8 else today.year)
    path = os.path.join(FOLDER, f"{end_year}.json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < 20 * 3600:
        return
    req = urllib.request.Request(f"https://barttorvik.com/getadvstats.php?year={end_year}&csv=1",
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        text = r.read().decode("utf8", "ignore")
    out = {}
    for row in csv.reader(io.StringIO(text)):
        try:
            out[row[32]] = [row[0], row[1], float(row[4] or 0), float(row[50] or 0),
                            float(row[34]) if row[34] else None, row[25], int(row[3] or 0)]
        except (ValueError, IndexError):
            pass
    if len(out) > 100:   # ignore an empty or blocked download
        os.makedirs(FOLDER, exist_ok=True)
        with open(path, "w") as f:
            json.dump(out, f, separators=(",", ":"))
        print("college basketball players:", len(out))


if __name__ == "__main__":
    update()
