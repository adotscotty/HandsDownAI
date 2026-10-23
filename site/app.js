// HandsDownAI: renders data/predictions.json and data/track_record.json
const SPORT_NAMES = { nfl: "NFL", nba: "NBA", cfb: "College" };
let state = { sport: "all", edgeOnly: false, preds: null, track: null, parlays: null, props: null, best: null, daily: null };

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v; else if (k === "text") e.textContent = v; else e.setAttribute(k, v);
  }
  for (const k of kids) if (k != null) e.append(k);
  return e;
}
const short = (name, abbr) => (name || abbr || "").split(" ").slice(-1)[0] === "" ? abbr : name;
function fmtSpread(team, spread) {
  if (spread == null) return "No line yet";
  if (spread === 0) return "Pick 'em";
  return `${team} ${spread > 0 ? "+" : ""}${spread}`;
}

function gameCard(g) {
  const homeFav = g.predicted_home_margin >= 0;
  const favName = homeFav ? g.home_name : g.away_name;
  const marg = Math.abs(g.predicted_home_margin).toFixed(1);
  const homePct = Math.round(g.home_win_prob * 100);
  const when = new Date(g.date).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" });

  const team = (logo, name, pct) => el("div", { class: "team" },
    logo ? el("img", { src: logo, alt: "", loading: "lazy" }) : null,
    el("span", { class: "nm", text: name }), el("span", { class: "pct", text: pct + "%" }));

  const bar = el("div", { class: "bar", title: "Win chance" });
  bar.append(el("span", { style: `width:${100 - homePct}%` }));

  let edgeBox = null;
  if (g.edge_vs_spread != null) {
    const e = g.edge_vs_spread;  // positive: model likes the home team against the spread
    const side = e > 0 ? `${g.home} ${fmtSpread("", g.spread).trim()}` : `${g.away} ${fmtSpread("", -g.spread).trim()}`;
    const txt = Math.abs(e) < 0.5 ? "Our model agrees with the spread"
      : `Our model likes ${side} by ${Math.abs(e).toFixed(1)} pts`;
    edgeBox = el("div", { class: "edge" + (Math.abs(e) >= 3 ? " big" : ""), text: txt });
  }

  const injuries = [...(g.away_injuries?.key_injuries || []).map(i => ({ ...i, t: g.away })),
                    ...(g.home_injuries?.key_injuries || []).map(i => ({ ...i, t: g.home }))];
  const injBox = injuries.length ? el("div", { class: "inj",
    text: "Injuries counted: " + injuries.map(i => `${i.name} (${i.t}, ${i.status})`).join(", ") +
      (g.injury_adjustment ? ` · moves line ${Math.abs(g.injury_adjustment).toFixed(1)} pts` : "") }) : null;

  return el("div", { class: "card" },
    el("div", { class: "meta" }, el("span", { text: SPORT_NAMES[g.sport] }), el("span", { text: when })),
    team(g.away_logo, g.away_name, 100 - homePct),
    team(g.home_logo, (g.neutral ? "vs " : "@ ") + g.home_name, homePct),
    bar,
    el("div", { class: "lines" },
      el("div", {}, el("small", { text: "Our prediction" }), `${favName} by ${marg}`),
      el("div", {}, el("small", { text: "Betting spread" }), g.odds_detail || fmtSpread(g.home, g.spread))),
    g.model_home_margin != null && g.spread != null ? el("div", { class: "model-alone",
      text: `Our model alone: ${(g.model_home_margin >= 0 ? g.home_name : g.away_name)} by ${Math.abs(g.model_home_margin).toFixed(1)}` }) : null,
    edgeBox, propBox(g.best_prop), injBox);
}

const priceTxt = p => (+p > 0 ? "+" : "") + (+p);
function propText(bp) {
  return `${bp.name} ${bp.side} ${bp.line} ${bp.label} (${priceTxt(bp.price)})`;
}
function propBox(bp) {
  if (!bp) return null;
  return el("div", { class: "prop" }, el("small", { text: "Best player prop" }), propText(bp),
    el("span", { class: "note", text: ` · DraftKings ${Math.round(bp.market_prob * 100)}% likely · our projection ${(+bp.projection).toFixed(1)}` }));
}

