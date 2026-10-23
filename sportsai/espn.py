"""Small helpers for ESPN's free public sports API, with a disk cache."""
import hashlib, json, os, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

SITE = "https://site.api.espn.com/apis/site/v2/sports"
CORE = "https://sports.core.api.espn.com/v2/sports"
LEAGUES = {  # our sport key -> ESPN path
    "nfl": "football/nfl",
    "nba": "basketball/nba",
    "cfb": "football/college-football",
}
CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "cache")


def get_json(url, cache=True, retries=4):
    """Fetch a URL as JSON. Cached copies are reused for past data only."""
    path = os.path.join(CACHE_DIR, hashlib.md5(url.encode()).hexdigest() + ".json")
    if cache and os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "sports-ai/0.1"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            if cache:
                os.makedirs(CACHE_DIR, exist_ok=True)
                with open(path, "w") as f:
                    json.dump(data, f)
            return data
        except Exception as e:
            if attempt == retries - 1:
                raise
            if getattr(e, 'code', None) == 404:
                raise
            time.sleep(2 ** attempt)


def get_many(urls, cache=True, workers=8):
    def one(u):
        try:
            return get_json(u, cache)
        except Exception as e:
            print("failed:", u, e)
            return None
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(one, urls))


def scoreboard_url(sport, yyyymmdd):
    extra = "&groups=80&limit=300" if sport == "cfb" else "&limit=300"
    return f"{SITE}/{LEAGUES[sport]}/scoreboard?dates={yyyymmdd}{extra}"


def summary_url(sport, event_id):
    return f"{SITE}/{LEAGUES[sport]}/summary?event={event_id}"


def odds_url(sport, event_id):
    sport_path, league = LEAGUES[sport].split("/")
    return f"{CORE}/{sport_path}/leagues/{league}/events/{event_id}/competitions/{event_id}/odds"


def teams_url(sport):
    extra = "?groups=80&limit=400" if sport == "cfb" else "?limit=100"
    return f"{SITE}/{LEAGUES[sport]}/teams{extra}"


def roster_url(sport, team_id):
    return f"{SITE}/{LEAGUES[sport]}/teams/{team_id}/roster"
