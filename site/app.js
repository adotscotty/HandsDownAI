// HandsDown AI: renders the data/*.json files the updater writes every 15 minutes.
const SPORT = { nfl: "NFL", nba: "NBA", cfb: "College" };
const NAMES = { winner: "Best winner", spread: "Best spread", parlay: "Best parlay", prop: "Best player prop", sgp: "Best same-game parlay" };
const WHY = { winner: "Most likely team to win outright", spread: "Most likely to cover the spread", parlay: "Best value 2- or 3-game parlay",
  prop: "DraftKings' most likely player prop", sgp: "Our spread pick plus a player prop, same game" };
const KINDS = ["winner", "spread", "parlay", "prop", "sgp"];
const VIEWS = ["home", "games", "today", "yesterday", "record"];

const S = { sport: "all", edgeOnly: false, stake: 20, base: 20, preds: null, track: null, parlays: null, props: null, best: null, daily: null };
try { S.stake = +localStorage.getItem("hd-stake") || 20; } catch (e) {}

// ---------- helpers ----------
function h(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k === "class") e.className = v; else if (k === "text") e.textContent = v; else e.setAttribute(k, v);
  }
  for (const k of kids) if (k != null && k !== false) e.append(k);
  return e;
}
const money = v => (v < 0 ? "-$" : "$") + Math.abs(v).toFixed(2);
const signed = v => (v > 0 ? "+" : v < 0 ? "-" : "") + "$" + Math.abs(v).toFixed(2);
const scale = v => (+v || 0) * S.stake / S.base;           // data is stored at $20 a bet
const price = p => (+p > 0 ? "+" : "") + (+p);
const line = l => l === 0 ? "PK" : (l > 0 ? "+" : "") + l;
const when = s => new Date(s).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" });
const dayName = d => new Date(d + "T12:00").toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" });
const american = dec => dec >= 2 ? Math.round((dec - 1) * 100) : Math.round(-100 / (dec - 1));
const wl = (w, l, p) => `${w}-${l}${p ? "-" + p : ""}`;
const cls = v => v > 0 ? "w" : v < 0 ? "l" : "";
const legText = l => l.type === "prop" ? `${l.name} ${l.side} ${l.line} ${l.label}`
  : l.type === "ml" ? `${l.team_name || l.team} to win` : `${l.team} ${line(l.line)}`;
const sportOk = s => S.sport === "all" || S.sport === s;

// ---------- tickets ----------
// b: { legs, price?, chance, payout (at $20), status, profit, locked }
function ticket(title, why, b, lead) {
  const t = h("article", { class: "ticket rise" + (lead ? " lead" : "") });
  const head = h("div", {}, h("h3", { text: title }), why ? h("p", { class: "why", text: why }) : null);
  const legs = h("div", {});
  for (const l of b.legs) {
    const r = l.result;
    const res = r ? h("strong", { class: r === "win" ? "res-w" : r === "loss" ? "res-l" : "",
      text: ` · ${r === "win" ? "hit" : r === "loss" ? "missed" : r}${l.type === "prop" && l.actual != null ? " (" + l.actual + ")" : ""}` }) : null;
    const live = !r ? liveLeg(l) : null;
    const odds = l.odds != null ? ` · ${price(l.odds)}` : l.chance != null ? ` · ${Math.round(l.chance * 100)}% to cover` : "";
    legs.append(h("div", { class: "leg" }, h("b", { text: legText(l) }),
      h("span", { text: `${SPORT[l.sport] || ""} · ${l.game} · ${when(l.start)}${odds}` }), res, live));
  }
  const pr = b.price != null ? b.price : american(b.payout / S.base);
  const figs = h("div", { class: "figs" },
    h("div", {}, h("small", { text: "Price" }), h("strong", { text: price(pr) })),
    h("div", {}, h("small", { text: "Chance" }), h("strong", { text: Math.round(b.chance * 100) + "%" })),
    h("div", { class: "pay" }, h("small", { text: `Wins on $${S.stake}` }), h("strong", { text: "+" + money(scale(b.payout - S.base)) })));
  if (b.status === "won") t.append(h("div", { class: "stamp w", text: "Won" }));
  else if (b.status === "lost") t.append(h("div", { class: "stamp l", text: "Lost" }));
  else if (b.status === "push") t.append(h("div", { class: "stamp p", text: "Push" }));
  const stateTxt = b.status === "won" ? `Won ${money(scale(b.profit))} on $${S.stake}` : b.status === "lost" ? `Lost $${S.stake}`
    : b.status === "push" ? "Push, money back" : b.legs.some(l => !l.result && legNow(l)) ? "In play · live scores update every minute"
    : b.locked ? "Locked · waiting on the game" : "Can still change until 45 min before start";
  const st = h("p", { class: "state", text: stateTxt });
  if (lead) t.append(h("div", {}, head, legs, st), figs); else t.append(head, legs, figs, st);
  return t;
}
const betTicket = (kind, b, lead) => ticket((lead ? "Top pick · " : "") + NAMES[kind], WHY[kind], b, lead);

function pairs(items) {
  const wrap = h("div", {});
  for (let i = 0; i < items.length; i += 2) wrap.append(h("div", { class: "pair" }, items[i], items[i + 1] || null));
  return wrap;
}

// ---------- shared blocks ----------
function totalBlock(r, since) {
  return h("div", { class: "total rise" },
    h("div", { class: "big", text: signed(scale(r.profit)) }),
    h("p", { text: `${wl(r.won, r.lost)} ${since}, betting $${S.stake} on every best bet.` + (r.roi != null ? ` Return ${r.roi}%.` : "") }));
}

function recordRows(rows) {
  const tb = h("tbody");
  for (const [n, x] of rows) {
    if (!x) continue;
    tb.append(h("tr", {}, h("td", { text: n }), h("td", { class: "r", text: wl(x.won ?? x.wins, x.lost ?? x.losses, x.pushes) }),
      h("td", { class: "r " + cls(x.profit), text: money(scale(x.profit)) }), h("td", { class: "r", text: x.roi == null ? "–" : x.roi + "%" })));
  }
  return h("table", { class: "rise" }, h("thead", {}, h("tr", {}, h("th", { text: "Bet" }), h("th", { class: "r", text: "Won-lost" }),
    h("th", { class: "r", text: "Profit" }), h("th", { class: "r", text: "Return" }))), tb);
}