function renderProps() {
  const box = document.getElementById("props"), rec = document.getElementById("propRecord");
  box.replaceChildren(); rec.replaceChildren();
  const P = state.props;
  if (!P) { box.append(el("p", { class: "empty", text: "Props will appear after the next update." })); return; }
  const cur = (P.current || []).filter(x => state.sport === "all" || state.sport === x.sport);
  if (cur.length) {
    const t = el("table", {}, el("tr", {}, el("th", { text: "Game" }), el("th", { text: "Prop" }),
      el("th", { class: "r", text: "DK chance" }), el("th", { class: "r", text: "Our projection" })));
    for (const x of cur) {
      const when = new Date(x.date).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" });
      t.append(el("tr", {}, el("td", {}, x.game, el("small", { text: ` · ${SPORT_NAMES[x.sport]} · ${when}` })),
        el("td", { text: propText(x) }), el("td", { class: "r", text: Math.round(x.market_prob * 100) + "%" }),
        el("td", { class: "r", text: (+x.projection).toFixed(1) })));
    }
    box.append(el("div", { class: "card" }, t));
  } else {
    box.append(el("p", { class: "empty", text: "No props yet: DraftKings usually posts NBA props the day of the game." }));
  }
  const t = el("table", {}, el("tr", {}, el("th", { text: "" }), el("th", { class: "r", text: "Won-lost" }),
    el("th", { class: "r", text: "Profit" }), el("th", { class: "r", text: "ROI" })));
  for (const [k, label] of [["all", "All props"], ["nba", "NBA"], ["nfl", "NFL"]]) {
    const x = P.record[k]; if (!x || (k !== "all" && !(x.wins + x.losses + x.pushes))) continue;
    const cls = x.profit < 0 ? "neg" : x.profit > 0 ? "pos" : "";
    t.append(el("tr", {}, el("td", { text: label }), el("td", { class: "r", text: `${x.wins}-${x.losses}` + (x.pushes ? `-${x.pushes}` : "") }),
      el("td", { class: "r " + cls, text: money(x.profit) }), el("td", { class: "r " + cls, text: x.roi == null ? "–" : x.roi + "%" })));
  }
  const card = el("div", { class: "card" }, t);
  if (P.recent.length) {
    const h = el("table", {}, el("tr", {}, el("th", { text: "Prop" }), el("th", { class: "r", text: "Actual" }), el("th", { class: "r", text: "Result" })));
    for (const x of P.recent) {
      const res = x.result === "win" ? `Won ${money(+x.profit)}` : x.result === "loss" ? "Lost -$20.00" : x.result === "void" ? "Void (sat out)" : "Push";
      h.append(el("tr", {}, el("td", {}, `${x.name} ${x.side} ${x.line} ${x.label} (${priceTxt(x.price)})`, el("small", { text: " · " + x.game })),
        el("td", { class: "r", text: x.actual || "–" }),
        el("td", { class: "r " + (x.result === "win" ? "w" : x.result === "loss" ? "l" : ""), text: res })));
    }
    card.append(el("details", {}, el("summary", { text: "Recent graded props" }), h));
  } else {
    card.append(el("p", { class: "note", text: "Tracking starts today: each game's prop is saved 45 minutes before tip-off and graded from the box score." }));
  }
  rec.append(card);
}

function renderGames() {
  const box = document.getElementById("games");
  box.replaceChildren();
  let games = state.preds.games.filter(g => state.sport === "all" || g.sport === state.sport);
  if (state.edgeOnly) games = games.filter(g => g.edge_vs_spread != null && Math.abs(g.edge_vs_spread) >= 3);
  if (!games.length) { box.append(el("p", { class: "empty", text: "No games to show right now." })); return; }
  let day = null, grid = null;
  for (const g of games) {
    const d = new Date(g.date).toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" });
    if (d !== day) { day = d; box.append(el("div", { class: "day", text: d })); grid = el("div", { class: "grid" }); box.append(grid); }
    grid.append(gameCard(g));
  }
}

