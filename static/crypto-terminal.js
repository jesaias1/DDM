"use strict";
let cryptoData = null;
const cryptoReturn = (value) => (value == null ? "—" : fmt(value, 1) + "%");
async function loadCrypto() {
  cryptoData = await api("/api/live/status");
}
function cryptoView() {
  const c = cryptoData;
  if (!c) return empty("Afventer børsstatus", "");
  return `<div class="mode-banner">${tag(c.live ? "LIVE" : "TØR-KØRSEL", c.live ? "red" : "gray")}<span>Eksperimentel momentum-strategi. Ingen dokumenteret edge. Midler bliver hos ${esc(c.exchange)}.</span></div><div class="metric-strip">${metric("PULJE", fmt(c.equity) + ' <span class="unit">' + esc(c.quote) + "</span>", c.live ? "Børsens frie saldo + registrerede positioner" : "Virtuel pulje")}${metric("DISPONIBEL", fmt(c.cash) + ' <span class="unit">' + esc(c.quote) + "</span>", esc(c.exchange))}${metric("DAGENS AFKAST", cryptoReturn(c.risk.daily_return_pct), `Tabsloft ${fmt(c.risk.daily_loss_limit_pct, 1)}%`, color(c.risk.daily_return_pct))}${metric("SAMLET AFKAST", cryptoReturn(c.risk.total_return_pct), `Tabsloft ${fmt(c.risk.total_loss_limit_pct, 1)}%`, color(c.risk.total_return_pct))}${metric("RISIKOBREMSE", c.risk.halted ? "STOPPET" : "AKTIV", esc(c.risk.halt_reason || "Ingen stopgrænse ramt"), c.risk.halted ? "negative" : "positive")}</div><div class="toolbar"><button id="crypto-preflight">${icon("clipboard-check")}Preflight</button><button id="crypto-readiness">${icon("shield-check")}Kontroller testprofil</button><button id="crypto-start">${icon("play")}Start kryptodrift</button><button id="crypto-stop">${icon("pause")}Stop drift</button>${c.live ? "" : '<button id="crypto-reset">' + icon("wallet") + "Angiv virtuel pulje</button>"}${c.risk.halted ? '<button id="crypto-clear">' + icon("rotate-ccw") + "Ophæv risikobremse</button>" : ""}</div><pre id="crypto-log" class="details-code" role="status">${c.pending_order ? "Uafklaret børsordre. Afstem med børsen, før programmet kan fortsætte." : esc(state.scheduler.last_log.join("\n") || "Afventer cyklus")}</pre><div class="two-col"><section class="band"><h2>Eksponeringsprofil</h2><div class="health-line"><span>Maks. live-køb</span><span class="mono">${fmt(c.test_limits.max_live_stake)} ${esc(c.quote)}</span></div><div class="health-line"><span>Køb pr. dag</span><span class="mono">${c.test_limits.daily_buy_count} / ${c.test_limits.max_daily_buys}</span></div><div class="health-line"><span>Åbne positioner</span><span class="mono">${c.positions.length} / ${c.test_limits.max_open_positions}</span></div><div class="health-line"><span>Første canary-køb</span><span class="mono">${c.test_limits.canary_mode ? fmt(c.test_limits.canary_stake) + " " + esc(c.quote) : "Slået fra"}</span></div></section><section class="band"><h2>Driftsstatus</h2><div class="health-line"><span>Baggrundsmotor</span>${tag(state.scheduler.running && state.scheduler.run_live ? "KØRER" : "STOPPET", state.scheduler.running && state.scheduler.run_live ? "green" : "gray")}</div><div class="health-line"><span>Seneste cyklus</span><span class="mono">${date(state.scheduler.last_run)}</span></div><div class="health-line"><span>Trendfilter</span><span class="mono">SMA ${c.strategy.trend_len} dage</span></div><div class="health-line"><span>AI-forbrug</span><span class="positive">0 tokens</span></div><p>Uafklarede ordrer blokerer gentagelser. En kill switch bevarer positioner, hvis salget fejler. Stopgrænser kan ikke garantere mod tab ved prisgab eller nedetid.</p></section></div><div class="section-heading" style="margin-top:24px"><h2>Åbne positioner</h2></div>${c.positions.length ? `<div class="table-wrap"><table><thead><tr><th>Par</th><th>Mængde</th><th>Indgang</th><th>Aktuel pris</th><th>Top</th><th>Kostpris</th></tr></thead><tbody>${c.positions.map((p) => `<tr><td>${esc(p.symbol)}</td><td class="mono">${fmt(p.amount, 6)}</td><td class="mono">${fmt(p.entry)}</td><td class="mono">${fmt(p.now)}</td><td class="mono">${fmt(p.peak)}</td><td class="mono">${fmt(p.cost)} ${esc(c.quote)}</td></tr>`).join("")}</tbody></table></div>` : empty("Ingen åbne positioner", "Handler kræver et signal og godkendte risiko-/API-forhold.")}<section class="band"><h2>Lukkede positioner</h2>${c.history.length ? `<div class="table-wrap" style="margin-top:15px"><table><thead><tr><th>Tid</th><th>Par</th><th>P/L</th><th>Grund</th><th>Tilstand</th></tr></thead><tbody>${c.history.map((h) => `<tr><td>${date(h.ts)}</td><td>${esc(h.symbol)}</td><td class="mono ${color(h.pnl)}">${fmt(h.pnl)}</td><td>${esc(h.reason)}</td><td>${tag(h.live ? "LIVE" : "TØR", "gray")}</td></tr>`).join("")}</tbody></table></div>` : empty("Ingen lukkede positioner", "Kryptoresultater blandes aldrig med sportsjournalens performance.")}</section>`;
}
async function cryptoCycle() {
  const button = $("#scan");
  button.disabled = true;
  try {
    const r = await api("/api/live/cycle", {});
    await refresh();
    $("#crypto-log").textContent = r.log.join("\n");
  } finally {
    button.disabled = false;
  }
}
async function cryptoAction(id) {
  if (id === "crypto-preflight" || id === "crypto-readiness") {
    const result = await api(
      id === "crypto-preflight" ? "/api/live/preflight" : "/api/live/readiness",
    );
    $("#crypto-log").textContent =
      (result.ok ? "Kontroller bestået" : "Ikke klar") +
      "\n" +
      result.checks
        .map((c) => `${c.ok ? "OK" : "FEJL"} / ${c.name}: ${c.message}`)
        .join("\n");
    return;
  }
  if (id === "crypto-start")
    await api("/api/scheduler/start", {
      interval: 60,
      run_live: true,
      run_sim: false,
      run_sports: state.scheduler.running && state.scheduler.run_sports,
    });
  if (id === "crypto-stop") {
    if (state.scheduler.run_sports)
      await api("/api/scheduler/start", {
        interval: state.scheduler.interval,
        run_live: false,
        run_sim: false,
        run_sports: true,
      });
    else await api("/api/scheduler/stop", {});
  }
  if (id === "crypto-reset") {
    const amount = prompt("Virtuel kryptopulje i " + cryptoData.quote);
    if (amount === null) return;
    await api("/api/live/reset", {
      starting: Number(amount.replace(",", ".")),
    });
  }
  if (id === "crypto-clear") {
    if (!confirm("Ophæv risikobremsen og opret et nyt risikogrundlag?")) return;
    await api("/api/live/clear-halt", {});
  }
  await refresh();
}
document.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (button?.id.startsWith("crypto-")) action(() => cryptoAction(button.id));
});
