"use strict";
const $ = (selector, parent = document) => parent.querySelector(selector);
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (ch) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        ch
      ],
  );
const icon = (name) => `<i data-lucide="${name}"></i>`;
const fmt = (n, digits = 2) =>
  n === null || n === undefined
    ? "—"
    : Number(n).toLocaleString("da-DK", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });
const pct = (n, sign = false) =>
  n === null || n === undefined
    ? "—"
    : `${sign && n > 0 ? "+" : ""}${fmt(n * 100, 1)}%`;
const money = (n) => `${fmt(n)} <span class="unit">EUR</span>`;
const color = (n) =>
  n === null || n === undefined ? "muted" : n >= 0 ? "positive" : "negative";
const tag = (text, style = text) =>
  `<span class="tag ${esc(style)}">${esc(text)}</span>`;
const age = (ts) => `${Math.max(0, Math.floor(Date.now() / 1000 - ts))}s`;
const date = (ts) =>
  ts
    ? new Date(ts * 1000).toLocaleString("da-DK", {
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";
const metric = (label, value, sub = "", css = "") =>
  `<div><div class="metric-label">${label}</div><div class="metric-value ${css}">${value}</div><div class="metric-sub">${sub}</div></div>`;
const empty = (title, text) =>
  `<div class="empty"><strong>${title}</strong>${text}</div>`;
const titles = {
  overview: "Overblik",
  opportunities: "Muligheder",
  markets: "Markeder",
  portfolio: "Portefølje",
  strategies: "Strategier",
  analytics: "Analyse",
  lab: "Strategilab",
  models: "Modeller",
  history: "Historik",
  settings: "Indstillinger",
  crypto: "Krypto",
};
let state = null,
  currentMode = "DEMO",
  currentView = "overview",
  loading = false,
  revision = 0,
  activeDecision = null,
  labData = null,
  settingsData = null,
  chartRange = "ALL";
let filters = { q: "", action: "", model: "", sport: "", sort: "ev" },
  refreshTimer,
  searchTimer;
const csrf = $("meta[name=csrf-token]").content;
const originalFetch = window.fetch.bind(window);
async function api(path, data, method) {
  const options = {
    method: method || (data ? "POST" : "GET"),
    credentials: "same-origin",
    headers: {},
  };
  if (data) {
    options.headers = {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrf,
    };
    options.body = JSON.stringify(data);
  }
  const response = await originalFetch(path, options);
  if (response.status === 401) {
    location.href = "/login";
    throw new Error("Session udløbet");
  }
  const result = await response.json();
  if (!response.ok)
    throw new Error(result.error || `Serverfejl (${response.status})`);
  return result;
}
function icons() {
  if (window.lucide) window.lucide.createIcons();
}
function error(message) {
  $("#error-banner").textContent = message;
  $("#error-banner").hidden = !message;
  document.querySelectorAll(".dialog-error").forEach((e) => e.remove());
  const open = document.querySelector("dialog[open]");
  if (message && open) {
    const e = document.createElement("div");
    e.className = "error-banner dialog-error";
    e.textContent = message;
    open.prepend(e);
  }
}
let toastTimer;
let historyData = { bets: [], page: 1, pages: 1, total: 0 };
let historyFilters = { q: "", status: "", sort: "time", page: 1 };
let historyRevision = 0;
async function loadHistory() {
  const rev = ++historyRevision;
  const mode = currentMode;
  const result = await api(
    "/api/terminal/history?" + new URLSearchParams({ mode, ...historyFilters }),
  );
  if (mode === currentMode && rev === historyRevision) historyData = result;
}
function historyPage() {
  return (
    historyTable(historyData.bets) +
    `<div class="toolbar" style="margin-top:16px"><span class="muted small">${historyData.total} registreringer · side ${historyData.page}/${historyData.pages}</span><span class="spacer"></span><button id="history-prev" class="icon-button" title="Forrige side" ${historyData.page === 1 ? "disabled" : ""}>${icon("chevron-left")}</button><button id="history-next" class="icon-button" title="Næste side" ${historyData.page >= historyData.pages ? "disabled" : ""}>${icon("chevron-right")}</button></div>`
  );
}
function toast(message) {
  clearTimeout(toastTimer);
  $("#toast").textContent = message;
  $("#toast").hidden = false;
  toastTimer = setTimeout(() => ($("#toast").hidden = true), 5000);
}
async function action(work) {
  try {
    error("");
    await work();
  } catch (e) {
    error(e.message);
  }
}
async function refresh(render = true) {
  const rev = ++revision,
    mode = currentMode;
  const params = new URLSearchParams({ mode });
  const result = await api("/api/terminal/overview?" + params);
  if (rev !== revision || mode !== currentMode) return;
  state = result;
  $("#heartbeat").textContent =
    result.scheduler?.running && result.scheduler.run_sports
      ? "PAPER-motor kører"
      : "Journal online";
  $("#heartbeat-dot").classList.remove("offline");
  $("#nav-count").textContent = result.brain.bet + result.brain.watch;
  $("#last-update").textContent =
    `Journal opdateret ${new Date().toLocaleTimeString("da-DK")}`;
  $("#halt").title =
    currentView === "crypto"
      ? "Stop og luk kryptopositioner"
      : state.account.halted
        ? "Ophæv globalt sportsstop"
        : "Stop nye sportsregistreringer";
  $("#halt").classList.toggle("primary", !!state.account.halted);
  if (currentView === "crypto") await loadCrypto();
  if (currentView === "history") await loadHistory();
  if (render) renderView();
}
async function scan() {
  if (loading) return;
  loading = true;
  $("#scan").disabled = true;
  $("#scan").innerHTML = icon("loader-circle") + "<span>Scanner</span>";
  icons();
  $("#scan .lucide").classList.add("spin");
  try {
    const result = await api("/api/terminal/scan", { mode: currentMode });
    await refresh();
    toast(result.message);
  } finally {
    loading = false;
    $("#scan").disabled = false;
    $("#scan").innerHTML = icon("refresh-cw") + "<span>Scan markedet</span>";
    icons();
  }
}
function modeBanner() {
  const crypto = currentView === "crypto";
  const haltLabel = crypto
    ? "Stop og luk kryptopositioner"
    : state.account.halted
      ? "Ophæv sportsstop"
      : "Globalt sportsstop";
  $("#halt").title = haltLabel;
  $("#halt").setAttribute("aria-label", haltLabel);
  $("#halt").classList.toggle(
    "primary",
    crypto ? !!cryptoData?.risk.halted : !!state.account.halted,
  );
  $("#heartbeat").textContent = crypto
    ? state.scheduler.running && state.scheduler.run_live
      ? "Kryptomotor kører"
      : "Kryptomotor stoppet"
    : state.scheduler.running && state.scheduler.run_sports
      ? "PAPER-motor kører"
      : "Journal online";
  $("#modes").hidden = currentView === "crypto";
  $("#mode-banner").hidden = currentView === "crypto";
  $("#scan span").textContent =
    currentView === "crypto" ? "Kør cyklus" : "Scan markedet";
  if (currentView === "crypto") return;
  const descriptions = {
    DEMO: "Illustrative priser. Beløb og resultater er adskilt fra PAPER og REAL.",
    PAPER:
      "Aktuelle odds, virtuelle indsatser. Resultater og CLV registreres i paper-journalen.",
    REAL: "Manuelt registrerede væddemål. LIVE kræver dokumentation fra PAPER; ingen bookmaker-ordrer sendes.",
  };
  $("#mode-banner").innerHTML =
    tag(
      currentMode,
      currentMode === "DEMO"
        ? "amber"
        : currentMode === "REAL"
          ? "red"
          : "gray",
    ) +
    `<span>${descriptions[currentMode]}</span><span class="banner-end">INGEN DOKUMENTERET EDGE</span>`;
}
async function navigate(view) {
  if (!titles[view]) view = "overview";
  $("#navigation-menu").close();
  currentView = view;
  history.replaceState(null, "", "#" + view);
  $("#page-title").textContent = titles[view];
  $("#breadcrumb").textContent = titles[view];
  document
    .querySelectorAll("[data-view]")
    .forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  if (view === "lab" || view === "models")
    labData = await api("/api/terminal/lab");
  if (view === "settings") settingsData = await api("/api/settings");
  if (view === "crypto") await loadCrypto();
  if (view === "history") await loadHistory();
  renderView();
}
function metricsStrip() {
  const m = state.metrics,
    a = state.account;
  return `<div class="metric-strip">${metric("SAMLET PULJE", money(a.equity), `Disponibel ${fmt(a.cash)} EUR`)}${metric("REALISERET P/L", money(m.profit), `${m.settled} afgjorte · ${currentMode}`, color(m.profit))}${metric("YIELD / ROI", pct(m.roi), m.roi_ci ? `95% interval ${pct(m.roi_ci[0])} til ${pct(m.roi_ci[1])}` : "Afventer tilstrækkelig stikprøve", color(m.roi))}${metric("GENNEMSNITLIG CLV", pct(m.clv, true), `${m.clv_n} observerede lukkepriser`, color(m.clv))}${metric("AKTIV EKSPONERING", money(a.exposure), `${pct(a.equity ? a.exposure / a.equity : 0)} af puljen · ${state.open_count} åbne`)}</div>`;
}
function chartHTML(id, title, seriesExists, range = false) {
  return `<div class="chart-region"><div class="section-heading"><h2>${title}</h2>${range ? '<div class="segmented" id="chart-range">' + ["7D", "30D", "3M", "YTD", "ALL"].map((v) => `<button data-range="${v}" class="${v === chartRange ? "selected" : ""}">${v}</button>`).join("") + "</div>" : ""}</div>${seriesExists ? `<canvas id="${id}" role="img" aria-label="${title}"></canvas>` : `<div class="chart-empty">${icon("chart-no-axes-combined")}<span>Afventer afgjorte væddemål</span><small>Ingen konstrueret performance</small></div>`}<div class="chart-legend"><span><span class="legend-dot"></span>Realiseret</span><span><span class="legend-dot expected"></span>Modelens forventning</span></div></div>`;
}
function filteredOpportunities() {
  let rows = state.opportunities.filter(
    (o) =>
      (!filters.q ||
        `${o.home} ${o.away} ${o.name}`
          .toLowerCase()
          .includes(filters.q.toLowerCase())) &&
      (!filters.action || o.action === filters.action) &&
      (!filters.model || o.model_version === filters.model) &&
      (!filters.sport || o.sport === filters.sport),
  );
  return rows.sort((a, b) =>
    filters.sort === "odds"
      ? b.odds - a.odds
      : filters.sort === "time"
        ? a.start - b.start
        : (b.robust_ev ?? -1) - (a.robust_ev ?? -1),
  );
}
function opportunityTable(rows) {
  if (!rows.length)
    return empty(
      "Ingen muligheder i denne visning",
      "Scan markedet, eller juster filtrene. Et tomt BET-feed er et gyldigt resultat.",
    );
  return `<div class="table-wrap desktop-opportunities"><table><thead><tr><th>Kamp / marked</th><th>Udfald</th><th>Bedste odds</th><th>DDM / marked</th><th>EV / robust EV</th><th>Kelly-score</th><th>Status</th><th></th></tr></thead><tbody>${rows.map((o) => `<tr tabindex="0" data-detail="${o.id}"><td class="event-cell"><strong>${esc(o.home)}<span class="muted"> / </span>${esc(o.away)}</strong><small>${esc(o.league)} · h2h · ${date(o.start)}</small></td><td class="selection">${esc(o.name)}</td><td class="mono"><strong>${fmt(o.odds)}</strong><small class="muted" style="display:block;font-size:9px">${esc(o.book_title)} · ${age(o.updated_at)}</small></td><td class="mono">${pct(o.p)}<small class="muted" style="display:block;font-size:10px">${pct(o.market_p)} no-vig</small></td><td class="mono"><span class="${color(o.ev)}">${pct(o.ev, true)}</span><small class="muted" style="display:block;font-size:10px">${pct(o.robust_ev, true)} konservativ</small></td><td class="mono" title="100 × fuld Kelly ved konservativ p. Ikke en valideret confidence-score."><span class="mini-track"><span style="width:${Math.min(100, o.score)}%"></span></span>${fmt(o.score, 1)}</td><td>${tag(o.action)}</td><td><button data-detail="${o.id}" class="row-button" title="Se analyse" aria-label="Se analyse">${icon("arrow-up-right")}</button></td></tr>`).join("")}</tbody></table></div><div class="mobile-list">${rows.map((o) => `<div class="mobile-opportunity"><div class="top"><div><strong>${esc(o.home)} / ${esc(o.away)}</strong><div class="small muted">${esc(o.league)} · ${esc(o.name)}</div></div>${tag(o.action)}</div><div class="numbers"><div><small>Odds</small>${fmt(o.odds)}</div><div><small>DDM / no-vig</small>${pct(o.p)} / ${pct(o.market_p)}</div><div class="${color(o.robust_ev)}"><small>Robust EV</small>${pct(o.robust_ev, true)}</div></div><button data-detail="${o.id}">Se analyse ${icon("arrow-up-right")}</button></div>`).join("")}</div>`;
}
function brain() {
  const b = state.brain;
  return `<section class="brain"><div class="brain-head">${icon("brain-circuit")}<h2>DDM Brain</h2>${tag("EKSPERIMENT", "gray")}</div><div class="brain-grid"><div><div class="brain-number">${b.markets}</div><div class="brain-label">Markeder</div></div><div><div class="brain-number positive">${b.bet}</div><div class="brain-label">BET</div></div><div><div class="brain-number amber-text">${b.watch}</div><div class="brain-label">WATCH</div></div></div><div class="decision-bar"><span class="bet" style="flex:${b.bet || 0.05}"></span><span class="watch" style="flex:${b.watch || 0.05}"></span><span style="flex:${b.pass || 0.05}"></span></div><div class="brain-row"><span>Modelstatus</span><strong>${esc(state.model_health)}</strong></div><div class="brain-row"><span>Strategi</span><strong>${tag(state.strategy.state, "gray")}</strong></div><div class="brain-row"><span>Likviditet</span><strong class="muted">Ikke målt af odds-feedet</strong></div><div class="brain-row"><span>Forældede beslutninger</span><strong>${b.stale}</strong></div></section>`;
}
function overview() {
  return `${metricsStrip()}<div class="overview-grid">${chartHTML("equity", "Puljens udvikling", state.metrics.settled > 0, true)}${brain()}</div><div class="section-heading"><h2>Markedets muligheder <span class="muted small">/ ${state.opportunity_count}</span></h2><button class="section-link" data-view="opportunities">Alle muligheder ${icon("arrow-right")}</button></div>${opportunityTable(state.opportunities.slice(0, 6))}<section class="method"><div class="section-heading"><h2>Den Danske Metode</h2><span class="meta">DATA → PRIS → BESLUTNING → EVIDENS</span></div><div class="method-steps">${[
    ["01", "Indlæs", "Odds og historik"],
    ["02", "Verificer", "Tid, identitet, margin"],
    ["03", "Estimer", "No-vig og model"],
    ["04", "Vurder", "EV og usikkerhed"],
    ["05", "Begræns", "Kelly og eksponering"],
    ["06", "Evaluer", "Resultat, CLV, kalibrering"],
  ]
    .map(
      ([n, t, s]) =>
        `<div class="method-step"><span>${n}</span><strong>${t}</strong><small>${s}</small></div>`,
    )
    .join("")}</div></section>`;
}
function filterToolbar() {
  const versions = [
      ...new Set(state.opportunities.map((o) => o.model_version)),
    ],
    sports = [...new Set(state.opportunities.map((o) => o.sport))];
  return `<div class="toolbar"><div class="search">${icon("search")}<input id="search" aria-label="Søg kampe" placeholder="Søg kamp eller udfald" value="${esc(filters.q)}"></div><select id="filter-action" aria-label="Beslutning"><option value="">Alle beslutninger</option>${["BET", "WATCH", "PASS"].map((x) => `<option ${filters.action === x ? "selected" : ""}>${x}</option>`).join("")}</select><select id="filter-sport" aria-label="Sport"><option value="">Alle sportsgrene</option>${sports.map((s) => `<option value="${esc(s)}" ${filters.sport === s ? "selected" : ""}>${esc(s)}</option>`).join("")}</select><select id="filter-model" aria-label="Model"><option value="">Alle modeller</option>${versions.map((s) => `<option value="${esc(s)}" ${filters.model === s ? "selected" : ""}>${esc(s)}</option>`).join("")}</select><span class="spacer"></span><select id="filter-sort" aria-label="Sortering"><option value="ev">Robust EV</option><option value="odds" ${filters.sort === "odds" ? "selected" : ""}>Højeste odds</option><option value="time" ${filters.sort === "time" ? "selected" : ""}>Kampstart</option></select><button class="icon-button" id="save-view" title="Gem filtervisning" aria-label="Gem filtervisning">${icon("bookmark-plus")}</button><button class="icon-button" id="load-view" title="Hent gemt filtervisning" aria-label="Hent gemt filtervisning">${icon("bookmark")}</button></div>`;
}
function markets() {
  const rows = state.opportunities;
  return `<div class="section-heading"><h2>Bookmaker-sammenligning</h2><span class="meta">SAMME KAMP · SAMME H2H-UDFALD</span></div>${
    rows.length
      ? `<div class="table-wrap"><table><thead><tr><th>Kamp / udfald</th><th>Bookmaker</th><th>Odds</th><th>Forskel til bedste</th><th>EV tabt</th><th>Opdateret</th><th>Status</th></tr></thead><tbody>${rows
          .slice(0, 30)
          .flatMap((o) =>
            o.books.map(
              (b) =>
                `<tr data-detail="${o.id}"><td class="event-cell"><strong>${esc(o.home)} / ${esc(o.away)}</strong><small>${esc(o.name)}</small></td><td>${esc(b.book)} ${b.odds === o.odds ? tag("BEDST", "green") : ""}</td><td class="mono">${fmt(b.odds)}</td><td class="mono muted">${fmt(b.odds - o.odds)}</td><td class="mono negative">${o.ev === null ? "—" : pct(o.ev - b.ev)}</td><td class="mono muted">${age(b.updated_at)}</td><td>${tag(b.status === "FRESH" ? "AKTUEL" : "FOR GAMMEL", b.status === "FRESH" ? "gray" : "amber")}</td></tr>`,
            ),
          )
          .join("")}</tbody></table></div>`
      : empty(
          "Ingen priser endnu",
          "Scan den valgte datatilstand. Feedfejl bliver aldrig erstattet af demo-priser.",
        )
  }`;
}
function historyTable(bets) {
  if (!bets.length)
    return empty(
      "Ingen registrerede væddemål",
      "Journalen bevarer alle beslutninger og resultater, også tab.",
    );
  return `<div class="table-wrap"><table><thead><tr><th>Tid / kamp</th><th>Udfald / book</th><th>Odds / luk</th><th>CLV</th><th>DDM p</th><th>Indsats</th><th>Resultat</th><th>P/L</th><th></th></tr></thead><tbody>${bets.map((b) => `<tr data-detail="${b.decision_id}" tabindex="0"><td class="event-cell"><strong>${esc(b.event.home)} / ${esc(b.event.away)}</strong><small>${date(b.placed_at)} · ${esc(b.model_version)}</small></td><td>${esc(b.selection)}<small class="muted" style="display:block">${esc(b.bookmaker)}</small></td><td class="mono">${fmt(b.odds)} / ${fmt(b.closing_odds)}</td><td class="mono ${color(b.clv)}">${pct(b.clv, true)}</td><td class="mono">${pct(b.p)}</td><td class="mono">${fmt(b.stake)}</td><td>${tag(b.status)}</td><td class="mono ${color(b.pnl)}">${b.status === "OPEN" ? "—" : fmt(b.pnl)}</td><td>${b.status === "OPEN" ? `<button class="row-button" data-settle="${esc(b.event_id)}" title="Registrer kampresultat" aria-label="Registrer resultat">${icon("check-check")}</button>` : ""}</td></tr>`).join("")}</tbody></table></div>`;
}
function portfolio() {
  const a = state.account;
  const opened = state.open_bets;
  return `${metricsStrip()}<div class="section-heading"><h2>Kapital og risiko</h2><div class="toolbar"><button id="add-funds">${icon("plus")}Tilføj pulje</button>${currentMode !== "DEMO" ? `<button id="settle-feed">${icon("check-check")}Hent resultater</button>` : ""}<button id="toggle-halt" class="danger">${icon("octagon-pause")}${a.halted ? "Ophæv stop" : "Stop nye registreringer"}</button></div></div><div class="two-col"><section class="band"><h3>Eksponeringslofter</h3><div class="risk-bars" style="margin-top:20px">${[
    ["Portefølje", a.exposure, 0.1],
    [
      "Største kamp",
      Math.max(
        0,
        ...Object.values(
          opened.reduce(
            (x, b) => ((x[b.event_id] = (x[b.event_id] || 0) + b.stake), x),
            {},
          ),
        ),
      ),
      0.02,
    ],
    [
      "Største sport",
      Math.max(
        0,
        ...Object.values(
          opened.reduce(
            (x, b) => ((x[b.sport] = (x[b.sport] || 0) + b.stake), x),
            {},
          ),
        ),
      ),
      0.05,
    ],
  ]
    .map(
      ([name, v, cap]) =>
        `<div class="risk-line"><span>${name}</span><div class="risk-track"><span style="width:${a.equity ? Math.min(100, (v / a.equity / cap) * 100) : 0}%"></span></div><span class="mono muted">${pct(a.equity ? v / a.equity : 0)} / ${pct(cap)}</span></div>`,
    )
    .join(
      "",
    )}</div></section><section class="band"><h3>${a.halted ? "GLOBALT STOP AKTIVT" : "Konservativ risikoprofil"}</h3><p>¼ Kelly på den konservative sandsynlighed. Maks. 1% pr. bet, 2% pr. kamp, 3% pr. hold, 4% pr. liga, 5% pr. sport/dag og 10% samlet.</p><p>${currentMode === "REAL" ? "EUR-beløbet er et manuelt regnskab over din bookmakerpulje. DDM opbevarer ingen midler." : "Puljen er virtuel og opbevares som regnskab i den lokale SQLite-journal."}</p></section></div><div class="section-heading" style="margin-top:24px"><h2>Åbne væddemål</h2><span class="meta">${opened.length} AKTIVE</span></div>${historyTable(opened)}`;
}
function strategyView() {
  const m = state.metrics;
  return `<section class="band"><div class="section-heading"><div><h2>Prisdivergens / h2h</h2><p>Reference-bookmakere uden den bookmaker, der tilbyder prisen. Strategiversion price-divergence-1.</p></div>${tag(state.strategy.state, "gray")}</div><div class="stat-grid">${metric("AFGJORTE", String(m.decisive), "Mindst 500 kræves til LIVE")}${metric("OMSÆTNING", money(m.turnover), currentMode)}${metric("YIELD / ROI", pct(m.roi), m.roi_ci ? `${pct(m.roi_ci[0])} til ${pct(m.roi_ci[1])}` : "Utilstrækkelig stikprøve", color(m.roi))}${metric("GENNEMSNITLIG CLV", pct(m.clv, true), `${m.clv_n} observerede priser`, color(m.clv))}</div><div class="toolbar"><label for="strategy-state" style="margin:0">Tilstand</label><select id="strategy-state">${["EXPERIMENT", "PAPER", "LIVE", "PAUSED", "REJECTED"].map((s) => `<option ${s === state.strategy.state ? "selected" : ""}>${s}</option>`).join("")}</select><button id="strategy-save">${icon("check")}Gem tilstand</button>${currentMode === "PAPER" ? `<button id="${state.scheduler.run_sports && state.scheduler.running ? "paper-stop" : "paper-start"}">${icon(state.scheduler.run_sports && state.scheduler.running ? "pause" : "play")}${state.scheduler.run_sports && state.scheduler.running ? "Stop PAPER-drift" : "Start PAPER-drift"}</button>` : ""}</div><p>LIVE kræver ≥500 afgjorte PAPER-bets, ≥100 CLV-observationer, positiv CLV, positiv nedre ROI-grænse og Brier mindst på niveau med markedet. Kravene er en adgangsport, ikke et bevis på fremtidig profit.</p></section><section class="band"><h2>Versionsspecifik performance</h2>${state.versions.length ? `<div class="table-wrap" style="margin-top:18px"><table><thead><tr><th>Model</th><th>Afgjorte</th><th>Profit</th><th>ROI</th><th>CLV</th><th>Brier</th></tr></thead><tbody>${state.versions.map((v) => `<tr><td>${esc(v.version)}</td><td class="mono">${v.metrics.decisive}</td><td class="mono ${color(v.metrics.profit)}">${fmt(v.metrics.profit)}</td><td class="mono">${pct(v.metrics.roi)}</td><td class="mono">${pct(v.metrics.clv, true)}</td><td class="mono">${fmt(v.metrics.calibration.brier, 3)}</td></tr>`).join("")}</tbody></table></div>` : empty("Afventer journaldata", "Performance bliver aldrig blandet på tværs af modelversioner.")}</section>`;
}
function analytics() {
  const m = state.metrics,
    c = state.model_calibration;
  return `${metricsStrip()}<div class="two-col">${chartHTML("equity", "Realiseret og forventet", m.settled > 0)}<div class="chart-region"><h2>Kalibrering</h2>${c.n ? '<canvas id="calibration" role="img" aria-label="Forudsagt sandsynlighed og faktisk udfald"></canvas>' : '<div class="chart-empty">' + icon("chart-scatter") + "<span>Afventer observerede udfald</span><small>Ingen opdigtede sandsynligheder</small></div>"}</div></div><section class="band"><div class="stat-grid">${metric("BRIER / ALLE SIGNALER", fmt(c.brier, 3), `${c.events} kampe · WATCH og PASS inkluderet`)}${metric("MARKEDETS BRIER", fmt(state.model_baseline.brier, 3), "Samme observerede kampe")}${metric("LOG LOSS", fmt(c.log_loss, 3), "Straffer forkert sikkerhed")}${metric("KALIBRERINGSFEJL", pct(c.ece), "ECE · 10 intervaller")}</div><h3>Stikprøve og drawdown</h3><p>${m.decisive} afgjorte bets. Maksimalt observeret drawdown ${pct(m.drawdown)}. Hver statistik er baseret på den valgte konto. Små stikprøver kan ikke afgøre, om en edge eksisterer.</p>${state.drift ? `<div class="error-banner">${esc(state.drift)}</div>` : ""}</section><section class="band"><div class="section-heading"><h2>Varians / Monte Carlo</h2><button id="monte-carlo">${icon("chart-network")}Simuler 2.000 forløb</button></div><div id="mc-results">${empty("Afventer simulering", "Baseres på journalens odds, indsatser og modelsandsynligheder. En modelantagelse er ikke dokumentation for edge.")}</div></section>`;
}
function labView() {
  const d = labData || {},
    ev = d.evaluation;
  return `<div class="stat-grid">${metric("HISTORISKE KAMPE", String(d.historical_matches || 0), "Resultater med available_at")}${metric("ODDS-SNAPSHOTS", String(d.historical_odds || 0), "Kun pre-match observationer")}${metric("MODEL", ev ? esc(ev.model_version) : "—", "Poisson · eksperiment")}${metric("HOLDOUT", ev ? "FROSSET" : "AFVENTER", "60 / 20 / 20 kronologisk")}</div><section class="band"><h2>Datasæt</h2><div class="toolbar" style="margin-top:18px"><label class="primary" style="display:inline-flex;align-items:center;gap:8px;padding:8px 12px;border-radius:4px;cursor:pointer;margin:0">${icon("upload")}Importer resultater<input id="import-results" type="file" accept=".csv" hidden></label><label style="display:inline-flex;align-items:center;gap:8px;border:1px solid var(--line);padding:8px 12px;border-radius:4px;cursor:pointer;margin:0">${icon("upload")}Importer odds<input id="import-odds" type="file" accept=".json" hidden></label><button id="evaluate-history">${icon("play")}Kør kronologisk evaluering</button></div><p>Resultat-CSV: id, league, home, away, start, available_at, home_goals, away_goals, source. Odds-JSON: The Odds API-events med ekstra received_at. Event-id og holdnavne skal være identiske. Mindst 300 kampe kræves.</p></section><section class="band"><h2>Train / validation / holdout</h2>${
    ev
      ? `<div class="table-wrap" style="margin-top:18px"><table><thead><tr><th>Periode</th><th>Kampe</th><th>Brier (multiklasse)</th><th>Log loss</th></tr></thead><tbody>${Object.entries(
          ev.partitions,
        )
          .map(
            ([key, v]) =>
              `<tr><td>${esc(key)}</td><td class="mono">${v.events}</td><td class="mono">${fmt(v.brier, 3)}</td><td class="mono">${fmt(v.log_loss, 3)}</td></tr>`,
          )
          .join(
            "",
          )}<tr><td>Kalibreret holdout</td><td class="mono">${ev.calibrated_holdout.events}</td><td class="mono">${fmt(ev.calibrated_holdout.brier, 3)}</td><td class="mono">${fmt(ev.calibrated_holdout.log_loss, 3)}</td></tr></tbody></table></div><p>Dataset ${esc(ev.dataset_hash.slice(0, 16))} · ${date(ev.created_at)}. Kalibrering ${esc(ev.calibration_version)}. Replay: ${ev.backtest.events_with_prices} kampe med historiske priser, ${ev.backtest.metrics.decisive} bets.</p><details><summary>Forudsætninger og begrænsninger</summary><ul>${ev.limitations.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></details>`
      : empty(
          "Ingen historisk evaluering endnu",
          "Importér et dokumenteret datasæt. Syntetiske prisforløb bruges ikke som bevis på profit.",
        )
  }</section>`;
}
function modelView() {
  return `<section class="band"><h2>Probabilistiske modeller</h2><div class="table-wrap" style="margin-top:18px"><table><thead><tr><th>Model</th><th>Grundlag</th><th>Kalibrering</th><th>Tilstand</th></tr></thead><tbody><tr><td>leave-book-out-power-1</td><td>Komplette h2h-priser; ≥3 reference-books</td><td>Ikke valideret</td><td>${tag("EKSPERIMENT", "amber")}</td></tr><tr><td>poisson-shrink-1</td><td>Historiske mål; decay 180 dage; prior 20 kampe</td><td>Validation-isotonic i strategilab</td><td>${tag("EKSPERIMENT", "amber")}</td></tr></tbody></table></div><p>Poisson aktiveres kun med mindst 100 ligakampe og 15 relevante hjemme-/udekampe for hvert hold. Ellers anvendes markedskonsensus. Usikkerheden er en konservativ følsomhedsbuffer, ikke et statistisk konfidensinterval.</p></section><section class="band"><h2>Modelhelbred</h2><div class="health-line"><span>Aktuel vurdering</span>${tag(state.model_health, "gray")}</div><div class="health-line"><span>Observationsgrundlag</span><span class="mono">${state.metrics.decisive} afgjorte bets</span></div><div class="health-line"><span>AI som kvantitativ kilde</span><span class="positive">Deaktiveret</span></div><div class="health-line"><span>Ukontrolleret selvændring</span><span class="positive">Deaktiveret</span></div><p>Hver beslutning har versions-id, feature-version, data-hash, kalibreringsversion og originalt input. Drift kontrolleres først med mindst 200 observationer. Ingen model forfremmes automatisk efter en heldig periode.</p></section>`;
}
function settingsView() {
  const s = settingsData;
  if (!s) return empty("Henter indstillinger", "");
  const provider = (id) => s.providers.find((p) => p.id === id);
  const keyField = (id, label) => {
    const p = provider(id);
    return `<div><label for="${id}">${label}</label><input id="${id}" type="password" autocomplete="off" placeholder="Ny nøgle eller behold eksisterende"><div class="key-status">${p?.configured ? "Konfigureret · " + esc(p.masked) : "Ikke konfigureret"}<label class="check-label" style="margin-top:6px"><input type="checkbox" data-clear="${id}">Fjern gemt nøgle</label></div></div>`;
  };
  return `<form id="settings-form" class="settings-layout"><section class="settings-row"><div><h3>Markedsdata</h3><p>Op til tre sportsgrene. Scanning sker ved din handling, med genbrug af nylige svar.</p></div><div class="form-fields">${keyField("odds_api_key", "The Odds API")}<div><label for="sports-keys">Sport-keys</label><input id="sports-keys" value="${esc(s.sports_keys)}" placeholder="soccer_epl,soccer_denmark_superliga"></div><div><label for="odds-budget">Maks. feedkald pr. UTC-dag</label><input id="odds-budget" type="number" min="0" max="1000" value="${s.odds_daily_request_limit}"></div><div><label for="sports-interval">PAPER-interval i sekunder</label><input id="sports-interval" type="number" min="300" max="86400" value="${s.sports_scan_interval}"></div></div></section><section class="settings-row"><div><h3>Valgfri AI-forklaring</h3><p>Claude forklarer eksisterende tal. Ingen AI-modeller må levere sandsynligheder eller indsatser.</p></div><div class="form-fields">${keyField("anthropic_api_key", "Anthropic API-nøgle")}<div><label for="ai-model">Model-id</label><input id="ai-model" value="${esc(s.anthropic_model)}"></div><div class="full"><label class="check-label"><input id="ai-enabled" type="checkbox" ${s.ai_research_enabled ? "checked" : ""}>Tillad AI-forklaring ved manuelt klik</label></div><div><label for="ai-calls">Maks. kald pr. UTC-dag</label><input id="ai-calls" type="number" min="0" max="100" value="${s.ai_daily_call_limit}"></div><div><label for="ai-tokens">Dagligt tokenbudget</label><input id="ai-tokens" type="number" min="0" max="1000000" value="${s.ai_daily_token_budget}"></div><div class="full small muted">${s.ai_usage?.calls ?? 0}/${s.ai_daily_call_limit} kald · ${s.ai_usage?.reserved_tokens ?? 0} reserverede tokens · ingen web-søgning eller automatisk AI-cyklus</div></div></section><section class="settings-row"><div><h3>Andre AI-nøgler</h3><p>Opbevares lokalt. OpenAI og Gemini har ingen aktiv motor og bruger ingen tokens.</p></div><div class="form-fields">${keyField("openai_api_key", "OpenAI")}${keyField("gemini_api_key", "Gemini")}</div></section><section class="settings-row"><div><h3>Beskeder</h3><p>Telegram fra kryptomotoren. Beskedfejl kan ses i systemstatus og stopper ikke en handelscyklus.</p></div><div class="form-fields">${keyField("telegram_bot_token", "Telegram bot-token")}<div><label for="telegram-chat">Chat-id</label><input id="telegram-chat" value="${esc(s.telegram_chat_id)}"></div><label class="check-label"><input id="notify-enabled" type="checkbox" ${s.notify_enabled ? "checked" : ""}>Tillad beskeder</label><button id="test-notify" type="button">${icon("send")}Send test</button></div></section><div class="save-row"><button type="submit" class="primary">${icon("save")}Gem indstillinger</button><span class="muted small">Nøgler returneres aldrig i klartekst til browseren.</span></div></form><section class="band"><h2>Datakilder og systemstatus</h2>${state.providers.length ? state.providers.map((p) => `<div class="health-line"><span>${esc(p.provider)} · ${esc(p.message)}</span>${tag(p.ok ? "ONLINE" : "FEJL", p.ok ? "green" : "red")}</div>`).join("") : empty("Ingen live-feedkald endnu", "Tilføj en Odds API-nøgle, vælg PAPER og scan.")}<p>Sportsjournal: lokal SQLite. Krypto: eksisterende Coinbase-forbindelse i kryptoterminalen. Kontoens midler bliver hos din bookmaker eller børs.</p></section>`;
}
function renderView() {
  if (!state) return;
  modeBanner();
  const views = {
    overview,
    opportunities: () =>
      filterToolbar() + opportunityTable(filteredOpportunities()),
    markets,
    portfolio,
    strategies: strategyView,
    analytics,
    lab: labView,
    models: modelView,
    history: () =>
      `<div class="toolbar"><div class="search">${icon("search")}<input id="history-search" value="${esc(historyFilters.q)}" placeholder="Søg historik" aria-label="Søg historik"></div><select id="history-status" aria-label="Resultat"><option value="">Alle resultater</option>${["OPEN", "WON", "LOST", "VOID"].map((s) => `<option ${historyFilters.status === s ? "selected" : ""}>${s}</option>`).join("")}</select><select id="history-sort" aria-label="Sortering"><option value="time">Nyeste</option><option value="odds" ${historyFilters.sort === "odds" ? "selected" : ""}>Højeste odds</option><option value="pnl" ${historyFilters.sort === "pnl" ? "selected" : ""}>Største P/L</option></select><span class="spacer"></span><button id="history-save" class="icon-button" title="Gem historikvisning">${icon("bookmark-plus")}</button><button id="history-load" class="icon-button" title="Hent historikvisning">${icon("bookmark")}</button><a href="/api/terminal/history/export?mode=${currentMode}"><button>${icon("download")}CSV eksport</button></a></div><div id="history-table">${historyPage()}</div>`,
    settings: settingsView,
    crypto: cryptoView,
  };
  $("#view").innerHTML = views[currentView]();
  icons();
  drawCharts();
}
function drawLine(id, points, keys = ["equity", "expected"], yPercent = false) {
  const canvas = $("#" + id);
  if (!canvas) return;
  const dpr = window.devicePixelRatio || 1,
    width = canvas.clientWidth,
    height = canvas.clientHeight;
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  if (points.length < 2) {
    ctx.fillStyle = "#6b7280";
    ctx.font = "12px Arial";
    ctx.textAlign = "center";
    ctx.fillText(
      "Afventer flere observationer i perioden",
      width / 2,
      height / 2,
    );
    return;
  }
  const pad = { l: 52, r: 15, t: 20, b: 30 };
  const values = points
    .flatMap((p) => keys.map((k) => p[k]))
    .filter(Number.isFinite);
  let lo = Math.min(...values),
    hi = Math.max(...values);
  if (lo === hi) {
    lo -= 1;
    hi += 1;
  }
  const delta = (hi - lo) * 0.15;
  lo -= delta;
  hi += delta;
  const X = (i) => pad.l + ((width - pad.l - pad.r) * i) / (points.length - 1),
    Y = (v) =>
      height - pad.b - ((height - pad.b - pad.t) * (v - lo)) / (hi - lo);
  ctx.font = "10px Consolas";
  ctx.textAlign = "right";
  ctx.strokeStyle = "#eceef1";
  ctx.lineWidth = 1;
  for (let i = 0; i < 4; i++) {
    const v = lo + ((hi - lo) * i) / 3,
      y = Y(v);
    ctx.beginPath();
    ctx.moveTo(pad.l, y);
    ctx.lineTo(width - pad.r, y);
    ctx.stroke();
    ctx.fillStyle = "#878c96";
    ctx.fillText(yPercent ? pct(v) : fmt(v, 0), pad.l - 9, y + 3);
  }
  keys.forEach((key, index) => {
    ctx.strokeStyle = ["#16796b", "#a1a5ae", "#b53632"][index];
    ctx.lineWidth = index === 0 ? 2 : 1.3;
    ctx.setLineDash(index === 1 ? [5, 4] : []);
    ctx.beginPath();
    points.forEach((p, i) =>
      i ? ctx.lineTo(X(i), Y(p[key])) : ctx.moveTo(X(i), Y(p[key])),
    );
    ctx.stroke();
  });
  ctx.setLineDash([]);
  ctx.textAlign = "left";
  ctx.fillStyle = "#878c96";
  ctx.fillText(points[0].ts ? date(points[0].ts) : "START", pad.l, height - 8);
  ctx.textAlign = "right";
  ctx.fillText(
    points.at(-1).ts ? date(points.at(-1).ts) : `${points.length - 1} KAMPE`,
    width - pad.r,
    height - 8,
  );
  canvas.onmousemove = (e) => {
    const index = Math.max(
      0,
      Math.min(
        points.length - 1,
        Math.round(
          ((e.offsetX - pad.l) / (width - pad.l - pad.r)) * (points.length - 1),
        ),
      ),
    );
    let tip = $(".chart-tooltip");
    if (!tip) {
      tip = document.createElement("div");
      tip.className = "chart-tooltip";
      document.body.appendChild(tip);
    }
    tip.textContent = keys
      .map(
        (k) =>
          `${k}: ${yPercent ? pct(points[index][k]) : fmt(points[index][k])}`,
      )
      .join(" · ");
    tip.style.left =
      Math.min(window.innerWidth - tip.offsetWidth - 15, e.clientX + 10) + "px";
    tip.style.top = e.clientY - 35 + "px";
  };
  canvas.onmouseleave = () => $(".chart-tooltip")?.remove();
}
function drawCalibration() {
  const canvas = $("#calibration");
  if (!canvas) return;
  const bins = state.model_calibration.bins,
    dpr = devicePixelRatio || 1,
    w = canvas.clientWidth,
    h = canvas.clientHeight;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  const X = (p) => 45 + p * (w - 65),
    Y = (p) => h - 35 - p * (h - 55);
  ctx.font = "10px Consolas";
  ctx.strokeStyle = "#e5e7eb";
  ctx.fillStyle = "#858b95";
  for (let i = 0; i <= 4; i++) {
    const p = i / 4;
    ctx.beginPath();
    ctx.moveTo(X(p), Y(0));
    ctx.lineTo(X(p), Y(1));
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(X(0), Y(p));
    ctx.lineTo(X(1), Y(p));
    ctx.stroke();
    ctx.fillText(pct(p), 5, Y(p) + 3);
    ctx.fillText(pct(p), X(p) - 10, h - 14);
  }
  ctx.strokeStyle = "#a2a7b0";
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(X(0), Y(0));
  ctx.lineTo(X(1), Y(1));
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = "#15766a";
  bins.forEach((b) => {
    ctx.beginPath();
    ctx.arc(
      X(b.predicted),
      Y(b.actual),
      Math.min(9, 3 + Math.sqrt(b.n) / 4),
      0,
      Math.PI * 2,
    );
    ctx.fill();
  });
}
function drawCharts() {
  if (!state) return;
  let curve = state.metrics.curve;
  const cut =
    chartRange === "ALL"
      ? 0
      : chartRange === "YTD"
        ? new Date(new Date().getFullYear(), 0, 1).getTime() / 1000
        : Date.now() / 1000 -
          ({ "7D": 7, "30D": 30, "3M": 90 }[chartRange] || 0) * 86400;
  if (cut) curve = curve.filter((p) => p.ts && p.ts >= cut);
  drawLine("equity", curve);
  drawCalibration();
}
async function showDetail(id) {
  const detail = await api(`/api/terminal/decisions/${id}?mode=${currentMode}`);
  activeDecision = detail.decision;
  activeDecision.idempotency_key = crypto.randomUUID();
  const o = activeDecision;
  $("#detail-title").textContent = `${o.home} / ${o.away}`;
  $("#detail-body").innerHTML =
    `<div class="section-heading"><span>${esc(o.name)} · h2h · ${esc(o.league)}</span>${tag(o.action)}</div><div class="analysis-metrics">${metric("TILBUDTE ODDS", fmt(o.odds), esc(o.book_title))}${metric("FAIR ODDS", fmt(o.fair_odds), "DDM-estimat")}${metric("MINIMUM ODDS", fmt(o.min_odds), "Konservativ p + 2% EV")}${metric("INDSATS", money(o.stake), currentMode)}</div><div class="analysis-metrics">${metric("RÅ IMPLICIT P", pct(o.implied_p), `Margin ${pct(o.margin)}`)}${metric("NO-VIG MARKED", pct(o.market_p), `${o.reference_count} reference-books`)}${metric("DDM ESTIMAT", pct(o.p), `Buffer ±${fmt((o.uncertainty || 0) * 100, 1)} procentpoint`)}${metric("ROBUST EV", pct(o.robust_ev, true), `EV ${pct(o.ev, true)}`, color(o.robust_ev))}</div><div class="analysis-columns"><section><h3>Markeds- og modelsignaler</h3><ul>${o.reasons.map((x) => `<li>${esc(x)}</li>`).join("")}</ul><p class="small muted">${esc(o.estimate?.basis || "Intet modelgrundlag")} · Datakvalitet ${esc(o.quality)}. Likviditet: ukendt.</p></section><section><h3>Risiko og modargumenter</h3><ul>${o.counterarguments.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></section></div><h3>Prisgrundlaget</h3><div class="table-wrap" style="margin-top:10px"><table><thead><tr><th>Bookmaker</th><th>Odds</th><th>EV</th><th>Observeret</th><th>Status</th></tr></thead><tbody>${o.books.map((b) => `<tr><td>${esc(b.book)}</td><td class="mono">${fmt(b.odds)}</td><td class="mono ${color(b.ev)}">${pct(b.ev, true)}</td><td>${date(b.updated_at)}</td><td>${tag(b.status, b.status === "FRESH" ? "gray" : "amber")}</td></tr>`).join("")}</tbody></table></div><div class="detail-actions">${o.action === "BET" && currentMode !== "REAL" ? `<button id="paper-bet" class="primary">${icon("check")}Registrer ${currentMode === "DEMO" ? "demo" : "paper"}-bet</button>` : ""}${o.action === "BET" && currentMode === "REAL" ? '<label>Faktiske odds<input id="actual-odds" type="number" step=".01" min="1.01"></label><label>Faktisk indsats<input id="actual-stake" type="number" step=".01" min=".01"></label><button id="paper-bet" class="primary">Registrer manuelt bet</button>' : ""}<button id="explain-decision">${icon("message-square-text")}Forklar beslutning</button><span class="small muted">Udløber ${date(o.expires_at)}</span></div><p id="explanation" class="small muted"></p><details><summary>Originalt input og modelversion</summary><pre class="details-code">${esc(JSON.stringify({ decision: detail.recorded_decision, availability: o, snapshot: detail.snapshot }, null, 2))}</pre></details>`;
  icons();
  $("#detail").showModal();
}
async function saveSettings() {
  const s = settingsData;
  const payload = {
    anthropic_model: $("#ai-model").value,
    ai_research_enabled: $("#ai-enabled").checked,
    ai_web_search_enabled: false,
    ai_daily_call_limit: Number($("#ai-calls").value),
    ai_daily_token_budget: Number($("#ai-tokens").value),
    sports_keys: $("#sports-keys").value,
    odds_daily_request_limit: Number($("#odds-budget").value),
    sports_scan_interval: Number($("#sports-interval").value),
    telegram_chat_id: $("#telegram-chat").value,
    notify_enabled: $("#notify-enabled").checked,
  };
  for (const key of [
    "odds_api_key",
    "anthropic_api_key",
    "openai_api_key",
    "gemini_api_key",
    "telegram_bot_token",
  ]) {
    payload[key] = $("#" + key).value;
    payload["clear_" + key] = $(`[data-clear=${key}]`).checked;
  }
  settingsData = await api("/api/settings", payload);
  renderView();
  toast("Indstillinger gemt lokalt");
}
function openFund() {
  const descriptions = {
    DEMO: "Tilføjer virtuelle EUR til demo-kontoen.",
    PAPER: "Tilføjer virtuelle EUR til paper-kontoen. Ingen penge overføres.",
    REAL: "Registrerer dit eget indbetalte beløb som regnskab. DDM modtager eller opbevarer ikke pengene.",
  };
  $("#fund-title").textContent = "Tilføj pulje / " + currentMode;
  $("#fund-note").textContent = descriptions[currentMode];
  $("#fund-amount").value = "";
  $("#fund").showModal();
  $("#fund-amount").focus();
}
async function settlePrompt(eventId) {
  const event = (
    state.bets.find((b) => b.event_id === eventId) ||
    historyData.bets.find((b) => b.event_id === eventId)
  )?.event;
  if (!event) return;
  const winner = prompt(
    `Registrer dokumenteret resultat for ${event.home} / ${event.away}. Skriv HOME, DRAW, AWAY eller VOID. Resultatet kan ikke overskrives.`,
  );
  if (!winner) return;
  await api("/api/terminal/settle", {
    mode: currentMode,
    event_id: eventId,
    winner: winner.toUpperCase() === "VOID" ? null : winner.toUpperCase(),
    void: winner.toUpperCase() === "VOID",
  });
  await refresh();
  toast("Resultatet er registreret");
}
document.addEventListener("click", (event) => {
  const target = event.target.closest("button,[data-detail],[data-view]");
  if (!target) return;
  if (target.dataset.close) {
    $("#" + target.dataset.close).close();
    return;
  }
  if (target.dataset.view) {
    action(() => navigate(target.dataset.view));
    return;
  }
  if (target.dataset.mode) {
    currentMode = target.dataset.mode;
    document
      .querySelectorAll("[data-mode]")
      .forEach((b) =>
        b.classList.toggle("selected", b.dataset.mode === currentMode),
      );
    state = null;
    $("#view").innerHTML =
      '<div class="loading-state">Henter ' + currentMode + "-journal</div>";
    action(async () => {
      await refresh();
      if (currentView === "settings") await navigate("settings");
    });
    return;
  }
  if (target.dataset.settle) {
    event.stopPropagation();
    action(() => settlePrompt(target.dataset.settle));
    return;
  }
  if (target.dataset.detail) {
    action(() => showDetail(target.dataset.detail));
    return;
  }
  if (target.dataset.range) {
    chartRange = target.dataset.range;
    renderView();
    return;
  }
  const handlers = {
    "history-prev": async () => {
      historyFilters.page--;
      await loadHistory();
      renderView();
    },
    "history-next": async () => {
      historyFilters.page++;
      await loadHistory();
      renderView();
    },
    "history-save": async () => {
      localStorage.setItem("ddm-history-view", JSON.stringify(historyFilters));
      toast("Historikvisning gemt");
    },
    "history-load": async () => {
      const saved = localStorage.getItem("ddm-history-view");
      if (saved) historyFilters = JSON.parse(saved);
      await loadHistory();
      renderView();
    },
    scan: () => (currentView === "crypto" ? cryptoCycle() : scan()),
    halt: async () => {
      if (currentView === "crypto") {
        if (!confirm("Sælg/luk alle kryptopositioner og stop driften?")) return;
        await api("/api/live/flatten", {});
        await refresh();
        return;
      }
      await api("/api/terminal/halt", {
        mode: currentMode,
        halted: !state.account.halted,
      });
      await refresh();
    },
    "toggle-halt": async () => {
      await api("/api/terminal/halt", {
        mode: currentMode,
        halted: !state.account.halted,
      });
      await refresh();
    },
    "add-funds": async () => openFund(),
    "nav-menu": async () => {
      $("#mobile-navigation").innerHTML = Object.entries(titles)
        .map(([v, t]) => `<button data-view="${v}">${esc(t)}</button>`)
        .join("");
      $("#navigation-menu").showModal();
    },
    "paper-start": async () => {
      const s = state.scheduler;
      await api("/api/scheduler/start", {
        interval: s.interval,
        run_live: s.running && s.run_live,
        run_sim: s.running && s.run_sim,
        run_sports: true,
      });
      await refresh();
      toast("PAPER-drift startet");
    },
    "paper-stop": async () => {
      const s = state.scheduler;
      if (s.run_live || s.run_sim)
        await api("/api/scheduler/start", {
          interval: s.interval,
          run_live: s.run_live,
          run_sim: s.run_sim,
          run_sports: false,
        });
      else await api("/api/scheduler/stop", {});
      await refresh();
      toast("PAPER-drift stoppet");
    },
    "settle-feed": async () => {
      const r = await api("/api/terminal/settle-feed", { mode: currentMode });
      await refresh();
      toast(`${r.settled} bets afregnet fra resultat-feed`);
    },
    "strategy-save": async () => {
      await api("/api/terminal/strategy", {
        mode: currentMode,
        state: $("#strategy-state").value,
      });
      await refresh();
      toast("Strategitilstand gemt; scan for nye beslutninger");
    },
    "save-view": async () => {
      localStorage.setItem("ddm-filter-view", JSON.stringify(filters));
      toast("Filtervisning gemt");
    },
    "load-view": async () => {
      const saved = localStorage.getItem("ddm-filter-view");
      if (saved) filters = JSON.parse(saved);
      renderView();
    },
    "paper-bet": async () => {
      const d = activeDecision;
      const result = await api("/api/terminal/bets", {
        mode: currentMode,
        decision_id: d.id,
        idempotency_key: d.idempotency_key,
        odds: $("#actual-odds") ? Number($("#actual-odds").value) : undefined,
        stake: $("#actual-stake")
          ? Number($("#actual-stake").value)
          : undefined,
      });
      $("#detail").close();
      await refresh();
      toast(
        result.duplicate
          ? "Allerede registreret"
          : "Bet registreret i journalen",
      );
    },
    "explain-decision": async () => {
      const b = $("#explain-decision");
      b.disabled = true;
      try {
        const r = await api("/api/terminal/explain", {
          mode: currentMode,
          decision_id: activeDecision.id,
        });
        $("#explanation").textContent = r.text;
      } finally {
        b.disabled = false;
      }
    },
    "test-notify": async () => {
      const r = await api("/api/notify/test", {});
      toast(r.message);
    },
    "evaluate-history": async () => {
      const b = $("#evaluate-history");
      b.disabled = true;
      b.textContent = "Evaluerer kronologisk";
      try {
        await api("/api/terminal/lab/evaluate", {});
        labData = await api("/api/terminal/lab");
        renderView();
      } finally {
        b.disabled = false;
      }
    },
    "monte-carlo": async () => {
      const r = await api("/api/terminal/monte-carlo", {
        mode: currentMode,
        runs: 2000,
      });
      $("#mc-results").innerHTML =
        `<div class="stat-grid">${metric("MEDIAN", money(r.median), "Betinget på modelens p")}${metric("5–95% INTERVAL", fmt(r.p05) + " / " + fmt(r.p95), "EUR efter sidste kamp")}${metric("CHANCE FOR MINUS", pct(r.negative_probability), `${r.events} kampe`)}${metric("RUIN / <10% AF START", pct(r.ruin_probability), `95% drawdown ${pct(r.drawdown_p95)}`)}</div><canvas id="mc-chart" style="width:100%;height:230px" role="img" aria-label="Monte Carlo percentilebaner"></canvas><p class="small muted">${esc(r.assumptions)}</p>`;
      drawLine("mc-chart", r.bands, ["p50", "p95", "p05"]);
    },
  };
  if (handlers[target.id]) action(handlers[target.id]);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && event.target.matches("tr[data-detail]"))
    action(() => showDetail(event.target.dataset.detail));
});
document.addEventListener("change", (event) => {
  const t = event.target;
  const map = {
    "filter-action": "action",
    "filter-sport": "sport",
    "filter-model": "model",
    "filter-sort": "sort",
  };
  if (map[t.id]) {
    filters[map[t.id]] = t.value;
    renderView();
  }
  if (t.id === "history-status" || t.id === "history-sort")
    action(filterHistory);
  if (t.id === "import-results" || t.id === "import-odds") {
    const file = t.files[0];
    if (!file) return;
    action(async () => {
      if (file.size > 5 * 1024 * 1024)
        throw new Error("Import må højst være 5 MB");
      const text = await file.text();
      const result = await api(
        "/api/terminal/lab/" + (t.id === "import-results" ? "results" : "odds"),
        t.id === "import-results"
          ? { csv: text }
          : { events: JSON.parse(text) },
      );
      labData = await api("/api/terminal/lab");
      renderView();
      toast(`${result.imported} rækker behandlet`);
    });
  }
});
async function filterHistory() {
  historyFilters = {
    q: $("#history-search").value,
    status: $("#history-status").value,
    sort: $("#history-sort").value,
    page: 1,
  };
  await loadHistory();
  if (currentView !== "history") return;
  $("#history-table").innerHTML = historyPage();
  icons();
}
document.addEventListener("input", (event) => {
  if (event.target.id === "search") {
    filters.q = event.target.value;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      const focus = $("#search") === document.activeElement,
        position = $("#search")?.selectionStart;
      renderView();
      if (focus) {
        $("#search").focus();
        $("#search").setSelectionRange(position, position);
      }
    }, 180);
  }
  if (event.target.id === "history-search") {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => action(filterHistory), 180);
  }
});
$("#settings-form")?.addEventListener("submit", (e) => e.preventDefault());
document.addEventListener("submit", (event) => {
  if (event.target.id === "settings-form") {
    event.preventDefault();
    action(() => saveSettings());
  }
  if (event.target.id === "fund-form") {
    event.preventDefault();
    action(async () => {
      await api("/api/terminal/deposit", {
        mode: currentMode,
        amount: Number($("#fund-amount").value),
      });
      $("#fund").close();
      await refresh();
      toast("Beløb tilføjet til journalen");
    });
  }
});
window.addEventListener("resize", () => {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(drawCharts, 180);
});
setInterval(
  () => ($("#clock").textContent = new Date().toLocaleTimeString("da-DK")),
  1000,
);
setInterval(() => {
  if (
    document.visibilityState === "visible" &&
    !loading &&
    !$("#detail").open &&
    !$("#fund").open &&
    !["settings", "lab"].includes(currentView)
  ) {
    refresh().catch((e) => {
      $("#heartbeat").textContent = "Ingen kontakt";
      $("#heartbeat-dot").classList.add("offline");
      error(e.message);
    });
  }
}, 15000);
action(async () => {
  await refresh(false);
  await navigate(
    location.hash.slice(1) ||
      (location.pathname === "/crypto" ? "crypto" : "overview"),
  );
  if (
    !state.opportunities.length &&
    currentMode === "DEMO" &&
    currentView !== "crypto"
  )
    await scan();
});
icons();