function statRows(s, last) {
  if (!s) return el("p", { class: "empty", text: "No finished games yet." });
  const ats = s.ats;
  const atsPct = ats ? (ats.pct ?? ats.win_pct) : null;
  const t = el("table");
  const row = (k, v) => t.append(el("tr", {}, el("td", { text: k }), el("td", { class: "r", text: v })));
  row("Games graded", s.games.toLocaleString());
  row("Picked the winner", s.winner_pct + "%" + (last && s.spread_winner_pct ? ` (spread: ${s.spread_winner_pct}%)` : ""));
  row("Average miss on margin", s.avg_miss + " pts" + (s.spread_avg_miss ? ` (spread: ${s.spread_avg_miss})` : ""));
  if (ats) row("Against the spread", `${ats.wins}-${ats.losses}${ats.pushes ? "-" + ats.pushes : ""} (${atsPct}%)`);
  return t;
}

function periodTable(periods) {
  const t = el("table", {}, el("tr", {}, el("th", { text: "" }), el("th", { class: "r", text: "Winners" }),
    el("th", { class: "r", text: "Vs spread" }), el("th", { class: "r", text: "Avg miss" })));
  for (const p of periods || []) {
    const ats = p.ats;
    t.append(el("tr", {},
      el("td", { text: p.label }),
      el("td", { class: "r", text: p.games ? `${p.winners[0]}-${p.winners[1]}` : "No games" }),
      el("td", { class: "r", text: ats && (ats.wins + ats.losses) ? `${ats.wins}-${ats.losses}${ats.pushes ? "-" + ats.pushes : ""}` : "–" }),
      el("td", { class: "r", text: p.games ? p.avg_miss + " pts" : "–" })));
  }
  return t;
}

function renderTrack() {
  const box = document.getElementById("track");
  box.replaceChildren();
  const grid = el("div", { class: "track" });
  for (const [sport, t] of Object.entries(state.track)) {
    if (state.sport !== "all" && sport !== state.sport) continue;
    const recent = el("table", {}, el("tr", {}, el("th", { text: "Game" }), el("th", { class: "r", text: "Ours" }),
      el("th", { class: "r", text: "Final" }), el("th", { class: "r", text: "" })));
    for (const r of t.recent) {
      const margin = r.home_score - r.away_score;
      const ok = (r.pred > 0) === (margin > 0);
      recent.append(el("tr", {},
        el("td", { text: `${r.away} @ ${r.home}` }),
        el("td", { class: "r", text: (r.pred >= 0 ? r.home : r.away) + " " + Math.abs(r.pred).toFixed(1) }),
        el("td", { class: "r", text: `${r.away_score}-${r.home_score}` }),
        el("td", { class: "r " + (ok ? "w" : "l"), text: ok ? "✓" : "✗" })));
    }
    grid.append(el("div", { class: "card" },
      el("h3", { text: t.name }),
      el("div", { class: "day", text: "Recent" }), periodTable(t.periods),
      el("div", { class: "day", text: "This season" }), statRows(t.this_season),
      el("div", { class: "day", text: "Last season (test)" }), statRows(t.last_season, true),
      t.recent.length ? el("details", {}, el("summary", { text: "Recent results" }), recent) : null));
  }
  box.append(grid);
}

const money = v => (v < 0 ? "-$" : "$") + Math.abs(v).toFixed(2);
const lineTxt = l => (l > 0 ? "+" : "") + (l === 0 ? "PK" : l);

