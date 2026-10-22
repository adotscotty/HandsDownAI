"""Suggested 2- and 3-game spread parlays, and a running record assuming a $5 bet on each.

How picks are made: for every upcoming game in the next 24 hours with a betting line, take the side
our main prediction favors against the spread, with its chance of covering. A parlay pays only if
every leg covers, so its chance is the legs' chances multiplied together. Projected return =
chance x payout - stake. For each sport we show the best 2-game parlay (if it has 4+ games that day)
and the best 3-game parlay (if it has 6+ games), all legs from that sport.

Tracking: one card per sport per day. It is locked 45 minutes before its first game, then every parlay
on it is graded when its games are final, at $5 each. Results: data/parlays_log.csv.
"""
import csv, datetime as dt, itertools, json, os
from .fetch_history import DATA

STAKE = 5.0
LOG = os.path.join(DATA, "parlays_log.csv")
COLS = ["slot", "sport", "kind", "rank", "first_start", "legs", "chance", "payout", "projected_profit",
        "status", "returned", "profit", "logged_at"]


def decimal(american):
    a = float(american)
    return 1 + (a / 100 if a > 0 else 100 / -a)


def legs_for(preds, now):
    out = []
    for p in preds:
        if p.get("home_cover_prob") is None or p.get("spread") is None:
            continue
        start = dt.datetime.fromisoformat(p["date"].replace("Z", "+00:00"))
        if not (now < start <= now + dt.timedelta(hours=24)):
            continue
        home = p["home_cover_prob"] >= 0.5
        side = "home" if home else "away"
        line = p["spread"] if home else -p["spread"]
        out.append(dict(event_id=p["event_id"], sport=p["sport"], side=side, team=p[side],
                        game=f'{p["away"]} @ {p["home"]}', line=line, start=p["date"],
                        odds=p.get(side + "_spread_odds") or -110,
                        chance=p["home_cover_prob"] if home else 1 - p["home_cover_prob"]))
    return out


def best_parlays(legs, size, n=3):
    pool = sorted(legs, key=lambda l: l["chance"] * decimal(l["odds"]), reverse=True)[:14]
    combos = []
    for c in itertools.combinations(pool, size):
        chance = 1.0
        payout = STAKE
        for l in c:
            chance *= l["chance"]
            payout *= decimal(l["odds"])
        combos.append(dict(legs=sorted(c, key=lambda l: l["start"]), chance=chance, payout=payout,
                           projected_profit=chance * payout - STAKE))
    combos.sort(key=lambda x: x["projected_profit"], reverse=True)
    return combos[:n]


def load_log():
    if not os.path.exists(LOG):
        return {}
    with open(LOG) as f:
        return {r["slot"]: r for r in csv.DictReader(f)}


def results():
    """event_id -> (home score, away score) for finished games this season."""
    out = {}
    for sport in ("nfl", "nba", "cfb"):
        path = os.path.join(DATA, f"current_{sport}.csv")
        if os.path.exists(path):
            with open(path) as f:
                for r in csv.DictReader(f):
                    out[r["event_id"]] = (int(r["home_score"]), int(r["away_score"]))
    return out


def grade(row, finals):
    legs = json.loads(row["legs"])
    payout = STAKE
    for l in legs:
        if l["event_id"] not in finals:
            return  # not finished yet
        hs, as_ = finals[l["event_id"]]
        margin = (hs - as_) if l["side"] == "home" else (as_ - hs)
        result = margin + l["line"]
        if result < 0:
            row.update(status="lost", returned=0.0, profit=-STAKE)
            return
        if result > 0:
            payout *= decimal(l["odds"])
        # a push leg drops out of the parlay
    row.update(status="won", returned=round(payout, 2), profit=round(payout - STAKE, 2))


def eastern_today(now):
    try:
        from zoneinfo import ZoneInfo
        return now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    except Exception:
        return (now - dt.timedelta(hours=5)).date().isoformat()


