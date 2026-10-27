"""When picks lock, and a safety net so a pick is never lost.

Picks keep updating until their first game is LOCK_MINUTES away (after NBA starting lineups, which
are due 30 minutes before tip). Every unlocked pick is also saved as a draft in data/drafts.json.
If no update happens to run inside the lock window (GitHub sometimes runs late), the last draft
saved before the game is the one that gets locked.
"""
import datetime as dt, json, os
from .fetch_history import DATA

LOCK_MINUTES = 25
PATH = os.path.join(DATA, "drafts.json")


def when(iso):
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))


def in_window(start_iso, now):
    return when(start_iso) <= now + dt.timedelta(minutes=LOCK_MINUTES)


def load():
    try:
        return json.load(open(PATH))
    except Exception:
        return {}


def save(drafts, now):
    # drop drafts for games more than 2 days old
    keep = {k: v for k, v in drafts.items() if when(v["start"]) > now - dt.timedelta(days=2)}
    with open(PATH, "w") as f:
        json.dump(keep, f, indent=1, sort_keys=True)


def missed(drafts, key, now):
    """The draft to lock when its game already started without any update inside the lock window."""
    d = drafts.get(key)
    if d and when(d["start"]) <= now:
        return d
    return None