function parlayCard(p, title) {
  const legs = el("ul", { class: "legs" });
  for (const l of p.legs) {
    const when = new Date(l.start).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" });
    legs.append(el("li", {}, `${l.team} ${lineTxt(l.line)}`,
      el("small", { text: `${SPORT_NAMES[l.sport]} · ${l.game} · ${when} · ${Math.round(l.chance * 100)}% to cover` })));
  }
  const proj = p.projected_profit;
  const status = p.status === "won" ? el("span", { class: "w", text: ` · Won ${money(+p.profit)}` })
    : p.status === "lost" ? el("span", { class: "l", text: " · Lost" })
    : p.status === "open" ? el("span", { class: "note", text: " · Locked, waiting on games" }) : null;
  return el("div", { class: "card" }, el("h3", {}, title, status), legs,
    el("div", { class: "nums" },
      el("div", {}, el("small", { text: "Chance to win" }), Math.round(p.chance * 1000) / 10 + "%"),
      el("div", {}, el("small", { text: "Pays on $20" }), money(p.payout)),
      el("div", { class: proj < 0 ? "neg" : "pos" }, el("small", { text: "Projected" }),
        `${money(proj)} (${(100 * proj / 5).toFixed(0)}%)`)));
}

function renderParlays() {
  const box = document.getElementById("parlays"), rec = document.getElementById("parlayRecord");
  box.replaceChildren(); rec.replaceChildren();
  const P = state.parlays;
  if (!P) { box.append(el("p", { class: "empty", text: "Parlays will appear after the next update." })); return; }
  let shown = 0;
  for (const sport of ["nfl", "nba", "cfb"]) {
    if (state.sport !== "all" && state.sport !== sport) continue;
    const card = (P.current || {})[sport];
    if (!card || (!card.two && !card.three)) continue;
    box.append(el("div", { class: "day", text: SPORT_NAMES[sport] + (card.locked ? " · locked for today" : "") }));
    const grid = el("div", { class: "grid" });
    if (card.two) grid.append(parlayCard(card.two, "2-game parlay"));
    if (card.three) grid.append(parlayCard(card.three, "3-game parlay"));
    box.append(grid); shown++;
  }
  if (!shown) box.append(el("p", { class: "empty", text: "No parlays today: a sport needs at least 4 games with betting lines in the next 24 hours for a 2-game parlay, and 6 for a 3-game parlay." }));
  const r = P.record;
  const t = el("table", {}, el("tr", {}, el("th", { text: "" }), el("th", { class: "r", text: "Won-lost" }),
    el("th", { class: "r", text: "Profit" }), el("th", { class: "r", text: "ROI" })));
  const line = (label, x) => {
    if (!x) return;
    const cls = x.profit < 0 ? "neg" : x.profit > 0 ? "pos" : "";
    t.append(el("tr", {}, el("td", { text: label + (x.pending ? ` (${x.pending} pending)` : "") }),
      el("td", { class: "r", text: `${x.won}-${x.lost}` }),
      el("td", { class: "r " + cls, text: money(x.profit) }),
      el("td", { class: "r " + cls, text: x.roi == null ? "–" : x.roi + "%" })));
  };
  line("All parlays", r);
  line("2-game", (r.by_kind || {}).two);
  line("3-game", (r.by_kind || {}).three);
  t.append(el("tr", {}, el("td", { text: "Total bet" }), el("td", {}), el("td", { class: "r", text: money(r.staked) }), el("td", {})));
  const card = el("div", { class: "card" }, t);
  if (P.history.length) {
    const h = el("table", {}, el("tr", {}, el("th", { text: "Parlay" }), el("th", { class: "r", text: "Result" })));
    for (const x of P.history) {
      const res = x.status === "open" ? "Pending" : x.status === "won" ? `Won ${money(+x.profit)}` : "Lost -$20.00";
      h.append(el("tr", {}, el("td", { text: x.legs.map(l => `${l.team} ${lineTxt(l.line)}`).join(", ") }),
        el("td", { class: "r " + (x.status === "won" ? "w" : x.status === "lost" ? "l" : ""), text: res })));
    }
    card.append(el("details", {}, el("summary", { text: "Every tracked parlay" }), h));
  } else {
    card.append(el("p", { class: "note", text: "Tracking starts with today's parlays: each one is saved just before its first game and graded when all its games finish." }));
  }
  rec.append(card);
}

