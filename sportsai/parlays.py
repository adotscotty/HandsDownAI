"""Suggested 2- and 3-game spread parlays, and a running record assuming a $5 bet on each.

How picks are made: for every upcoming game in the next 24 hours with a betting line, take the side
our main prediction favors against the spread, with its chance of covering. A parlay pays only if
every leg covers, so its chance is the legs' chances multiplied together. Projected return =
chance x payout - stake. We show the three best 2-game and three best 3-game parlays.

Tracking: one card per day. The card is locked 45 minutes before its first game, then every parlay
on it is graded when its games are final, at $5 each. Results: data/parlays_log.csv.
"""
import csv, datetime as dt, itertools, json, os
from .fetch_history import DATA

STAKE = 5.0
LOG = os.path.join(DATA, "parlays_log.csv")
COLS = ["slot", "kind", "rank", "first_start", "legs", "chance", "payout", "projected_profit",
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


def update_parlays(preds):
    """One card per day (US Eastern): the 3 best 2-game and 3-game parlays. The card keeps updating
    until the first of its games is 45 minutes from starting; then it is locked, tracked, and shown
    for the rest of the day."""
    now = dt.datetime.now(dt.timezone.utc)
    today = eastern_today(now)
    log = load_log()
    changed = False

    locked = sorted((r for r in log.values() if r["slot"].startswith(today + "|")), key=lambda r: r["slot"])
    if locked:
        current = {"two": [], "three": []}
        for r in locked:
            current[r["kind"]].append(dict(legs=json.loads(r["legs"]), chance=float(r["chance"]),
                                           payout=float(r["payout"]),
                                           projected_profit=float(r["projected_profit"]), status=r["status"]))
        locked_flag = True
    else:
        legs = legs_for(preds, now)
        current = {"two": best_parlays(legs, 2), "three": best_parlays(legs, 3)}
        starts = [p["legs"][0]["start"] for ps in current.values() for p in ps]
        locked_flag = False
        if starts:
            first = dt.datetime.fromisoformat(min(starts).replace("Z", "+00:00"))
            if first <= now + dt.timedelta(minutes=45):
                for kind, parlays in current.items():
                    for rank, p in enumerate(parlays, 1):
                        slot = f"{today}|{kind}|{rank}"
                        log[slot] = dict(slot=slot, kind=kind, rank=rank, first_start=p["legs"][0]["start"],
                                         legs=json.dumps(p["legs"]), chance=round(p["chance"], 4),
                                         payout=round(p["payout"], 2),
                                         projected_profit=round(p["projected_profit"], 2),
                                         status="open", returned="", profit="",
                                         logged_at=now.isoformat(timespec="minutes"))
                        p["status"] = "open"
                locked_flag = changed = True

    # Grade parlays whose games are all final.
    finals = results()
    for row in log.values():
        if row["status"] == "open":
            grade(row, finals)
            changed = changed or row["status"] != "open"
    if changed or not os.path.exists(LOG):
        with open(LOG, "w", newline="") as f:
            w = csv.DictWriter(f, COLS)
            w.writeheader()
            w.writerows(sorted(log.values(), key=lambda r: r["slot"]))
    if locked_flag:  # show today's results as they come in
        for kind in current:
            for rank, p in enumerate(current[kind], 1):
                r = log.get(f"{today}|{kind}|{rank}")
                if r:
                    p["status"], p["profit"] = r["status"], r["profit"]

    settled = [r for r in log.values() if r["status"] in ("won", "lost")]
    staked = STAKE * len(settled)
    profit = sum(float(r["profit"]) for r in settled)
    summary = dict(bets=len(settled), won=sum(r["status"] == "won" for r in settled),
                   lost=sum(r["status"] == "lost" for r in settled),
                   pending=sum(r["status"] == "open" for r in log.values()),
                   staked=staked, profit=round(profit, 2),
                   roi=round(100 * profit / staked, 1) if staked else None)
    history = [dict(r, legs=json.loads(r["legs"])) for r in sorted(log.values(), key=lambda r: r["slot"], reverse=True)[:60]]
    out = dict(updated=now.isoformat(timespec="seconds"), stake=STAKE, card_date=today, locked=locked_flag,
               current=current, record=summary, history=history)
    json.dump(out, open(os.path.join(DATA, "parlays.json"), "w"), indent=1)
