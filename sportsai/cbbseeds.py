"""Preseason bracketology for college basketball: the Bracket Matrix average projected NCAA seed
(bracketmatrix.com averages dozens of bracketologists). Saved once per season in
data/cbb_seeds/<season start year>.json. Past seasons came from web.archive.org snapshots taken
before the matrix's first in-season update. The site blocks automated downloads, so each new
preseason file is added by hand.
"""
import json, os
from .fetch_history import DATA
from .cbbplayers import team_id

FOLDER = os.path.join(DATA, "cbb_seeds")
ALIASES = {"Miami (Fla.)": "2390", "Miami (FLA.)": "2390", "St. Mary's (CA)": "2608", "Louisiana-Lafayette": "309",
           "McNeese State": "2377", "Arkansas-Little Rock": "2031", "North Carolina State": "152",
           "NC-Wilmington": "350", "Southern": "2582", "Mississippi": "145", "Long Island": "112358",
           "Ohio": "195", "Purdue-Fort Wayne": "2870", "Connecticut": "41", "Montana": "149", "USC": "30",
           "Texas A&M": "245"}


def load(season):
    """{ESPN team id: average projected seed} for the season starting in `season`."""
    try:
        with open(os.path.join(FOLDER, f"{season}.json")) as f:
            seeds = json.load(f)["seeds"]
    except Exception:
        return {}
    out = {}
    for name, seed in seeds.items():
        tid = ALIASES.get(name) or team_id(name)
        if tid:
            out[tid] = seed
    return out


def seed_points(seed):
    """Projected seed -> rough strength in points vs an average Division I team.
    A 1 seed is about +22, a 16 seed (small-conference champ) about +2."""
    return 23.5 - 1.35 * seed