const VIEWS = ["home", "games", "today", "yesterday", "record"];
function showView() {
  const h = location.hash.slice(1);
  const v = VIEWS.includes(h) ? h : (h === "results" || h === "parlays" || h === "props") ? "record" : "home";
  for (const x of VIEWS) document.getElementById("view-" + x).hidden = x !== v;
  document.getElementById("tabs").hidden = !["games", "record"].includes(v);
  document.querySelectorAll("#views a").forEach(a => a.classList.toggle("on", a.dataset.view === v));
}
window.addEventListener("hashchange", () => { showView(); window.scrollTo(0, 0); });
showView();

function render() { renderHome(); renderGames(); renderToday(); renderYesterday(); renderTrack(); renderParlays(); renderProps(); }

async function load() {
  const bust = "?t=" + Date.now();
  const [p, t] = await Promise.all([fetch("data/predictions.json" + bust).then(r => r.json()),
                                    fetch("data/track_record.json" + bust).then(r => r.json())]);
  state.preds = p; state.track = t;
  state.parlays = await fetch("data/parlays.json" + bust).then(r => r.ok ? r.json() : null).catch(() => null);
  state.props = await fetch("data/props.json" + bust).then(r => r.ok ? r.json() : null).catch(() => null);
  state.best = await fetch("data/bestbets.json" + bust).then(r => r.ok ? r.json() : null).catch(() => null);
  state.daily = await fetch("data/daily.json" + bust).then(r => r.ok ? r.json() : null).catch(() => null);
  document.getElementById("updated").textContent = "Last updated " + new Date(p.updated).toLocaleString();
  render();
}

document.getElementById("tabs").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  state.sport = b.dataset.sport;
  document.querySelectorAll("#tabs button").forEach(x => x.classList.toggle("on", x === b));
  render();
});
document.getElementById("edgeOnly").addEventListener("change", e => { state.edgeOnly = e.target.checked; renderGames(); });
load().catch(() => { document.getElementById("updated").textContent = "Couldn't load predictions. Try refreshing."; });
setInterval(() => load().catch(() => {}), 5 * 60 * 1000);


// ---------- Best bets, today's results, yesterday's recap ----------

const BET_NAMES = { winner: "Best winner", spread: "Best spread", parlay: "Best parlay", prop: "Best player prop", sgp: "Best same-game parlay" };
const BET_HINT = { winner: "Most likely winner (moneyline)", spread: "Most likely to cover", parlay: "Best value 2- or 3-game parlay",
  prop: "DraftKings' most likely prop", sgp: "Spread + player prop, same game" };
const whenTxt = d => new Date(d).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" });
const fmtLine = l => l === 0 ? "PK" : (l > 0 ? "+" : "") + l;
function legText(l) {
  if (l.type === "prop") return `${l.name} ${l.side} ${l.line} ${l.label}`;
  if (l.type === "ml") return `${l.team_name || l.team} to win`;
  return `${l.team} ${fmtLine(l.line)}`;
}
function legResult(l) {
  if (!l.result) return null;
  const cls = l.result === "win" ? "w" : l.result === "loss" ? "l" : "";
  const extra = l.type === "prop" && l.actual != null ? ` (${l.actual})` : "";
  return el("span", { class: cls, text: ` · ${l.result === "win" ? "hit" : l.result === "loss" ? "missed" : l.result}${extra}` });
}

function betCard(kind, b) {
  const head = el("div", { class: "bet-head" }, el("h3", { text: BET_NAMES[kind] }), el("span", { class: "hint", text: BET_HINT[kind] }));
  if (!b) return el("div", { class: "card bet empty-bet" }, head, el("p", { class: "empty", text: "Nothing qualifies today." }));
  const legs = el("ul", { class: "legs" });
  for (const l of b.legs) legs.append(el("li", {}, legText(l), legResult(l),
    el("small", { text: `${SPORT_NAMES[l.sport]} · ${l.game} · ${whenTxt(l.start)} · ${priceTxt(l.odds)}` })));
  let status;
  if (b.status === "won") status = el("div", { class: "status w", text: `Won ${money(+b.profit)}` });
  else if (b.status === "lost") status = el("div", { class: "status l", text: "Lost -$20.00" });
  else if (b.status === "push") status = el("div", { class: "status", text: "Push, money back" });
  else if (b.locked) status = el("div", { class: "status", text: "Locked · waiting on the game" });
  else status = el("div", { class: "status muted", text: "Can still change until 45 min before start" });
  return el("div", { class: "card bet" }, head, legs,
    el("div", { class: "nums" },
      el("div", {}, el("small", { text: "Price" }), priceTxt(b.price)),
      el("div", {}, el("small", { text: "Chance" }), Math.round(b.chance * 100) + "%"),
      el("div", {}, el("small", { text: "ROI if it wins" }), "+" + Math.round((b.payout / 20 - 1) * 100) + "%")),
    status);
}