function chart(history) {
  const box = h("div", { class: "chart rise" });
  if (!history || !history.length) { box.append(h("p", { text: "The money chart starts after the first graded day." })); return box; }
  let run = 0;
  const pts = [{ date: null, v: 0 }, ...history.map(d => ({ date: d.date, v: (run += scale(d.profit)) }))];
  const W = 640, H = 260, P = 34;
  const vs = pts.map(p => p.v), lo = Math.min(0, ...vs), hi = Math.max(0, ...vs), span = hi - lo || 1;
  const x = i => P + (W - 2 * P) * (pts.length === 1 ? 0 : i / (pts.length - 1));
  const y = v => H - P - (H - 2 * P) * (v - lo) / span;
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `Best bets profit over time: ${signed(run)} at $${S.stake} a bet`);
  const add = (tag, a, text) => { const e = document.createElementNS(ns, tag); for (const k in a) e.setAttribute(k, a[k]); if (text) e.textContent = text; svg.append(e); };
  add("rect", { x: P, y: y(0) - 1, width: W - 2 * P, height: 2, fill: "#2b271f" });
  add("text", { x: P, y: y(0) - 8, fill: "#b9b09c", "font-size": 14, "font-family": "Inter, sans-serif" }, "$0");
  add("polyline", { points: pts.map((p, i) => `${x(i)},${y(p.v)}`).join(" "), fill: "none", stroke: "#d4a73a", "stroke-width": 4, "stroke-linejoin": "round", "stroke-linecap": "round" });
  const last = pts[pts.length - 1];
  add("circle", { cx: x(pts.length - 1), cy: y(last.v), r: 7, fill: "#d4a73a" });
  add("text", { x: x(pts.length - 1) - 10, y: y(last.v) + (last.v >= 0 ? -16 : 28), fill: "#f2ead7", "font-size": 20, "font-weight": 800,
    "text-anchor": "end", "font-family": "Inter, sans-serif" }, signed(last.v));
  box.append(svg, h("p", { text: `Running profit from best bets since ${dayName(history[0].date).split(",").slice(0, 2).join(",")}, at $${S.stake} a bet.` }));
  return box;
}

// ---------- Best bets ----------
function renderHome() {
  const box = document.getElementById("bestbets"); box.replaceChildren();
  const B = S.best;
  if (!B) { box.append(h("p", { class: "empty", text: "Best bets will appear after the next update." })); return; }
  let card = B.card, title = "Today's best bets";
  if ((!card || !Object.keys(card).length) && B.preview) { card = B.preview.card; title = "Next up: " + dayName(B.preview.date).split(",")[0]; }
  document.getElementById("homeTitle").textContent = title;
  const kinds = KINDS.filter(k => card && card[k]);
  if (!kinds.length) box.append(h("p", { class: "empty", text: "No picks yet today. Check back after the next update." }));
  else {
    const top = kinds.reduce((a, k) => card[k].chance > card[a].chance ? k : a, kinds[0]);
    box.append(betTicket(top, card[top], true));
    const rest = pairs(kinds.filter(k => k !== top).map(k => betTicket(k, card[k])));
    rest.style.marginTop = "20px";
    box.append(rest);
  }
  // yesterday trio
  const yb = document.getElementById("homeYest"); yb.replaceChildren();
  const y = S.daily && S.daily.yesterday;
  if (y && y.summary && y.summary.games) {
    const s = y.summary, bb = s.best_bets, prof = scale((y.best_bets || []).reduce((a, x) => a + (+x.profit || 0), 0));
    yb.append(
      h("div", { class: "rise" }, h("p", { class: "lbl", text: "Best bets" }), h("div", { class: "big " + cls(prof || 0), text: wl(bb[0], bb[1]) }),
        h("p", { text: `${prof >= 0 ? "Up" : "Down"} ${money(Math.abs(prof))} at $${S.stake} a bet. Winners ${wl(...s.winners)}, spreads ${wl(...s.ats)}.` })),
      y.best_win ? h("div", { class: "rise" }, h("p", { class: "lbl", text: "Best win" }), h("p", { text: y.best_win.title }), h("p", { text: scaleDetail(y.best_win.detail) })) : null,
      y.bad_beat ? h("div", { class: "rise" }, h("p", { class: "lbl", text: "Bad beat" }), h("p", { text: y.bad_beat.title }), h("p", { text: y.bad_beat.detail }),
        h("p", {}, h("a", { href: "#yesterday", text: "Full recap →" }))) : null);
  } else yb.append(h("p", { class: "empty", text: "No games yesterday." }));
  // record
  const rb = document.getElementById("homeRecord"); rb.replaceChildren();
  const r = B.record;
  rb.append(totalBlock(r.all, "since Oct 22"),
    recordRows([["Winner", r.winner], ["Spread", r.spread], ["Parlay", r.parlay], ["Prop", r.prop], ["Same-game parlay", r.sgp]]));
}
// "won $32.52 on $20" -> scaled to the visitor's stake
function scaleDetail(t) {
  const m = /won \$([\d.]+) on \$\d+/.exec(t || "");
  return m ? t.replace(m[0], `won ${money(scale(+m[1]))} on $${S.stake}`) : t;
}

