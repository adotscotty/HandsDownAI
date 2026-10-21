"""Download past seasons (scores, closing spreads, who played) into data/games_<sport>.csv."""
import csv, datetime as dt, os, sys
from .espn import get_many, get_json, scoreboard_url, summary_url, odds_url, teams_url

SEASONS = {  # season label -> (first day, last day)
    "nfl": {2024: ("2024-09-05", "2025-02-09"), 2025: ("2025-09-04", "2026-02-08")},
    "nba": {2024: ("2024-10-22", "2025-06-23"), 2025: ("2025-10-21", "2026-06-21")},
    "cfb": {2024: ("2024-08-24", "2025-01-20"), 2025: ("2025-08-23", "2026-01-20")},
}
TEST_SEASON = 2025  # the "last season" we backtest on; 2024 is used to tune and seed ratings
DATA = os.path.join(os.path.dirname(__file__), "..", "data")


def days(a, b):
    d, end = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    while d <= end:
        yield d.strftime("%Y%m%d")
        d += dt.timedelta(days=1)


def fbs_teams_from_games(games):
    """FBS teams are the ones that show up many times in ESPN's FBS scoreboard;
    small-school (FCS) opponents only appear once or twice a season."""
    from collections import Counter
    seen = Counter()
    for g in games:
        seen[(g["season"], g["home_id"])] += 1
        seen[(g["season"], g["away_id"])] += 1
    return {(season, t) for (season, t), n in seen.items() if n >= 5}


def main_teams(sport):
    if sport == "cfb":
        return set()  # decided from the games themselves, see fbs_teams_from_games
    data = get_json(teams_url(sport))
    return {t["team"]["id"] for t in data["sports"][0]["leagues"][0]["teams"]}


def fetch_games(sport):
    known = main_teams(sport)  # NFL/NBA: real franchises; CFB: FBS teams
    games = []
    for season, (a, b) in SEASONS[sport].items():
        boards = get_many([scoreboard_url(sport, d) for d in days(a, b)])
        for board in boards:
            for ev in (board or {}).get("events", []):
                comp = ev["competitions"][0]
                if not comp["status"]["type"]["completed"]:
                    continue
                if ev.get("season", {}).get("type") not in (2, 3):  # regular season + playoffs
                    continue
                side = {c["homeAway"]: c for c in comp["competitors"]}
                h, aw = side["home"], side["away"]
                ids = {h["team"]["id"], aw["team"]["id"]}
                if sport != "cfb" and not ids <= known:
                    continue  # skips all-star / exhibition games
                games.append(dict(
                    sport=sport, season=season, event_id=ev["id"], date=ev["date"],
                    season_type=ev["season"]["type"], neutral=int(comp.get("neutralSite", False)),
                    home_id=h["team"]["id"], home=h["team"]["abbreviation"], home_score=int(h["score"]),
                    away_id=aw["team"]["id"], away=aw["team"]["abbreviation"], away_score=int(aw["score"]),
                ))
    games = list({g["event_id"]: g for g in games}.values())
    games.sort(key=lambda g: g["date"])
    fbs = fbs_teams_from_games(games) if sport == "cfb" else None
    for g in games:
        g["home_fbs"] = int(fbs is None or (g["season"], g["home_id"]) in fbs)
        g["away_fbs"] = int(fbs is None or (g["season"], g["away_id"]) in fbs)
    return games


def add_closing_spreads(sport, games, all_seasons=False):
    test = [g for g in games if all_seasons or g["season"] == TEST_SEASON]
    results = get_many([odds_url(sport, g["event_id"]) for g in test])
    for g, res in zip(test, results):
        items = (res or {}).get("items", [])
        items = [i for i in items if i.get("spread") is not None]
        if items:
            best = sorted(items, key=lambda i: i.get("provider", {}).get("priority", 9))[0]
            g["spread"] = best["spread"]  # home spread, e.g. -5.5 = home favored by 5.5
            g["total"] = best.get("overUnder")
            g["book"] = best.get("provider", {}).get("name")


def game_score(st):
    """Hollinger's Game Score: a one-number summary of a basketball box score line."""
    def n(k):
        try:
            return float(st.get(k, 0) or 0)
        except ValueError:
            return 0.0
    def pair(k):
        try:
            a, b = st.get(k, "0-0").split("-")
            return float(a), float(b)
        except ValueError:
            return 0.0, 0.0
    fg, fga = pair("fieldGoalsMade-fieldGoalsAttempted")
    ft, fta = pair("freeThrowsMade-freeThrowsAttempted")
    return (n("points") + 0.4 * fg - 0.7 * fga - 0.4 * (fta - ft) + 0.7 * n("offensiveRebounds")
            + 0.3 * n("defensiveRebounds") + n("steals") + 0.7 * n("assists") + 0.7 * n("blocks")
            - 0.4 * n("fouls") - n("turnovers"))


def player_lines(sport, summary, team_id):
    """Who played and how much, from the box score. Returns list of (player_id, name, value)."""
    out = []
    for team in summary.get("boxscore", {}).get("players", []):
        if team["team"]["id"] != team_id:
            continue
        for group in team["statistics"]:
            keys = group.get("keys") or group.get("labels") or []
            for a in group.get("athletes", []):
                stats = dict(zip(keys, a.get("stats", [])))
                pid, name = a.get("athlete", {}).get("id"), a.get("athlete", {}).get("displayName", "")
                if not pid:
                    continue
                if sport == "nba":
                    try:
                        mins = float(stats.get("minutes", 0) or 0)
                    except ValueError:
                        mins = 0.0
                    if mins > 0:
                        out.append((pid, name, (mins, game_score(stats))))
                elif group.get("name") == "passing":
                    att = stats.get("completions/passingAttempts", "0/0").split("/")
                    out.append((pid, name, float(att[1]) if len(att) == 2 and att[1] else 0.0))
    return out


def add_lineups(sport, games):
    """NBA: minutes for every player. NFL/CFB: the main passer (QB)."""
    sums = get_many([summary_url(sport, g["event_id"]) for g in games])
    for g, s in zip(games, sums):
        for side in ("home", "away"):
            lines = player_lines(sport, s or {}, g[side + "_id"])
            if sport == "nba":
                g[side + "_players"] = ";".join(f"{p}:{m:g}:{gs:.1f}" for p, _, (m, gs) in lines)
            else:
                qb = max(lines, key=lambda x: x[2]) if lines else None
                g[side + "_qb"] = qb[0] if qb else ""
                g[side + "_qb_name"] = qb[1] if qb else ""


def main(sports):
    for sport in sports:
        print("fetching", sport)
        games = fetch_games(sport)
        add_closing_spreads(sport, games)
        add_lineups(sport, games)
        cols = sorted({k for g in games for k in g})
        path = os.path.join(DATA, f"games_{sport}.csv")
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, cols)
            w.writeheader()
            w.writerows(games)
        print(sport, len(games), "games ->", path)


if __name__ == "__main__":
    main(sys.argv[1:] or ["nfl", "nba", "cfb"])