function recordTable(rows) {
  const t = el("table", {}, el("tr", {}, el("th", { text: "" }), el("th", { class: "r", text: "Won-lost" }),
    el("th", { class: "r", text: "Profit" }), el("th", { class: "r", text: "ROI" })));
  for (const [label, x] of rows) {
    if (!x) continue;
    const cls = x.profit < 0 ? "neg" : x.profit > 0 ? "pos" : "";
    t.append(el("tr", {}, el("td", { text: label }), el("td", { class: "r", text: `${x.won}-${x.lost}` }),
      el("td", { class: "r " + cls, text: money(x.profit) }), el("td", { class: "r " + cls, text: x.roi == null ? "–" : x.roi + "%" })));
  }
  return t;
}

function renderHome() {
  const box = document.getElementById("bestbets"), rec = document.getElementById("bestRecord"), tz = document.getElementById("yesterdayTeaser");
  box.replaceChildren(); rec.replaceChildren(); tz.replaceChildren();
  const B = state.best;
  if (!B) { box.append(el("p", { class: "empty", text: "Best bets will appear after the next update." })); return; }
  let card = B.card, title = "Today's best bets";
  if ((!card || !Object.keys(card).length) && B.preview) {
    card = B.preview.card;
    title = "Next up: " + new Date(B.preview.date + "T12:00").toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" });
  }
  document.getElementById("homeTitle").textContent = title;
  const grid = el("div", { class: "grid" });
  for (const k of ["winner", "spread", "parlay", "prop", "sgp"]) grid.append(betCard(k, card ? card[k] : null));
  box.append(grid);
  const y = state.daily && state.daily.yesterday;
  if (y && y.summary.games) {
    const s = y.summary;
    tz.append(el("a", { class: "card teaser", href: "#yesterday" },
      el("strong", { text: "Yesterday: " }),
      `Winners ${s.winners[0]}-${s.winners[1]} · Spreads ${s.ats[0]}-${s.ats[1]}` +
      (s.best_bets[0] + s.best_bets[1] ? ` · Best bets ${s.best_bets[0]}-${s.best_bets[1]}` : "") + "  →  See the recap"));
  }
  const r = B.record;
  rec.append(el("div", { class: "card" }, recordTable([["All best bets", r.all], ["Winner", r.winner], ["Spread", r.spread],
    ["Parlay", r.parlay], ["Prop", r.prop], ["Same-game parlay", r.sgp]]),
    r.all.won + r.all.lost ? null : el("p", { class: "note", text: "Tracking starts today." })));
}

function gameRow(g) {
  const ats = g.ats ? el("span", { class: g.ats === "win" ? "w" : g.ats === "loss" ? "l" : "",
    text: g.ats === "win" ? `covered by ${g.by}` : g.ats === "loss" ? `missed by ${-g.by}` : "push" }) : "–";
  return el("tr", {},
    el("td", {}, `${g.away} ${g.away_score} @ ${g.home} ${g.home_score}`, el("small", { text: " · " + SPORT_NAMES[g.sport] })),
    el("td", {}, g.pick || "–", el("br"), ats),
    el("td", { class: "r " + (g.winner_right ? "w" : "l"), text: g.winner_right ? "✓" : "✗" }));
}

