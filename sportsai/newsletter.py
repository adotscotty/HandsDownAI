"""Writes "HandsDown AI Weekly" from the site's real results and sends it through Buttondown.

Runs Thursday at 2 AM Eastern (see .github/workflows/newsletter.yml):
  python -m sportsai.newsletter            # write the issue; send it if BUTTONDOWN_API_KEY is set
  python -m sportsai.newsletter --draft    # save it in Buttondown as a draft instead of sending
  python -m sportsai.newsletter --preview  # just print it

The week covered is the seven Eastern days ending the day before the run (Thursday to Wednesday).
Each sent issue is saved to data/newsletter/ so the same week is never sent twice.
"""
import csv, datetime as dt, json, os, sys, urllib.request
from zoneinfo import ZoneInfo
from .fetch_history import DATA
from .build_site import leg_txt, line_txt

ET = ZoneInfo("America/New_York")
SITE = "https://adotscotty.github.io/HandsDownAI/"
SUBSCRIBE = "https://buttondown.com/handsdownai"
STAKE = 20.0
FIRST_ISSUE_DATE = dt.date(2026, 10, 22)            # issue #1 went out the week of Oct 22
KIND = {"winner": "Winner", "spread": "Spread", "parlay": "Parlay", "prop": "Player prop", "sgp": "Same-game parlay"}
SPORT = {"nfl": "NFL", "nba": "NBA", "cfb": "College"}
OUT = os.path.join(DATA, "newsletter")


def money(v):
    return ("-" if v < 0 else "+") + f"${abs(v):,.2f}"


def american(p):
    p = int(p)
    return f"+{p}" if p > 0 else str(p)


def decimal(p):
    p = float(p)
    return 1 + (p / 100 if p > 0 else 100 / -p)


def et_when(iso):
    t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ET)
    return t.strftime("%a %-I:%M %p")


def fetch_json(name):
    """The site's current data (built every 15 minutes)."""
    local = os.path.join(os.path.dirname(DATA), "site", "data", name)
    if os.path.exists(local):
        return json.load(open(local))
    with urllib.request.urlopen(SITE + "data/" + name, timeout=30) as r:
        return json.load(r)


def load_bets():
    path = os.path.join(DATA, "bestbets_log.csv")
    if not os.path.exists(path):
        return []
    out = []
    for r in csv.DictReader(open(path)):
        if r["status"] in ("won", "lost", "push"):
            b = json.loads(r["bet"])
            out.append(dict(b, date=r["date"], kind=r["kind"], status=r["status"], profit=float(r["profit"])))
    return out


def record(bets):
    w = sum(b["status"] == "won" for b in bets); l = sum(b["status"] == "lost" for b in bets)
    p = sum(b["profit"] for b in bets)
    return w, l, p


def bet_line(b):
    legs = " + ".join(leg_txt(l) for l in b["legs"])
    res = {"won": "Won", "lost": "Lost", "push": "Push"}[b["status"]]
    return f'**{KIND[b["kind"]]}:** {legs}. {res} ({money(b["profit"])})'


def miss_by(b):
    """How close a losing bet came: the smallest miss among its losing legs."""
    misses = [abs(l["by"]) for l in b["legs"] if l.get("result") == "loss" and l.get("by") is not None]
    return min(misses) if misses else 99


