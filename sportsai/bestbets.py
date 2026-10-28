"""Today's best bets across all sports: one winner, one spread, one parlay, one player prop and one
same-game parlay. Each bet keeps updating until its first game is 25 minutes away, then it is locked
into data/bestbets_log.csv and graded at $20 once its games finish.
"""
import csv, datetime as dt, json, os
from .fetch_history import DATA
from .parlays import decimal, legs_for, best_parlays, results, eastern_today
from . import lock

STAKE = 20.0
KINDS = ("winner", "spread", "parlay", "prop", "sgp")
LOG = os.path.join(DATA, "bestbets_log.csv")
COLS = ["slot", "date", "kind", "bet", "status", "profit", "logged_at"]
MAX_FAV = -300  # skip props priced worse than this
WINNER_MAX = -200  # best winner: a win must pay enough to matter (big favorites lost money)
WINNER_MIN_CHANCE = 0.5  # and it must be more likely than not to win (value alone can pick long underdogs)
CORE = ("prop", "spread", "winner")  # straight bets, the main card
FUN = ("parlay", "sgp")  # long shots, shown separately


def american(dec):
    return round((dec - 1) * 100) if dec >= 2 else round(-100 / (dec - 1))


def eastern_date(iso):
    when = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    try:
        from zoneinfo import ZoneInfo
        return when.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    except Exception:
        return (when - dt.timedelta(hours=5)).date().isoformat()


def short(p):
    return f'{p["away"]} @ {p["home"]}'


def spread_leg(p):
    if p.get("home_cover_prob") is None or p.get("spread") is None:
        return None
    home = p["home_cover_prob"] >= 0.5
    side = "home" if home else "away"
    return dict(type="spread", event_id=p["event_id"], sport=p["sport"], side=side, team=p[side],
                team_name=p[side + "_name"], line=p["spread"] if home else -p["spread"], game=short(p),
                start=p["date"], odds=p.get(side + "_spread_odds") or -110,
                chance=p["home_cover_prob"] if home else 1 - p["home_cover_prob"])


def prop_leg(p):
    bp = p.get("best_prop")
    if not bp:
        return None
    return dict(type="prop", event_id=p["event_id"], sport=p["sport"], pid=bp["pid"], name=bp["name"],
                stat=bp["stat"], label=bp["label"], side=bp["side"], line=bp["line"], game=short(p),
                start=p["date"], odds=int(float(bp["price"])), chance=bp.get("market_prob", bp["prob"]),
                projection=bp.get("projection"))


def make_bet(kind, legs):
    dec = 1.0
    chance = 1.0
    for l in legs:
        dec *= decimal(l["odds"])
        chance *= l["chance"]
    legs = sorted(legs, key=lambda l: l["start"])
    return dict(kind=kind, legs=legs, start=legs[0]["start"], price=american(dec), chance=round(chance, 4),
                payout=round(STAKE * dec, 2), projected_profit=round(chance * STAKE * dec - STAKE, 2))


def has_value(b):
    """True when our chance beats the break-even this price needs (expected profit above $0)."""
    return b["chance"] * b["payout"] > STAKE