function dayDetail(d, box) {
  const s = d.summary;
  const tiles = el("div", { class: "tiles" });
  const tile = (label, wl, extra) => tiles.append(el("div", { class: "tile" }, el("small", { text: label }),
    el("strong", { text: `${wl[0]}-${wl[1]}` }), extra ? el("small", { text: extra }) : null));
  tile("Winners picked", s.winners);
  tile("Against the spread", s.ats);
  if (s.best_bets[0] + s.best_bets[1]) tile("Best bets", s.best_bets);
  if (s.parlays[0] + s.parlays[1]) tile("Parlays", s.parlays);
  if (s.props[0] + s.props[1]) tile("Props", s.props);
  if (s.best_bets[0] + s.best_bets[1] + s.parlays[0] + s.parlays[1] + s.props[0] + s.props[1])
    tiles.append(el("div", { class: "tile" }, el("small", { text: "Profit ($20 bets)" }),
      el("strong", { class: s.profit < 0 ? "neg" : s.profit > 0 ? "pos" : "", text: money(s.profit) })));
  box.append(tiles);
  if (d.best_bets.length) {
    const grid = el("div", { class: "grid" });
    for (const b of d.best_bets) grid.append(betCard(b.kind, b));
    box.append(el("h3", { class: "sub-h", text: "Best bets" }), grid);
  }
  const extra = [];
  for (const p of d.props) extra.push([`Prop: ${p.name} ${p.side} ${p.line} ${p.label}`, p.result, p.actual]);
  for (const p of d.parlays) extra.push([`${p.kind === "two" ? "2" : "3"}-game parlay (${SPORT_NAMES[p.sport]}): ` + p.legs.map(legText).join(", "),
    p.status === "won" ? "win" : p.status === "lost" ? "loss" : p.status === "open" ? "" : p.status, p.status === "won" ? money(p.profit) : ""]);
  if (extra.length) {
    const t = el("table", {});
    for (const [txt, res, info] of extra) t.append(el("tr", {}, el("td", { text: txt }),
      el("td", { class: "r " + (res === "win" ? "w" : res === "loss" ? "l" : ""), text: (res ? (res === "win" ? "Won" : res === "loss" ? "Lost" : res) : "Pending") + (info ? ` (${info})` : "") })));
    box.append(el("h3", { class: "sub-h", text: "Parlays and props" }), el("div", { class: "card" }, t));
  }
  if (d.games.length) {
    const t = el("table", {}, el("tr", {}, el("th", { text: "Final" }), el("th", { text: "Our spread pick" }), el("th", { class: "r", text: "Winner" })));
    for (const g of d.games) t.append(gameRow(g));
    box.append(el("h3", { class: "sub-h", text: "Every game" }), el("div", { class: "card" }, t));
  }
}

function renderToday() {
  const box = document.getElementById("today"); box.replaceChildren();
  const d = state.daily && state.daily.today;
  if (!d || (!d.games.length && !d.best_bets.some(b => b.status !== "open"))) {
    box.append(el("p", { class: "empty", text: "No games have finished yet today. Results show up here within 15 minutes of each final." }));
    if (d && d.best_bets.length) { const g = el("div", { class: "grid" }); d.best_bets.forEach(b => g.append(betCard(b.kind, b))); box.append(g); }
    return;
  }
  dayDetail(d, box);
}

function renderYesterday() {
  const box = document.getElementById("yesterday"); box.replaceChildren();
  const d = state.daily && state.daily.yesterday;
  if (!d) return;
  document.getElementById("yTitle").textContent = "Yesterday's recap · " +
    new Date(d.date + "T12:00").toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" });
  if (!d.games.length) { box.append(el("p", { class: "empty", text: "No games yesterday." })); return; }
  const hl = el("div", { class: "grid hl" });
  if (d.best_win) hl.append(el("div", { class: "card win" }, el("small", { text: "🏆 Best win" }), el("strong", { text: d.best_win.title }), el("p", { text: d.best_win.detail })));
  if (d.bad_beat) hl.append(el("div", { class: "card beat" }, el("small", { text: "😩 Bad beat" }), el("strong", { text: d.bad_beat.title }), el("p", { text: d.bad_beat.detail })));
  box.append(hl);
  dayDetail(d, box);
}