// ---------- Games ----------
// Plain-English "Why this pick?": the pieces that add up to our model's number, then how Vegas changes it
function whyBox(g) {
  const w = g.why; if (!w) return null;
  const H = g.home_name, A = g.away_name, pts = x => `${Math.abs(x).toFixed(1)} pt${Math.abs(x) >= 0.95 && Math.abs(x) < 1.05 ? "" : "s"}`;
  const toward = x => x > 0 ? H : A, items = [];
  const gap = w.home_rating - w.away_rating;
  items.push(Math.abs(gap) < 0.5 ? `Team strength: our ratings have these teams about even.`
    : `Team strength: our ratings have the ${toward(gap)} ${pts(gap)} better than the ${gap > 0 ? A : H} on a neutral field.`);
  if (w.espn_adj) items.push(`ESPN check: ESPN's power index sees a ${Math.abs(w.espn_gap).toFixed(1)}-pt gap${Math.abs(w.espn_gap) >= 0.5 ? ` favoring the ${toward(w.espn_gap)}` : ""}, far from ours, so we moved ${pts(w.espn_adj)} toward the ${toward(w.espn_adj)}.`);
  items.push(w.home_field ? `Home ${g.sport === "nba" ? "court" : "field"}: worth ${pts(w.home_field)} to the ${H}.` : `Neutral site, so no home edge.`);
  if (Math.abs(g.injury_adjustment) >= 0.1) items.push(`Injuries: move it ${pts(g.injury_adjustment)} toward the ${toward(g.injury_adjustment)}.`);
  if (Math.abs(w.lineup) >= 0.5) items.push(`Who's expected to play: moves it ${pts(w.lineup)} toward the ${toward(w.lineup)}.`);
  if (Math.abs(g.rest_adjustment) >= 0.1) items.push(`Rest: moves it ${pts(g.rest_adjustment)} toward the ${toward(g.rest_adjustment)}.`);
  if (Math.abs(w.late) >= 0.1) items.push(`Late-season tanking: moves it ${pts(w.late)} toward the ${toward(w.late)}.`);
  const rec = (n, f) => f && (f.w + f.l) ? `${n} ${f.w}-${f.l}` + (f.last5.length ? ` (last ${f.last5.length}: ${f.last5.map(x => (x > 0 ? "W" : "L") + Math.abs(x)).join(", ")})` : "") : null;
  const form = [rec(A, w.away_form), rec(H, w.home_form)].filter(Boolean);
  if (form.length) items.push(`This season: ${form.join("; ")}.`);
  const mm = g.model_home_margin;
  items.push(`Our model adds that up to the ${mm >= 0 ? H : A} by ${Math.abs(mm).toFixed(1)}.`);
  if (g.spread != null) {
    const vf = -g.spread, pm = g.predicted_home_margin;
    items.push(`Vegas has ${Math.abs(vf) < 0.25 ? "it a pick'em" : `the ${vf > 0 ? H : A} by ${Math.abs(vf).toFixed(1)}`}. Vegas is usually sharper, so our prediction is 60% Vegas and 40% our model: the ${pm >= 0 ? H : A} by ${Math.abs(pm).toFixed(1)}.`);
    const d = pm + g.spread;
    if (Math.abs(d) >= 0.05) items.push(`That's ${d > 0 ? "a bit more" : "a bit less"} than Vegas gives the ${H}, so our spread pick is the ${d > 0 ? H : A}. Our chance it covers: ${Math.round(100 * Math.max(g.home_cover_prob, 1 - g.home_cover_prob))}%.`);
  }
  return h("details", { class: "why" }, h("summary", { text: "Why this pick?" }), h("ul", {}, ...items.map(t => h("li", { text: t }))));
}

function gameRow(g) {
  const homePct = Math.round(g.home_win_prob * 100), awayPct = 100 - homePct;
  const favHome = g.predicted_home_margin >= 0;
  const favName = favHome ? g.home_name : g.away_name;
  const e = g.edge_vs_spread, big = e != null && Math.abs(e) >= 4 && Math.abs(e) < 7;
  const team = (logo, name, pct, fav) => h("div", { class: "team" + (fav ? " fav" : "") },
    logo ? h("img", { src: logo, alt: "", loading: "lazy", width: 30, height: 30 }) : null,
    h("span", { text: name }), h("span", { class: "pct", text: pct + "%" }));
  const bar = h("div", { class: "wp", title: `Win chance: ${g.away} ${awayPct}%, ${g.home} ${homePct}%` });
  bar.append(h("span", { style: `width:${awayPct}%;background:${awayPct >= 50 ? "var(--gold)" : "var(--surface-3)"}` }),
             h("span", { style: `width:${homePct}%;background:${homePct > 50 ? "var(--gold)" : "#3a3427"}` }));
  // The spread pick we grade in the Record tab: our prediction against the line
  let pickTxt = null, modelTxt = null;
  if (g.spread != null) {
    const d = g.predicted_home_margin + g.spread;
    pickTxt = Math.abs(d) < 0.05 ? "No spread pick: our prediction lands right on the line"
      : `Our spread pick: ${d > 0 ? `${g.home} ${line(g.spread)}` : `${g.away} ${line(-g.spread)}`}`;
  }
  if (e != null && g.model_home_margin != null) {
    const side = e > 0 ? `${g.home} ${line(g.spread)}` : `${g.away} ${line(-g.spread)}`;
    modelTxt = `Model alone (before blending with Vegas): ${g.model_home_margin >= 0 ? g.home_name : g.away_name} by ${Math.abs(g.model_home_margin).toFixed(1)}` +
      (Math.abs(e) < 0.5 ? ", about the same as the line." : `, so it disagrees with the line by ${Math.abs(e).toFixed(1)} pts` +
        (big ? ". That makes this a gold-edge pick, tracked in the Record." : "."));
  }
  const inj = [...(g.away_injuries?.key_injuries || []).map(i => ({ ...i, t: g.away })), ...(g.home_injuries?.key_injuries || []).map(i => ({ ...i, t: g.home }))];
  const bp = g.best_prop;
  const extra = h("div", { class: "extra" },
    bp ? h("p", {}, h("b", { text: "Best prop: " }), `${bp.name} ${bp.side} ${bp.line} ${bp.label} (${price(bp.price)}), DraftKings ${Math.round(bp.market_prob * 100)}% likely, our projection ${(+bp.projection).toFixed(1)}`) : null,
    inj.length ? h("p", {}, h("b", { text: "Injuries counted: " }), inj.map(i => `${i.name} (${i.t}, ${i.status})`).join(", ") +
      (g.injury_adjustment ? `. Moves our line ${Math.abs(g.injury_adjustment).toFixed(1)} pts.` : "")) : null,
    modelTxt ? h("p", { text: modelTxt }) : null,
    whyBox(g));
  return h("article", { class: "game rise" + (big ? " edge" : "") },
    h("div", {}, h("p", { class: "when", text: `${SPORT[g.sport]} · ${when(g.date)}` }),
      h("div", { class: "teams" }, team(g.away_logo, g.away_name, awayPct, !favHome), team(g.home_logo, (g.neutral ? "vs " : "@ ") + g.home_name, homePct, favHome)), bar),
    h("div", { class: "call" }, h("small", { text: "Our prediction" }), h("strong", { text: `${favName} by ${Math.abs(g.predicted_home_margin).toFixed(1)}` }),
      h("small", { text: "Betting spread" }), h("strong", { text: g.odds_detail || (g.spread == null ? "No line yet" : `${g.home} ${line(g.spread)}`) }),
      pickTxt ? h("p", { class: "edge-txt", text: pickTxt }) : null),
    extra);
}