def write(today=None):
    today = today or dt.datetime.now(ET).date()
    end = today - dt.timedelta(days=1)                  # Wednesday
    start = end - dt.timedelta(days=6)                  # the Thursday before
    number = (today - FIRST_ISSUE_DATE).days // 7 + 1
    bets = load_bets()
    week = [b for b in bets if start.isoformat() <= b["date"] <= end.isoformat()]
    season = bets
    w, l, p = record(week)
    sw, sl, sp = record(season)
    span = f'{start.strftime("%b %-d")} to {end.strftime("%b %-d")}'

    md = []
    title = (f"HandsDown AI Weekly #{number}: {w}-{l}, {money(p)} this week" if week
             else f"HandsDown AI Weekly #{number}: this weekend's best bets")
    md.append("Every week: how our best bets did, the plays we like this weekend, and a parlay of the week. "
              f"Every pick is tracked at ${STAKE:.0f} a bet, wins and losses, at [HandsDown AI]({SITE}).")

    # --- scorecard
    md.append(f"## Scorecard: {w}-{l} ({span})" if week else "## Scorecard")
    if week:
        staked = STAKE * (w + l)
        md.append(f"Our best bets went {w}-{l} this week, {'up' if p >= 0 else 'down'} ${abs(p):,.2f} "
                  f"betting ${STAKE:.0f} on each" + (f" ({100 * p / staked:+.0f}%)." if staked else "."))
        lines = []
        for k in KIND:
            kb = [b for b in week if b["kind"] == k]
            if kb:
                kw, kl, kp = record(kb)
                lines.append(f"- **{KIND[k]}:** {kw}-{kl}, {money(kp)}")
        md.append("\n".join(lines))
        won = [b for b in week if b["status"] == "won"]
        lost = [b for b in week if b["status"] == "lost"]
        if won:
            bw = max(won, key=lambda b: b["profit"])
            md.append(f'**Best win:** {" + ".join(leg_txt(x) for x in bw["legs"])} ({KIND[bw["kind"]].lower()}), '
                      f'{money(bw["profit"])} on ${STAKE:.0f}.')
        if lost:
            bb = min(lost, key=miss_by)
            m = miss_by(bb)
            how = f"missed by {m:g}" if m < 99 else "lost"
            md.append(f'**Bad beat:** {" + ".join(leg_txt(x) for x in bb["legs"])} ({KIND[bb["kind"]].lower()}) {how}.')
    else:
        md.append("No best bets were graded this week.")

    # --- this weekend
    preds = fetch_json("predictions.json")
    horizon = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=5)
    games = [g for g in preds.get("games", [])
             if dt.datetime.fromisoformat(g["date"].replace("Z", "+00:00")) <= horizon]
    plays = []
    # three most likely winners (no worse than -300), spread across sports where possible
    favs = []
    for g in games:
        for side in ("home", "away"):
            ml = g.get(side + "_ml")
            if ml is None or ml < -300:
                continue
            ch = g["home_win_prob"] if side == "home" else 1 - g["home_win_prob"]
            favs.append((ch, side, g))
    favs.sort(key=lambda t: -t[0])
    used, picked = set(), []
    for ch, side, g in favs:
        if g["event_id"] in used or (len(picked) < 2 and g["sport"] in {x[2]["sport"] for x in picked}):
            continue
        picked.append((ch, side, g)); used.add(g["event_id"])
        if len(picked) == 3:
            break
    for ch, side, g in picked:
        plays.append(f'**{g[side + "_name"]} to win ({american(g[side + "_ml"])}):** {SPORT[g["sport"]]}, '
                     f'{g["away_name"]} at {g["home_name"]}, {et_when(g["date"])}. We give them a {ch:.0%} chance.')
    # two biggest disagreements with the spread
    edges = sorted([g for g in games if g.get("edge_vs_spread") is not None and g["event_id"] not in used],
                   key=lambda g: -abs(g["edge_vs_spread"]))

    def spread_side(g):
        home = g["edge_vs_spread"] > 0
        side = "home" if home else "away"
        ln = g["spread"] if home else -g["spread"]
        odds = g.get(side + "_spread_odds") or -110
        return side, ln, odds

    for g in edges[:2]:
        side, ln, odds = spread_side(g)
        vegas = g["home_name"] if g["spread"] < 0 else g["away_name"]
        mm = g.get("model_home_margin")
        if mm is None:
            mm = g["predicted_home_margin"]
        model = g["home_name"] if mm >= 0 else g["away_name"]
        why = (f'Vegas has {vegas} by {abs(g["spread"]):g}; our model alone has {model} by {abs(mm):.1f}.'
               if g["spread"] else f'Vegas calls it even; our model alone has {model} by {abs(mm):.1f}.')
        plays.append(f'**{g[side + "_name"]} {line_txt(ln)} ({american(odds)}):** {SPORT[g["sport"]]}, '
                     f'{g["away_name"]} at {g["home_name"]}, {et_when(g["date"])}. {why}')
    md.append("## This weekend's top plays")
    if plays:
        md.append("Our most likely winners and the spots where we disagree most with the line. All times Eastern.")
        md.append("\n".join(f"{i}. {t}" for i, t in enumerate(plays, 1)))
    else:
        md.append("No games with betting lines yet. Check the site for picks as lines come out.")

    # --- parlay of the week: the three biggest disagreements, one per game
    legs = edges[:3]
    if len(legs) == 3:
        dec = 1.0
        rows = []
        for g in legs:
            side, ln, odds = spread_side(g)
            dec *= decimal(odds)
            rows.append(f'{g[side + "_name"]} {line_txt(ln)} ({SPORT[g["sport"]]}, {et_when(g["date"])}, {american(odds)})')
        price = round((dec - 1) * 100) if dec >= 2 else round(-100 / (dec - 1))
        md.append(f"## Parlay of the week: {american(price)}")
        md.append(f"A ${STAKE:.0f} bet pays ${STAKE * dec:,.2f} if all three cover. These are the three games where "
                  "our model disagrees most with the betting line.")
        md.append("\n".join(f"{i}. {t}" for i, t in enumerate(rows, 1)))

    # --- season record and footer
    md.append("## Best bets record")
    if season:
        md.append(f"Season so far: {sw}-{sl}, {'up' if sp >= 0 else 'down'} ${abs(sp):,.2f} at ${STAKE:.0f} a bet"
                  + (f" ({100 * sp / (STAKE * (sw + sl)):+.0f}%)." if sw + sl else "."))
    md.append(f"Live picks, live scores and every past bet: [HandsDown AI]({SITE}). "
              f"Know someone who'd like this? [Send them the sign-up link]({SUBSCRIBE}).")
    md.append("*For entertainment only, not betting advice. Bet only what you can afford to lose. "
              "If gambling stops being fun, call 1-800-GAMBLER.*")
    return number, title, "\n\n".join(md)


def send(title, body, draft=False):
    key = os.environ.get("BUTTONDOWN_API_KEY")
    if not key:
        print("No BUTTONDOWN_API_KEY set, so nothing was sent.")
        return False
    payload = {"subject": title, "body": "<!-- buttondown-editor-mode: plaintext -->\n" + body}
    if draft:
        payload["status"] = "draft"
    else:
        when = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)
        payload.update(status="scheduled", publish_date=when.isoformat(timespec="seconds"))
    req = urllib.request.Request("https://api.buttondown.com/v1/emails", data=json.dumps(payload).encode(),
                                 headers={"Authorization": "Token " + key, "Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.load(r)
        print("Buttondown:", res.get("status"), res.get("id"))
        return True
    except urllib.error.HTTPError as e:
        print("Buttondown refused it:", e.code, e.read().decode()[:500])
        raise


def main():
    args = set(sys.argv[1:])
    number, title, body = write()
    print(title + "\n\n" + body)
    if "--preview" in args:
        return
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"issue-{number:03d}.md")
    draft = "--draft" in args
    if os.path.exists(path) and not draft:
        print(f"Issue #{number} was already sent; not sending it twice.")
        return
    if send(title, body, draft=draft) and not draft:
        open(path, "w").write(f"# {title}\n\n{body}\n")


if __name__ == "__main__":
    main()