MIN_GAMES = {2: 4, 3: 6}  # a sport needs this many games with lines to get a 2- / 3-game parlay
SPORTS = ("nfl", "nba", "cfb")


def as_row(slot, sport, kind, p, now):
    return dict(slot=slot, sport=sport, kind=kind, rank=1, first_start=p["legs"][0]["start"],
                legs=json.dumps(p["legs"]), chance=round(p["chance"], 4), payout=round(p["payout"], 2),
                projected_profit=round(p["projected_profit"], 2), status="open", returned="", profit="",
                logged_at=now.isoformat(timespec="minutes"))


def from_row(r):
    return dict(legs=json.loads(r["legs"]), chance=float(r["chance"]), payout=float(r["payout"]),
                projected_profit=float(r["projected_profit"]), status=r["status"], profit=r["profit"])


def update_parlays(preds):
    """One card per sport per day (US Eastern): the best 2-game and 3-game parlay, each only when the
    sport has enough games. A sport's card keeps updating until its first game is 45 minutes away;
    then it is locked, tracked at $5 per parlay, and shown for the rest of the day."""
    now = dt.datetime.now(dt.timezone.utc)
    today = eastern_today(now)
    log = load_log()
    changed = False
    legs = legs_for(preds, now)
    current = {}
    for sport in SPORTS:
        card = {}
        locked = {r["kind"]: r for r in log.values() if r["slot"].startswith(f"{today}|{sport}|")}
        if locked:
            for kind, r in locked.items():
                card[kind] = from_row(r)
            card["locked"] = True
        else:
            pool = [l for l in legs if l["sport"] == sport]
            for kind, size in (("two", 2), ("three", 3)):
                if len(pool) >= MIN_GAMES[size]:
                    best = best_parlays(pool, size, n=1)
                    if best:
                        card[kind] = best[0]
            starts = [p["legs"][0]["start"] for k, p in card.items()]
            if starts and dt.datetime.fromisoformat(min(starts).replace("Z", "+00:00")) <= now + dt.timedelta(minutes=45):
                for kind in ("two", "three"):
                    if kind in card:
                        slot = f"{today}|{sport}|{kind}"
                        log[slot] = as_row(slot, sport, kind, card[kind], now)
                        card[kind]["status"] = "open"
                card["locked"] = changed = True
        if card:
            current[sport] = card

    # Grade parlays whose games are all final.
    finals = results()
    for slot, row in log.items():
        if row["status"] == "open":
            grade(row, finals)
            if row["status"] != "open":
                changed = True
                parts = slot.split("|")
                card = current.get(parts[1], {}) if len(parts) == 3 else {}
                if parts[0] == today and parts[2] in card:
                    card[parts[2]].update(status=row["status"], profit=row["profit"])
    if changed or not os.path.exists(LOG):
        with open(LOG, "w", newline="") as f:
            w = csv.DictWriter(f, COLS, extrasaction="ignore")
            w.writeheader()
            w.writerows(sorted(log.values(), key=lambda r: r["slot"]))

    settled = [r for r in log.values() if r["status"] in ("won", "lost")]
    staked = STAKE * len(settled)
    profit = sum(float(r["profit"]) for r in settled)
    summary = dict(bets=len(settled), won=sum(r["status"] == "won" for r in settled),
                   lost=sum(r["status"] == "lost" for r in settled),
                   pending=sum(r["status"] == "open" for r in log.values()),
                   staked=staked, profit=round(profit, 2),
                   roi=round(100 * profit / staked, 1) if staked else None)
    history = [dict(r, legs=json.loads(r["legs"])) for r in sorted(log.values(), key=lambda r: r["slot"], reverse=True)[:60]]
    out = dict(updated=now.isoformat(timespec="seconds"), stake=STAKE, card_date=today,
               current=current, record=summary, history=history)
    json.dump(out, open(os.path.join(DATA, "parlays.json"), "w"), indent=1)