function renderGames() {
  const box = document.getElementById("gamesList"); box.replaceChildren();
  let games = (S.preds?.games || []).filter(g => sportOk(g.sport));
  if (S.edgeOnly) games = games.filter(g => g.edge_vs_spread != null && Math.abs(g.edge_vs_spread) >= 4 && Math.abs(g.edge_vs_spread) < 7);
  if (!games.length) { box.append(h("p", { class: "empty", text: "No games to show right now." })); return; }
  let day = null, list = null;
  for (const g of games) {
    const d = new Date(g.date).toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" });
    if (d !== day) { day = d; box.append(h("h3", { class: "day-h", text: d })); list = h("div", { class: "games" }); box.append(list); }
    list.append(gameRow(g));
  }
}

function renderParlays() {
  const box = document.getElementById("parlays"), rec = document.getElementById("parlayRecord");
  box.replaceChildren(); rec.replaceChildren();
  const P = S.parlays;
  if (!P) { box.append(h("p", { class: "empty", text: "Parlays will appear after the next update." })); return; }
  const items = [];
  for (const sp of ["nfl", "nba", "cfb"]) {
    if (!sportOk(sp)) continue;
    const c = (P.current || {})[sp]; if (!c) continue;
    for (const [k, n] of [["two", "2-game"], ["three", "3-game"]]) if (c[k]) {
      const p = c[k];
      items.push(ticket(`${SPORT[sp]} ${n} parlay`, c.locked ? "Locked for today" : `Projected ${signed(scale(p.projected_profit))} on $${S.stake}`,
        { ...p, legs: p.legs.map(l => ({ ...l, type: "spread" })), locked: c.locked }));
    }
  }
  box.append(items.length ? pairs(items) : h("p", { class: "empty", text: "No parlays today. A sport needs at least 4 games with lines in the next 24 hours for a 2-game parlay, and 6 for a 3-game parlay." }));
  const r = P.record;
  rec.style.marginTop = "28px";
  rec.append(recordRows([["All parlays", r], ["2-game", (r.by_kind || {}).two], ["3-game", (r.by_kind || {}).three]]));
  if (P.history && P.history.length) {
    const tb = h("tbody");
    for (const x of P.history) tb.append(h("tr", {}, h("td", { text: x.legs.map(l => `${l.team} ${line(l.line)}`).join(", ") }),
      h("td", { class: "r " + (x.status === "won" ? "w" : x.status === "lost" ? "l" : ""),
        text: x.status === "open" ? "Pending" : x.status === "won" ? `Won ${money(scale(x.profit))}` : `Lost $${S.stake}` })));
    rec.append(h("details", {}, h("summary", { text: "Every tracked parlay" }), h("table", {}, tb)));
  }
}

function renderProps() {
  const box = document.getElementById("props"), rec = document.getElementById("propRecord");
  box.replaceChildren(); rec.replaceChildren();
  const P = S.props;
  if (!P) { box.append(h("p", { class: "empty", text: "Props will appear after the next update." })); return; }
  const cur = (P.current || []).filter(x => sportOk(x.sport));
  if (cur.length) {
    const tb = h("tbody");
    for (const x of cur) tb.append(h("tr", {},
      h("td", {}, `${x.name} ${x.side} ${x.line} ${x.label}`, h("small", { text: `${x.game} · ${when(x.date)}` })),
      h("td", { class: "r", text: price(x.price) }),
      h("td", { class: "r", text: Math.round(x.market_prob * 100) + "%" }),
      h("td", { class: "r", text: (+x.projection).toFixed(1) })));
    box.append(h("div", { class: "wide-scroll" }, h("table", { class: "rise" }, h("thead", {}, h("tr", {}, h("th", { text: "Prop" }),
      h("th", { class: "r", text: "Price" }), h("th", { class: "r", text: "DK chance" }), h("th", { class: "r", text: "Our projection" }))), tb)));
  } else box.append(h("p", { class: "empty", text: "No props yet. DraftKings usually posts NBA props on game day." }));
  rec.style.marginTop = "28px";
  const rows = [["All props", P.record.all]];
  for (const [k, n] of [["nba", "NBA"], ["nfl", "NFL"]]) { const x = P.record[k]; if (x && x.wins + x.losses + x.pushes) rows.push([n, x]); }
  rec.append(recordRows(rows));
  if (P.recent && P.recent.length) {
    const tb = h("tbody");
    for (const x of P.recent) tb.append(h("tr", {},
      h("td", {}, `${x.name} ${x.side} ${x.line} ${x.label} (${price(x.price)})`, h("small", { text: x.game })),
      h("td", { class: "r", text: x.actual || "–" }),
      h("td", { class: "r " + (x.result === "win" ? "w" : x.result === "loss" ? "l" : ""),
        text: x.result === "win" ? `Won ${money(scale(x.profit))}` : x.result === "loss" ? `Lost $${S.stake}` : x.result === "void" ? "Void (sat out)" : "Push" })));
    rec.append(h("details", {}, h("summary", { text: "Recent graded props" }), h("table", {}, tb)));
  }
}