def candidates(preds, day, now):
    """Pick the best bet of each kind from games on this Eastern date that haven't started.
    Winner, spread and both parlays must beat their break-even (best value); among those we take the
    most likely. A kind with no such bet is left off the card that day. Props are the exception: their
    chance is DraftKings' own fair odds, which always sit just under break-even, and the 65%+ prop rule
    has been the bet that pays, so the prop keeps its own rule."""
    games = [p for p in preds if eastern_date(p["date"]) == day
             and dt.datetime.fromisoformat(p["date"].replace("Z", "+00:00")) > now]
    out = {}
    # Winner: the most likely winner with a moneyline no worse than -200 that beats its break-even
    wins = []
    for p in games:
        for side in ("home", "away"):
            ml = p.get(side + "_ml")
            if ml is None or ml < WINNER_MAX or p.get("home_win_prob") is None:
                continue
            chance = p["home_win_prob"] if side == "home" else 1 - p["home_win_prob"]
            wins.append(make_bet("winner", [dict(type="ml", event_id=p["event_id"], sport=p["sport"], side=side,
                                                 team=p[side], team_name=p[side + "_name"], game=short(p),
                                                 start=p["date"], odds=ml, chance=chance)]))
    wins = [b for b in wins if has_value(b) and b["chance"] >= WINNER_MIN_CHANCE]
    if wins:
        out["winner"] = max(wins, key=lambda b: b["chance"])
    # Spread: the side most likely to cover, among those that beat their break-even
    # (college spreads are leans, not bets, until the model beats 52.4% there)
    spreads = [make_bet("spread", [l]) for l in (spread_leg(p) for p in games if p["sport"] != "cfb") if l]
    spreads = [b for b in spreads if has_value(b)]
    if spreads:
        out["spread"] = max(spreads, key=lambda b: b["chance"])
    # Parlay: best 2- or 3-game spread parlay across all sports
    pool = [l for l in legs_for(games, now)]
    combos = []
    for size in (2, 3):
        if len(pool) >= size:
            combos += best_parlays(pool, size, n=1)
    if combos:
        top = max(combos, key=lambda c: c["projected_profit"])
        bet = make_bet("parlay", [dict(l, type="spread", team_name=l["team"]) for l in top["legs"]])
        if has_value(bet):
            out["parlay"] = bet
    # Prop: the prop DraftKings thinks is most likely to hit
    props = [l for l in (prop_leg(p) for p in games) if l]
    if props:
        out["prop"] = make_bet("prop", [max(props, key=lambda l: l["chance"])])
    # Same-game parlay: our spread side + that game's best prop, most likely to hit together
    # among those that beat their break-even
    sgps = []
    for p in games:
        s, pr = spread_leg(p), prop_leg(p)
        if s and pr:
            b = make_bet("sgp", [s, pr])
            if has_value(b):
                sgps.append(b)
    if sgps:
        out["sgp"] = max(sgps, key=lambda b: b["chance"])
    return out


# ---------- grading ----------

def grade_leg(l, finals, box):
    """('win'|'loss'|'push'|'void'|None if not final, how much it won or missed by)."""
    if l["event_id"] not in finals:
        return None, None
    hs, as_ = finals[l["event_id"]]
    if l["type"] in ("ml", "spread"):
        margin = (hs - as_) if l["side"] == "home" else (as_ - hs)
        diff = margin + (l["line"] if l["type"] == "spread" else 0)
        return ("win" if diff > 0 else "loss" if diff < 0 else "push"), diff
    rows = box.get(l["event_id"])
    if rows is None:
        return None, None
    r = rows.get(l["pid"])
    if r is None:
        return "void", None
    from .props import stat_value
    val = stat_value(r, l["stat"])
    l["actual"] = val
    diff = (val - l["line"]) if l["side"] == "over" else (l["line"] - val)
    return ("win" if diff > 0 else "loss" if diff < 0 else "push"), diff


def grade(bet, finals, box):
    payout, any_loss = STAKE, False
    for l in bet["legs"]:
        res, diff = grade_leg(l, finals, box)
        if res is None:
            return None
        l["result"], l["by"] = res, diff
        if res == "loss":
            any_loss = True
        elif res == "win":
            payout *= decimal(l["odds"])
    if any_loss:
        return "lost", -STAKE
    if payout == STAKE:
        return "push", 0.0
    return "won", round(payout - STAKE, 2)


def box_scores(player_rows):
    box = {}
    for rows in (player_rows or {}).values():
        for r in rows:
            box.setdefault(r["event_id"], {})[r["pid"]] = r
    return box


def load_log():
    if not os.path.exists(LOG):
        return {}
    with open(LOG) as f:
        return {r["slot"]: r for r in csv.DictReader(f)}


