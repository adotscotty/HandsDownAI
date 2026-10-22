// Sports AI Picks: renders data/predictions.json and data/track_record.json
const SPORT_NAMES = { nfl: "NFL", nba: "NBA", cfb: "College" };
let state = { sport: "all", edgeOnly: false, preds: null, track: null };

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
    const txt = Math.abs(e) < 0.5 ? "Model agrees with the spread"
      : `Model likes ${side} by ${Math.abs(e).toFixed(1)} pts`;
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
    edgeBox, injBox);
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

function showView() {
  const v = location.hash === "#results" ? "results" : "games";
  document.getElementById("view-games").hidden = v !== "games";
  document.getElementById("view-results").hidden = v !== "results";
  document.querySelectorAll("#views a").forEach(a => a.classList.toggle("on", a.dataset.view === v));
}
window.addEventListener("hashchange", () => { showView(); window.scrollTo(0, 0); });
showView();

function render() { renderGames(); renderTrack(); }

async function load() {
  const bust = "?t=" + Date.now();
  const [p, t] = await Promise.all([fetch("data/predictions.json" + bust).then(r => r.json()),
                                    fetch("data/track_record.json" + bust).then(r => r.json())]);
  state.preds = p; state.track = t;
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