// ---------- Today and Yesterday ----------
function dayHeadline(d) {
  const s = d.summary, bb = s.best_bets;
  const prof = scale(s.profit);
  const anyBets = bb[0] + bb[1] + s.parlays[0] + s.parlays[1] + s.props[0] + s.props[1];
  return h("div", { class: "record" },
    h("div", { class: "total rise" }, h("div", { class: "big", text: anyBets ? signed(prof) : wl(...s.winners) }),
      h("p", { text: anyBets ? `All tracked bets at $${S.stake} each: best bets ${wl(...bb)}, parlays ${wl(...s.parlays)}, props ${wl(...s.props)}.`
        : "Winners picked." })),
    h("div", { class: "types rise", style: "grid-template-columns:repeat(2,1fr)" },
      h("div", {}, h("p", { class: "lbl", text: "Winners picked" }), h("div", { class: "big", text: wl(...s.winners) })),
      h("div", {}, h("p", { class: "lbl", text: "Spread picks" }), h("div", { class: "big", text: wl(...s.ats) })),
      h("div", {}, h("p", { class: "lbl", text: "Best bets" }), h("div", { class: "big", text: wl(...bb) })),
      h("div", {}, h("p", { class: "lbl", text: "Games final" }), h("div", { class: "big", text: String(s.games) }))));
}

function gamesTable(games) {
  const tb = h("tbody");
  for (const g of games) {
    const ats = g.ats === "win" ? h("span", { class: "w", text: `covered by ${g.by}` }) : g.ats === "loss" ? h("span", { class: "l", text: `missed by ${-g.by}` }) : g.ats ? "push" : "–";
    tb.append(h("tr", {},
      h("td", {}, `${g.away} ${g.away_score} @ ${g.home} ${g.home_score}`, h("small", { text: SPORT[g.sport] })),
      h("td", {}, g.pick || "–", h("small", {}, ats)),
      h("td", { class: "r " + (g.winner_right ? "w" : "l"), text: g.winner_right ? "Right" : "Wrong" })));
  }
  return h("div", { class: "wide-scroll" }, h("table", { class: "rise" }, h("thead", {}, h("tr", {}, h("th", { text: "Final" }),
    h("th", { text: "Our spread pick" }), h("th", { class: "r", text: "Winner" }))), tb));
}

function extrasTable(d) {
  const rows = [];
  for (const p of d.props || []) rows.push([`Prop: ${p.name} ${p.side} ${p.line} ${p.label}`, p.result, p.result === "win" ? money(scale(p.profit)) : p.actual != null ? `actual ${p.actual}` : ""]);
  for (const p of d.parlays || []) rows.push([`${p.kind === "two" ? "2" : "3"}-game ${SPORT[p.sport]} parlay: ` + p.legs.map(legText).join(", "),
    p.status === "won" ? "win" : p.status === "lost" ? "loss" : p.status === "open" ? "" : p.status, p.status === "won" ? money(scale(p.profit)) : ""]);
  if (!rows.length) return null;
  const tb = h("tbody");
  for (const [txt, res, info] of rows) tb.append(h("tr", {}, h("td", { text: txt }),
    h("td", { class: "r " + (res === "win" ? "w" : res === "loss" ? "l" : ""), text: (res ? (res === "win" ? "Won" : res === "loss" ? "Lost" : res) : "Pending") + (info ? ` (${info})` : "") })));
  return h("table", { class: "rise" }, tb);
}

function dayDetail(d, box) {
  if (d.best_bets && d.best_bets.length) {
    box.append(h("div", { class: "block" }, h("h2", { text: "Best bets" }), pairs(d.best_bets.map(b => betTicket(b.kind, b)))));
  }
  const ex = extrasTable(d);
  if (ex) box.append(h("div", { class: "block" }, h("h2", { text: "Parlays and props" }), ex));
  if (d.games.length) box.append(h("div", { class: "block" }, h("h2", { text: "Every game" }), gamesTable(d.games)));
}

function renderToday() {
  const box = document.getElementById("todayBox"); box.replaceChildren();
  box.append(liveBlock());
  const d = S.daily && S.daily.today;
  if (!d) { box.append(h("p", { class: "empty", text: "Results will appear after the next update." })); return; }
  if (!d.games.length && !(d.best_bets || []).some(b => b.status && b.status !== "open")) {
    box.append(h("p", { class: "empty", text: "No games have finished yet today. Results show up here within 15 minutes of each final." }));
    if (d.best_bets && d.best_bets.length) box.append(h("div", { class: "block" }, h("h2", { text: "Today's locked bets" }), pairs(d.best_bets.map(b => betTicket(b.kind, b)))));
    return;
  }
  box.append(dayHeadline(d));
  dayDetail(d, box);
}

function renderYesterday() {
  const box = document.getElementById("yBox"); box.replaceChildren();
  const d = S.daily && S.daily.yesterday;
  if (!d) return;
  document.getElementById("yDate").textContent = dayName(d.date);
  if (!d.games.length) { box.append(h("p", { class: "empty", text: "No games yesterday." })); return; }
  box.append(dayHeadline(d));
  const hl = [];
  if (d.best_win) hl.push(h("article", { class: "ticket lead hl rise", style: "display:block" }, h("div", { class: "stamp", text: "Won" }),
    h("h3", { text: "Best win" }), h("div", { class: "leg" }, h("b", { text: d.best_win.title })), h("p", { class: "state", text: scaleDetail(d.best_win.detail) })));
  if (d.bad_beat) hl.push(h("article", { class: "ticket hl rise" }, h("div", { class: "stamp l", text: "Ouch" }),
    h("h3", { text: "Bad beat" }), h("div", { class: "leg" }, h("b", { text: d.bad_beat.title })), h("p", { class: "state", text: d.bad_beat.detail })));
  if (hl.length) box.append(h("div", { class: "block" }, h("h2", { text: "Best win and bad beat" }), pairs(hl)));
  dayDetail(d, box);
}