def update(preds, player_rows):
    now = dt.datetime.now(dt.timezone.utc)
    today = eastern_today(now)
    log = load_log()
    # 1) today's card: locked bets stay; the rest update until 25 minutes before their first game
    picks = candidates(preds, today, now)
    drafts = lock.load()
    # safety net first: a bet whose game started with no update inside the lock window is locked as last
    # shown (any date, so an 11 PM game still counts when the next update runs after midnight)
    for key, d in list(drafts.items()):
        if key.startswith("bet|") and lock.missed(drafts, key, now):
            slot = key[4:]
            if slot not in log:
                day, kind = slot.split("|")
                log[slot] = dict(slot=slot, date=day, kind=kind, bet=json.dumps(d["bet"]), status="open", profit="",
                                 logged_at=d["seen"])
            drafts.pop(key)
    card = {}
    for kind in KINDS:
        slot = f"{today}|{kind}"
        key = "bet|" + slot
        if slot in log:
            card[kind] = dict(json.loads(log[slot]["bet"]), status=log[slot]["status"],
                              profit=log[slot]["profit"], locked=True)
            continue
        b = picks.get(kind)
        if b and lock.in_window(b["start"], now):
            log[slot] = dict(slot=slot, date=today, kind=kind, bet=json.dumps(b), status="open", profit="",
                             logged_at=now.isoformat(timespec="minutes"))
            card[kind] = dict(b, status="open", locked=True)
            drafts.pop(key, None)
        elif b:
            card[kind] = dict(b, locked=False)
            drafts[key] = dict(bet=b, start=b["start"], seen=now.isoformat(timespec="minutes"))
        else:
            drafts.pop(key, None)   # no longer shown, so it must not be tracked
    lock.save(drafts, now)
    # 2) nothing left today: preview the next day with games
    preview = None
    if not card:
        later = sorted({eastern_date(p["date"]) for p in preds if eastern_date(p["date"]) > today})
        if later:
            preview = dict(date=later[0], card=candidates(preds, later[0], now))
    # 3) grade finished bets
    finals, box = results(), box_scores(player_rows)
    for slot, r in log.items():
        if r["status"] == "open":
            bet = json.loads(r["bet"])
            g = grade(bet, finals, box)
            if g:
                r.update(status=g[0], profit=f"{g[1]:.2f}", bet=json.dumps(bet))
                if r["date"] == today and r["kind"] in card:
                    card[r["kind"]] = dict(bet, status=g[0], profit=r["profit"], locked=True)
    with open(LOG, "w", newline="") as f:
        w = csv.DictWriter(f, COLS)
        w.writeheader()
        w.writerows(sorted(log.values(), key=lambda r: r["slot"]))
    # 4) record per kind
    rec = {}
    groups = {"all": KINDS, "core": CORE, "fun": FUN, **{k: (k,) for k in KINDS}}
    for kind, members in groups.items():
        rs = [r for r in log.values() if r["status"] in ("won", "lost", "push") and r["kind"] in members]
        won, lost = sum(r["status"] == "won" for r in rs), sum(r["status"] == "lost" for r in rs)
        profit = sum(float(r["profit"]) for r in rs)
        staked = STAKE * (won + lost)
        rec[kind] = dict(won=won, lost=lost, profit=round(profit, 2), roi=round(100 * profit / staked, 1) if staked else None)
    # 5) profit per day, for the money-over-time chart
    days = {}
    for r in log.values():
        if r["status"] in ("won", "lost", "push"):
            days[r["date"]] = days.get(r["date"], 0.0) + float(r["profit"])
    history = [dict(date=d, profit=round(p, 2)) for d, p in sorted(days.items())]
    cdays = {}
    for r in log.values():
        if r["status"] in ("won", "lost", "push") and r["kind"] in CORE:
            cdays[r["date"]] = cdays.get(r["date"], 0.0) + float(r["profit"])
    history_core = [dict(date=d, profit=round(p, 2)) for d, p in sorted(cdays.items())]
    out = dict(updated=now.isoformat(timespec="seconds"), date=today, card=card, preview=preview, record=rec, stake=STAKE,
               history=history, history_core=history_core)
    json.dump(out, open(os.path.join(DATA, "bestbets.json"), "w"), indent=1)
    return out
