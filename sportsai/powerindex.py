"""Save ESPN's power index (NBA BPI, NFL and college FPI) once a day, so we can later test
whether mixing it into our ratings helps. It does not change any prediction."""
import datetime as dt, json, os, re
from .espn import get_json

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "powerindex")
PATHS = {"nba": ("basketball", "nba", "bpi"), "nfl": ("football", "nfl", "fpi"), "cfb": ("football", "college-football", "fpi")}


def main():
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    os.makedirs(DATA, exist_ok=True)
    for sport, (sp, lg, stat) in PATHS.items():
        path = os.path.join(DATA, f"{sport}-{today}.json")
        if os.path.exists(path):
            continue
        try:
            season = dt.date.today().year + (1 if sport == "nba" and dt.date.today().month >= 8 else 0)
            d = get_json(f"https://sports.core.api.espn.com/v2/sports/{sp}/leagues/{lg}/seasons/{season}/powerindex?limit=400", cache=False)
            out = {}
            for it in d.get("items", []):
                tid = re.search(r"teams/(\d+)", it["team"]["$ref"]).group(1)
                v = [s["value"] for s in (it.get("stats") or it.get("predictives") or []) if s["name"] == stat]
                if v:
                    out[tid] = v[0]
            if out:
                json.dump(dict(updated=(d["items"][0].get("lastUpdated")), ratings=out), open(path, "w"))
                print(sport, len(out), "teams saved")
        except Exception as e:  # never block the update
            print(sport, "power index not saved:", e)


if __name__ == "__main__":
    main()