// ---------- Record ----------
function renderRecord() {
  const B = S.best;
  const tot = document.getElementById("recTotal"); tot.replaceChildren();
  if (B) tot.append(totalBlock(B.record.all, "since Oct 22"), chart(B.history));
  let types = document.getElementById("recTypes"); types.replaceChildren();
  const tile = (name, x, note) => {
    if (!x) return;
    const w = x.won ?? x.wins ?? 0, l = x.lost ?? x.losses ?? 0;
    types.append(h("div", { class: "rise" }, h("p", { class: "lbl", text: name }),
      h("div", { class: "big " + cls(x.profit), text: signed(scale(x.profit)) }),
      h("p", { text: (w + l ? wl(w, l, x.pushes) : "No graded bets yet") + (x.roi != null ? ` · ${x.roi}%` : "") + (note ? ` · ${note}` : "") })));
  };
  if (B) { const r = B.record; tile("Best winner", r.winner); tile("Best spread", r.spread); tile("Best parlay", r.parlay); tile("Best prop", r.prop); tile("Same-game parlay", r.sgp); }
  const types2 = document.getElementById("recTypes2"); types2.replaceChildren();
  types = types2;
  if (S.parlays) tile("All parlays", S.parlays.record, S.parlays.record.pending ? `${S.parlays.record.pending} pending` : null);
  if (S.props) tile("All props", S.props.record.all);
  renderTrack();
}

function renderTrack() {
  const box = document.getElementById("track"); box.replaceChildren();
  if (!S.track) return;
  const wrap = h("div", { class: "sport-blocks" });
  for (const [sp, t] of Object.entries(S.track)) {
    if (!sportOk(sp)) continue;
    const s = t.this_season;
    const figs = h("div", { class: "season-figs" });
    if (s) {
      figs.append(h("div", {}, h("strong", { text: s.winner_pct + "%" }), h("small", { text: "Winners picked this season" })),
        h("div", {}, h("strong", { text: s.ats ? wl(s.ats.wins, s.ats.losses, s.ats.pushes) : "–" }), h("small", { text: "Spread picks won-lost" })),
        h("div", {}, h("strong", { class: "gold", text: s.model_ats_big ? wl(s.model_ats_big.wins, s.model_ats_big.losses, s.model_ats_big.pushes) : "–" }),
          h("small", { text: "Gold-edge picks won-lost" + (s.model_ats_big && s.model_ats_big.pct != null ? ` (${s.model_ats_big.pct}%)` : "") })),
        h("div", {}, h("strong", { text: s.avg_miss + " pts" }), h("small", { text: `Average miss on margin · ${s.games.toLocaleString()} games` })));
      const lm = t.line_moves;
      figs.append(h("div", {}, h("strong", { text: lm && lm.pct != null ? lm.pct + "%" : "–" }),
        h("small", { text: lm && lm.toward + lm.away ? `Line moved our way after we posted (${lm.toward} of ${lm.toward + lm.away}; above 55% means a real edge)` : "Line moved our way: tracking started Oct 26" })));
    }
    const ls = t.last_season;
    const tb = h("tbody");
    for (const p of t.periods || []) {
      const a = p.ats;
      tb.append(h("tr", {}, h("td", { text: p.label }), h("td", { class: "r", text: p.games ? wl(...p.winners) : "No games" }),
        h("td", { class: "r", text: a && (a.wins + a.losses) ? wl(a.wins, a.losses, a.pushes) : "–" }),
        h("td", { class: "r", text: p.model_ats_big && (p.model_ats_big.wins + p.model_ats_big.losses) ? wl(p.model_ats_big.wins, p.model_ats_big.losses, p.model_ats_big.pushes) : "–" }),
        h("td", { class: "r", text: p.games ? p.avg_miss + " pts" : "–" })));
    }
    const right = h("div", {}, h("table", {}, h("thead", {}, h("tr", {}, h("th", { text: "" }), h("th", { class: "r", text: "Winners" }),
      h("th", { class: "r", text: "Spread picks" }), h("th", { class: "r", text: "Gold-edge" }), h("th", { class: "r", text: "Avg miss" }))), tb),
      ls ? h("p", { class: "note", style: "margin-top:14px", text: `Last season's test: ${ls.winner_pct}% winners (spread ${ls.spread_winner_pct ?? "–"}%), ${ls.ats ? (ls.ats.pct ?? ls.ats.win_pct) + "% against the spread" : ""}, average miss ${ls.avg_miss} pts.` }) : null);
    if (t.recent && t.recent.length) {
      const rb = h("tbody");
      for (const r of t.recent) {
        const ok = (r.pred > 0) === (r.home_score - r.away_score > 0);
        rb.append(h("tr", {}, h("td", { text: `${r.away} @ ${r.home}` }), h("td", { class: "r", text: (r.pred >= 0 ? r.home : r.away) + " " + Math.abs(r.pred).toFixed(1) }),
          h("td", { class: "r", text: `${r.away_score}-${r.home_score}` }), h("td", { class: "r " + (ok ? "w" : "l"), text: ok ? "Right" : "Wrong" })));
      }
      right.append(h("details", {}, h("summary", { text: "Recent games" }), h("table", {}, rb)));
    }
    wrap.append(h("div", { class: "sport-block rise" }, h("div", {}, h("h3", { text: t.name }), figs), right));
  }
  box.append(wrap);
}

// ---------- page plumbing ----------
function showView() {
  const k = location.hash.slice(1);
  const v = VIEWS.includes(k) ? k : ["results", "parlays", "props"].includes(k) ? (k === "results" ? "record" : "games") : "home";
  for (const x of VIEWS) document.getElementById("view-" + x).hidden = x !== v;
  document.querySelectorAll("#views a[data-view]").forEach(a => { a.classList.toggle("on", a.dataset.view === v); a.toggleAttribute("aria-current", a.dataset.view === v); });
  reveal();
}

function render() {
  renderHome(); renderGames(); renderParlays(); renderProps(); renderToday(); renderYesterday(); renderRecord();
  reveal();
}

let io = null;
function reveal() {
  const els = document.querySelectorAll(".view:not([hidden]) .rise:not(.in)");
  if (!("IntersectionObserver" in window)) { els.forEach(e => e.classList.add("in")); return; }
  io = io || new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) {
    const i = [...e.target.parentNode.children].indexOf(e.target);
    setTimeout(() => e.target.classList.add("in"), Math.min(i, 4) * 75); io.unobserve(e.target); } }), { threshold: .1 });
  els.forEach(e => io.observe(e));
}
function rerender() { render(); document.querySelectorAll(".rise").forEach(e => e.classList.add("in")); }

function setStake(v) {
  S.stake = Math.max(1, Math.min(10000, Math.round(+v) || 20));
  try { localStorage.setItem("hd-stake", S.stake); } catch (e) {}
  const inp = document.getElementById("stake"); if (+inp.value !== S.stake) inp.value = S.stake;
  document.querySelectorAll(".chips button").forEach(b => b.setAttribute("aria-pressed", +b.dataset.v === S.stake));
  if (S.best) rerender();
}
document.getElementById("stake").addEventListener("input", e => e.target.value && setStake(e.target.value));
document.querySelectorAll(".chips button").forEach(b => b.addEventListener("click", () => setStake(b.dataset.v)));

for (const g of document.querySelectorAll(".sports")) {
  for (const [k, n] of [["all", "All"], ["nfl", "NFL"], ["nba", "NBA"], ["cfb", "College"]]) g.append(h("button", { "data-sport": k, text: n }));
  g.addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    S.sport = b.dataset.sport; syncSports(); rerender();
  });
}
function syncSports() { document.querySelectorAll(".sports button").forEach(b => b.setAttribute("aria-pressed", b.dataset.sport === S.sport)); }
syncSports();
document.getElementById("edgeOnly").addEventListener("change", e => { S.edgeOnly = e.target.checked; renderGames(); document.querySelectorAll("#gamesList .rise").forEach(x => x.classList.add("in")); });

window.addEventListener("hashchange", () => { showView(); window.scrollTo(0, 0); });
showView();
if (location.hash) window.scrollTo(0, 0);
setStake(S.stake);

async function load() {
  const bust = "?t=" + Date.now();
  const get = f => fetch("data/" + f + bust).then(r => r.ok ? r.json() : null).catch(() => null);
  const [p, t, pa, pr, b, d] = await Promise.all(["predictions.json", "track_record.json", "parlays.json", "props.json", "bestbets.json", "daily.json"].map(get));
  if (!p && !b) throw new Error("no data");
  Object.assign(S, { preds: p, track: t, parlays: pa, props: pr, best: b, daily: d, base: (b && b.stake) || 20 });
  if (p) document.getElementById("updated").textContent = "Last updated " + new Date(p.updated).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" }) + ".";
  const first = !document.querySelector(".rise.in");
  first ? render() : rerender();
  liveTick();
}
load().catch(() => { document.getElementById("bestbets").replaceChildren(h("p", { class: "empty", text: "Couldn't load picks. Try refreshing." })); });
setInterval(() => load().catch(() => {}), 5 * 60 * 1000);

// ---------- live scores (straight from ESPN, every minute) ----------
const LIVE = {};          // event_id -> { state: pre|in|post, detail, home, away, hs, as }
const BOX = {};           // event_id -> { pid -> stats }
const FEEDS = { nfl: "football/nfl", nba: "basketball/nba", cfb: "football/college-football" };
const COMBOS = { pr: ["pts", "reb"], pa: ["pts", "ast"], ar: ["ast", "reb"], pra: ["pts", "reb", "ast"],
  rr_yds: ["rush_yds", "rec_yds"], pr_yds: ["pass_yds", "rush_yds"] };
const etDate = (d = new Date()) => new URLSearchParams(location.search).get("liveday") || new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(d).replaceAll("-", "");
const n = v => +String(v ?? 0).split(/[-/]/)[0] || 0;

async function loadLive() {
  const day = etDate();
  const boards = await Promise.all(Object.entries(FEEDS).map(([sp, path]) =>
    fetch(`https://site.api.espn.com/apis/site/v2/sports/${path}/scoreboard?dates=${day}${sp === "cfb" ? "&groups=80&limit=300" : ""}`)
      .then(r => r.ok ? r.json() : null).catch(() => null)));
  for (const b of boards) for (const e of (b && b.events) || []) {
    const c = e.competitions[0], st = e.status.type;
    const home = c.competitors.find(x => x.homeAway === "home"), away = c.competitors.find(x => x.homeAway === "away");
    LIVE[e.id] = { state: st.state, detail: st.shortDetail || st.detail, home: home.team.abbreviation, away: away.team.abbreviation,
      hs: +home.score || 0, as: +away.score || 0 };
  }
  // box scores for live player props
  const need = new Set(allLegs().filter(l => l.type === "prop" && LIVE[l.event_id] && LIVE[l.event_id].state !== "pre").map(l => l.event_id + "|" + l.sport));
  await Promise.all([...need].map(async k => {
    const [id, sp] = k.split("|");
    const d = await fetch(`https://site.api.espn.com/apis/site/v2/sports/${FEEDS[sp]}/summary?event=${id}`).then(r => r.ok ? r.json() : null).catch(() => null);
    if (!d || !d.boxscore) return;
    const rows = {};
    for (const team of d.boxscore.players || []) for (const g of team.statistics || []) {
      const keys = g.keys || [];
      for (const a of g.athletes || []) {
        const st = Object.fromEntries(keys.map((k, i) => [k, a.stats[i]])), r = rows[a.athlete.id] = rows[a.athlete.id] || {};
        if (st.points != null) Object.assign(r, { pts: n(st.points), reb: n(st.rebounds), ast: n(st.assists), tpm: n(st["threePointFieldGoalsMade-threePointFieldGoalsAttempted"]) });
        if (g.name === "passing") Object.assign(r, { pass_yds: n(st.passingYards), pass_cmp: n(st["completions/passingAttempts"]), pass_att: +String(st["completions/passingAttempts"] || "0/0").split("/")[1] || 0 });
        if (g.name === "rushing") Object.assign(r, { rush_yds: n(st.rushingYards), carries: n(st.rushingAttempts) });
        if (g.name === "receiving") Object.assign(r, { rec_yds: n(st.receivingYards), rec: n(st.receptions) });
      }
    }
    BOX[id] = rows;
  }));
}

// Every leg of today's tracked bets
function allLegs() {
  const legs = [];
  const B = S.best;
  if (B && B.card) for (const b of Object.values(B.card)) legs.push(...b.legs);
  const P = S.parlays;
  if (P && P.current) for (const c of Object.values(P.current)) for (const k of ["two", "three"]) if (c[k]) legs.push(...c[k].legs.map(l => ({ ...l, type: "spread" })));
  const d = S.daily && S.daily.today;
  if (d) for (const p of d.props || []) legs.push({ ...p, type: "prop", line: +p.line });
  return legs;
}

// How one leg stands right now: { txt, good: true|false|null, done }
function legNow(l) {
  const g = LIVE[l.event_id];
  if (!g || g.state === "pre") return null;
  const done = g.state === "post";
  if (l.type === "prop") {
    const r = (BOX[l.event_id] || {})[l.pid];
    if (!r) return { txt: done ? "didn't play" : "no stats yet", good: null, done };
    const v = COMBOS[l.stat] ? COMBOS[l.stat].reduce((a, k) => a + (r[k] || 0), 0) : (r[l.stat] || 0);
    l = { ...l, label: v === 1 && /s$/.test(l.label) ? l.label.replace(/es$/, "e").replace(/s$/, "") : l.label };
    if (l.side === "over") {
      if (v > l.line) return { txt: `${v} ${l.label}, hit`, good: true, done: true };
      const need = Math.floor(l.line) + 1 - v;
      return { txt: done ? `${v} ${l.label}, missed` : `${v} ${l.label} so far, needs ${need} more`, good: done ? false : null, done };
    }
    if (v > l.line) return { txt: `${v} ${l.label}, missed`, good: false, done: true };
    return { txt: done ? `${v} ${l.label}, hit` : `${v} ${l.label} so far, staying under`, good: done ? true : true, done };
  }
  const home = l.side === "home";
  const margin = home ? g.hs - g.as : g.as - g.hs;
  const score = `${g.away} ${g.as}-${g.hs} ${g.home}, ${done ? "final" : g.detail}`;
  if (l.type === "ml") return { txt: `${score} · ${margin > 0 ? "winning" : margin < 0 ? "losing" : "tied"}`, good: margin > 0 ? true : margin < 0 ? false : null, done };
  const diff = margin + l.line;
  return { txt: `${score} · ${diff > 0 ? `covering by ${diff}` : diff < 0 ? `short by ${-diff}` : "right on the number"}`, good: diff > 0 ? true : diff < 0 ? false : null, done };
}
function liveLeg(l) {
  const x = legNow(l);
  if (!x) return null;
  return h("strong", { class: "live " + (x.good === true ? "res-w" : x.good === false ? "res-l" : ""), text: `${x.done ? "" : "LIVE "}${x.txt}` });
}

function liveBlock() {
  const wrap = h("div", { class: "live-block" });
  const slate = (S.daily && S.daily.today && S.daily.today.slate) || [];
  const live = slate.filter(g => LIVE[g.event_id] && LIVE[g.event_id].state === "in");
  // bets with a leg in play
  const bets = [];
  const B = S.best;
  if (B && B.card) for (const k of KINDS) { const b = B.card[k]; if (b && b.legs.some(l => legNow(l) && !l.result)) bets.push([NAMES[k], b]); }
  const P = S.parlays;
  if (P && P.current) for (const [sp, c] of Object.entries(P.current)) for (const [k, nm] of [["two", "2-game"], ["three", "3-game"]]) {
    const p = c[k]; if (!p) continue;
    const legs = p.legs.map(l => ({ ...l, type: "spread" }));
    if (legs.some(l => legNow(l))) bets.push([`${SPORT[sp]} ${nm} parlay`, { ...p, legs }]);
  }
  for (const p of ((S.daily && S.daily.today && S.daily.today.props) || [])) {
    const l = { ...p, type: "prop", line: +p.line, start: p.date, odds: +p.price };
    if (!p.result && legNow(l)) bets.push(["Player prop", { legs: [l], chance: +p.prob, locked: true, payout: S.base * (1 + (+p.price > 0 ? +p.price / 100 : 100 / -p.price)) }]);
  }
  if (!live.length && !bets.length) return wrap;
  wrap.append(h("h2", { text: "Live now" }));
  if (bets.length) {
    const cards = bets.map(([title, b]) => {
      const states = b.legs.map(legNow).filter(Boolean);
      const anyBad = states.some(x => x.good === false && x.done) , trailing = states.some(x => x.good === false);
      const why = anyBad ? "A leg has lost" : trailing ? "Behind right now" : "On track right now";
      return ticket(title, why, b);
    });
    wrap.append(pairs(cards));
  }
  if (live.length) {
    const tb = h("tbody");
    for (const g of live) {
      const x = LIVE[g.event_id];
      let pick = "–", st = null;
      if (g.spread != null && g.pred != null && g.pred + g.spread !== 0) {
        const home = g.pred + g.spread > 0;
        const l = { type: "spread", event_id: g.event_id, side: home ? "home" : "away", line: home ? g.spread : -g.spread };
        pick = `${home ? g.home : g.away} ${line(l.line)}`;
        const now = legNow(l);
        st = h("small", { class: now.good === true ? "w" : now.good === false ? "l" : "", text: now.txt.split(" · ")[1] });
      }
      tb.append(h("tr", {}, h("td", {}, `${x.away} ${x.as} @ ${x.home} ${x.hs}`, h("small", { text: `${SPORT[g.sport]} · ${x.detail}` })),
        h("td", {}, pick, st)));
    }
    wrap.append(h("div", { class: "block", style: "margin-top:60px" }, h("h3", { class: "day-h", text: "Games in progress" }),
      h("table", {}, h("thead", {}, h("tr", {}, h("th", { text: "Score" }), h("th", { text: "Our spread pick" }))), tb)));
  }
  wrap.style.marginBottom = "120px";
  return wrap;
}

let liveTimer = null;
let liveSig = "";
async function liveTick() {
  try {
    await loadLive();
    const sig = JSON.stringify([LIVE, BOX]);
    if (S.best && sig !== liveSig) { liveSig = sig; rerender(); }
  } catch (e) {}
}
liveTimer = setInterval(liveTick, 60 * 1000);
