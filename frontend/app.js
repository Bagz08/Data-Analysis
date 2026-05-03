/* ═══════════════════════════════════════════════════════════
   Proposal Insight Engine — Frontend SPA  v7.0
   FastAPI ↔ Vanilla JS
════════════════════════════════════════════════════════════ */

const API = "";
const PASTEL = [
  "#FFB3BA","#FFCBA4","#FFF3A3","#B8F0B8","#A8D8FF",
  "#D4B8FF","#FFB8E8","#B8FFF0","#FFD6A4","#C8E6C9",
];

let state = {
  page: "dashboard",
  cluster: null,
  clusterCols: [],
  donutChart: null,
  barChart: null,
  kwCharts: [],
  kwResultsHtml: "",       // persisted keyword results
  kwChartsHtml: "",        // persisted charts section
  kwCluster: null          // which cluster the results belong to
};

// ══════════════════════════════════════════════════════════
// Navigation
// ══════════════════════════════════════════════════════════

function navigate(page, clusterName) {
  document.querySelectorAll(".page").forEach(p => p.classList.add("hidden"));
  document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
  state.page = page;
  if (clusterName !== undefined) state.cluster = clusterName;

  if (page === "dashboard") {
    show("page-dashboard"); id("nav-dashboard").classList.add("active");
    id("nav-back").classList.add("hidden");
    // Clear keyword data when leaving cluster detail
    state.kwResultsHtml = ""; state.kwChartsHtml = ""; state.kwCluster = null;
    _lastKwData = null;
    loadDashboard();
  } else if (page === "detail") {
    show("page-detail"); id("nav-back").classList.remove("hidden");
    loadDetail(state.cluster);
  } else if (page === "upload") {
    show("page-upload"); id("nav-upload").classList.add("active");
    id("nav-back").classList.add("hidden");
    // Clear keyword data when leaving cluster detail
    state.kwResultsHtml = ""; state.kwChartsHtml = ""; state.kwCluster = null;
    _lastKwData = null;
    loadHistory();
  }
}

// ══════════════════════════════════════════════════════════
// Utilities
// ══════════════════════════════════════════════════════════

function id(s) { return document.getElementById(s); }
function show(s) { id(s).classList.remove("hidden"); }
function hide(s) { id(s).classList.add("hidden"); }

async function apiFetch(path, opts = {}) {
  const res = await fetch(API + path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

function showToast(msg, type = "info", ms = 3500) {
  const t = id("toast");
  t.textContent = msg;
  t.className = "toast " + type;
  t.classList.remove("hidden");
  setTimeout(() => t.classList.add("hidden"), ms);
}

function esc(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

function escRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }

// ══════════════════════════════════════════════════════════
// Table builder (full horizontal scroll)
// ══════════════════════════════════════════════════════════

function buildTable(cols, rows, maxH = 500) {
  if (!cols.length) return '<div class="empty-state"><div class="empty-icon">📭</div>No data.</div>';
  const ths = cols.map(c => `<th>${esc(c)}</th>`).join("");
  const trs = rows.map(r => {
    return "<tr>" + cols.map(c => {
      const v = r[c] ?? "";
      return `<td title="${esc(String(v).slice(0,250))}">${esc(String(v).slice(0,300))}</td>`;
    }).join("") + "</tr>";
  }).join("");
  return `<div class="table-wrap" style="max-height:${maxH}px"><table class="data-table"><thead><tr>${ths}</tr></thead><tbody>${trs}</tbody></table></div>`;
}

function buildTableRaw(cols, rows, maxH = 500) {
  if (!cols.length) return '<div class="empty-state"><div class="empty-icon">📭</div>No data.</div>';
  const ths = cols.map(c => `<th>${esc(c)}</th>`).join("");
  const trs = rows.map(r => "<tr>" + cols.map(c => `<td>${r[c] ?? ""}</td>`).join("") + "</tr>").join("");
  return `<div class="table-wrap" style="max-height:${maxH}px"><table class="data-table"><thead><tr>${ths}</tr></thead><tbody>${trs}</tbody></table></div>`;
}

// ══════════════════════════════════════════════════════════
// Dashboard
// ══════════════════════════════════════════════════════════

async function loadDashboard() {
  const grid = id("cards-grid");
  grid.innerHTML = '<div class="loading-block"><div class="spinner"></div><span>Loading clusters…</span></div>';
  hide("charts-section");
  try {
    const data = await apiFetch("/api/clusters");
    id("total-badge").textContent = data.total;
    renderCards(data.clusters);
    if (data.total > 0) renderCharts(data.clusters, data.total);
  } catch (e) {
    grid.innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div>${esc(e.message)}</div>`;
    showToast("Dashboard error: " + e.message, "error");
  }
}

function renderCards(clusters) {
  id("cards-grid").innerHTML = clusters.map(c => `
    <div class="cluster-card" onclick="navigate('detail','${c.name.replace(/'/g,"\\'")}')">
      <div><div class="c-num">Cluster ${c.index+1}</div><div class="c-name">${esc(c.name)}</div></div>
      <div class="c-stats">
        <div class="c-stat"><span class="sn">${c.count}</span><span class="sl">Proposals</span></div>
        <div class="c-sep"></div>
        <div class="c-stat"><span class="sn">${c.rc_count}</span><span class="sl">Resp. Centers</span></div>
      </div>
    </div>`).join("");
}

function renderCharts(clusters, total) {
  show("charts-section");
  const CC = ["#7B1D1D","#9B2C2C","#C9A84C","#E8C97A","#DDD5C8","#6B6256","#F2EDE6","#4A0E0E","#B05A2F"];
  const nz = clusters.filter(c => c.count > 0);

  if (state.donutChart) state.donutChart.destroy();
  state.donutChart = new Chart(id("donut-chart").getContext("2d"), {
    type: "doughnut",
    data: { labels: nz.map(c => c.name.split(" ").at(-1)),
      datasets: [{ data: nz.map(c => c.count), backgroundColor: CC.slice(0,nz.length), borderWidth: 2, borderColor: "#fff" }] },
    options: { cutout: "55%", plugins: {
      legend: { position: "bottom", labels: { font: { family: "'Source Sans 3'" }, boxWidth: 12 } },
      tooltip: { callbacks: { label: ctx => ctx.label + ": " + ctx.raw + " proposals" } } },
      layout: { padding: 10 } },
    plugins: [{ id: "ct", afterDraw(ch) {
      const {ctx, chartArea:{left,right,top,bottom}} = ch;
      ctx.save(); ctx.font = "bold 22px 'Playfair Display',serif"; ctx.fillStyle = "#7B1D1D";
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(total, (left+right)/2, (top+bottom)/2); ctx.restore(); } }]
  });

  const sorted = [...clusters].sort((a,b) => a.count - b.count);
  if (state.barChart) state.barChart.destroy();
  state.barChart = new Chart(id("bar-chart").getContext("2d"), {
    type: "bar",
    data: { labels: sorted.map(c => c.name.length > 46 ? c.name.slice(0,44)+"…" : c.name),
      datasets: [{ data: sorted.map(c => c.count),
        backgroundColor: sorted.map((_,i) => interp("#F2EDE6","#7B1D1D", sorted.length>1? i/(sorted.length-1):1)),
        borderWidth: 0, borderRadius: 4 }] },
    options: { indexAxis: "y", plugins: { legend: { display: false },
      tooltip: { callbacks: { label: ctx => ctx.raw + " proposals" } } },
      scales: { x: { grid: { color: "#DDD5C8" }, ticks: { font: { family: "'Source Sans 3'" } } },
                y: { grid: { display: false }, ticks: { font: { size: 11, family: "'Source Sans 3'" } } } } }
  });
}

function interp(h1, h2, t) {
  const p = (s,i) => parseInt(s.slice(i,i+2),16);
  const r = Math.round(p(h1,1)+(p(h2,1)-p(h1,1))*t);
  const g = Math.round(p(h1,3)+(p(h2,3)-p(h1,3))*t);
  const b = Math.round(p(h1,5)+(p(h2,5)-p(h1,5))*t);
  return `rgb(${r},${g},${b})`;
}

// ══════════════════════════════════════════════════════════
// Cluster Detail
// ══════════════════════════════════════════════════════════

async function loadDetail(cn) {
  switchTab("proposals");
  id("detail-header").innerHTML = detailHeaderHtml(cn, "—", "—", "—");
  show("proposals-loading"); id("proposals-table-wrap").innerHTML = "";
  // Clear cached kw results if cluster changed
  if (state.kwCluster !== cn) {
    state.kwResultsHtml = ""; state.kwChartsHtml = ""; state.kwCluster = cn;
  }

  try {
    const data = await apiFetch("/api/proposals/" + encodeURIComponent(cn));
    id("detail-header").innerHTML = detailHeaderHtml(cn, data.count, data.rc_count, data.kw_count);
    hide("proposals-loading");
    if (!data.rows.length) {
      id("proposals-table-wrap").innerHTML = `<div class="empty-state"><div class="empty-icon">📭</div>No proposals for <strong>${esc(cn)}</strong> yet. Upload a file first.</div>`;
    } else {
      id("proposals-table-wrap").innerHTML = `<div class="table-caption">${data.count.toLocaleString()} proposal(s) from database</div>` + buildTable(data.columns, data.rows, 540);
    }
    state.clusterCols = data.columns;
    populateColSelects(data.columns);
  } catch (e) {
    hide("proposals-loading");
    id("proposals-table-wrap").innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div>${esc(e.message)}</div>`;
    showToast("Error: " + e.message, "error");
  }
}

function detailHeaderHtml(cn, p, r, k) {
  return `<div class="dh-left"><div class="gold-bar"></div><h1>${esc(cn)}</h1><div class="dh-sub">Cluster Detail View</div></div>
    <div class="dh-pills"><div class="dh-pill"><span class="dn">${p}</span><span class="dl">Proposals</span></div>
    <div class="dh-pill"><span class="dn">${r}</span><span class="dl">Resp. Centers</span></div>
    <div class="dh-pill"><span class="dn">${k}</span><span class="dl">Keywords</span></div></div>`;
}

function populateColSelects(cols) {
  const catSel = id("cat-col-select"), kwSel = id("kw-col-select");
  const opts = cols.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
  catSel.innerHTML = opts; kwSel.innerHTML = opts;
  const di = cols.findIndex(c => /desc|ppa|content|text|project/i.test(c));
  if (di >= 0) kwSel.selectedIndex = di;
}

function switchTab(tab) {
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".tab-panel").forEach(p => p.classList.add("hidden"));
  if (tab === "proposals") {
    id("tab-proposals-btn").classList.add("active"); show("tab-proposals");
  } else {
    id("tab-keywords-btn").classList.add("active"); show("tab-keywords");
    // Ensure dropdowns are populated with actual file columns
    if (state.clusterCols.length) populateColSelects(state.clusterCols);
    // Restore persisted results if available
    if (state.kwResultsHtml && state.kwCluster === state.cluster) {
      id("kw-charts-section").innerHTML = state.kwChartsHtml;
      id("kw-results").innerHTML = state.kwResultsHtml;
      rebuildKwCharts();
    }
  }
}

// ══════════════════════════════════════════════════════════
// Keyword Analysis
// ══════════════════════════════════════════════════════════

let _lastKwData = null; // cache for chart rebuild

async function runKeywords() {
  const catCol = id("cat-col-select").value;
  const kwCol  = id("kw-col-select").value;
  const btn    = id("btn-run-kw");
  if (!state.cluster) return;

  btn.disabled = true; btn.textContent = "Running…";
  show("kw-loading"); id("kw-results").innerHTML = ""; id("kw-charts-section").innerHTML = "";

  try {
    const data = await apiFetch("/api/keywords", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cluster_name: state.cluster, cat_col: catCol, kw_col: kwCol }),
    });
    hide("kw-loading");
    if (!data.results.length) {
      id("kw-results").innerHTML = '<div class="empty-state"><div class="empty-icon">🔍</div>No keyword results found.</div>';
      return;
    }
    _lastKwData = data;
    renderKwCharts(data);
    renderKwResults(data.results, kwCol);
    // Persist
    state.kwChartsHtml = id("kw-charts-section").innerHTML;
    state.kwResultsHtml = id("kw-results").innerHTML;
    state.kwCluster = state.cluster;
  } catch (e) {
    hide("kw-loading");
    id("kw-results").innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div>${esc(e.message)}</div>`;
    showToast("Analysis failed: " + e.message, "error");
  } finally { btn.disabled = false; btn.textContent = "⚡ Run KeyBERT Analysis"; }
}

function renderKwCharts(data) {
  const cd = data.chart_data;
  let html = '<div class="section-title">📊 Visual Analytics</div><div class="kw-charts-grid">';
  html += '<div class="chart-card"><div class="chart-title">Top 10 Keywords by Frequency</div><canvas id="kw-bar-chart"></canvas></div>';
  html += '<div class="chart-card"><div class="chart-title">Proposals per Category</div><canvas id="kw-donut-chart"></canvas></div>';
  if (cd.amount_col_name && cd.amount_per_cat.some(a => a > 0)) {
    html += '<div class="chart-card"><div class="chart-title">Total ' + esc(cd.amount_col_name) + ' per Category</div><canvas id="kw-amount-chart"></canvas></div>';
  }
  html += '</div>';
  id("kw-charts-section").innerHTML = html;

  // Destroy old charts
  state.kwCharts.forEach(c => { try { c.destroy(); } catch(e){} }); state.kwCharts = [];

  buildKwChartsFromData(cd);
}

function buildKwChartsFromData(cd) {
  // Chart 1: Top Keywords bar
  if (cd.top_keywords.length && id("kw-bar-chart")) {
    const c1 = new Chart(id("kw-bar-chart").getContext("2d"), {
      type: "bar",
      data: { labels: cd.top_keywords.map(k => k.kw),
        datasets: [{ label: "Frequency", data: cd.top_keywords.map(k => k.count),
          backgroundColor: cd.top_keywords.map((_,i) => PASTEL[i % PASTEL.length]),
          borderWidth: 0, borderRadius: 4 }] },
      options: { indexAxis: "y", plugins: { legend: { display: false } },
        scales: { x: { grid: { color: "#DDD5C8" }, title: { display: true, text: "Occurrences" } },
                  y: { grid: { display: false } } } }
    });
    state.kwCharts.push(c1);
  }

  // Chart 2: Proposals per category donut
  if (cd.categories.length && id("kw-donut-chart")) {
    const CC = ["#7B1D1D","#9B2C2C","#C9A84C","#E8C97A","#DDD5C8","#6B6256","#B05A2F","#4A0E0E","#F2EDE6"];
    const c2 = new Chart(id("kw-donut-chart").getContext("2d"), {
      type: "doughnut",
      data: { labels: cd.categories.map(c => c.length > 30 ? c.slice(0,28)+"…" : c),
        datasets: [{ data: cd.proposals_per_cat, backgroundColor: CC.slice(0, cd.categories.length), borderWidth: 2, borderColor: "#fff" }] },
      options: { cutout: "50%", plugins: { legend: { position: "bottom", labels: { font: { size: 10 }, boxWidth: 10 } } } }
    });
    state.kwCharts.push(c2);
  }

  // Chart 3: Amount per category
  if (cd.amount_col_name && cd.amount_per_cat.some(a => a > 0) && id("kw-amount-chart")) {
    const c3 = new Chart(id("kw-amount-chart").getContext("2d"), {
      type: "bar",
      data: { labels: cd.categories.map(c => c.length > 25 ? c.slice(0,23)+"…" : c),
        datasets: [{ label: cd.amount_col_name, data: cd.amount_per_cat,
          backgroundColor: cd.categories.map((_,i) => interp("#C9A84C","#7B1D1D", cd.categories.length>1? i/(cd.categories.length-1):1)),
          borderWidth: 0, borderRadius: 4 }] },
      options: { plugins: { legend: { display: false } },
        scales: { y: { grid: { color: "#DDD5C8" }, title: { display: true, text: cd.amount_col_name },
          ticks: { callback: v => "₱" + Number(v).toLocaleString() } },
          x: { grid: { display: false } } } }
    });
    state.kwCharts.push(c3);
  }
}

function rebuildKwCharts() {
  if (_lastKwData && _lastKwData.chart_data) {
    setTimeout(() => {
      state.kwCharts.forEach(c => { try { c.destroy(); } catch(e){} }); state.kwCharts = [];
      buildKwChartsFromData(_lastKwData.chart_data);
    }, 50);
  }
}

function renderKwResults(results, kwCol) {
  const container = id("kw-results");
  // Tally table
  let html = '<div class="section-title">Overall Tally Summary</div>';
  html += buildTable(
    ["Category", "Proposals", "Top Keywords"],
    results.map(r => ({
      "Category": r.cat, "Proposals": r.n,
      "Top Keywords": r.kws.slice(0,5).map(k => k.kw + " (" + k.count + ")").join(", ") || "—",
    })), 320);

  html += '<div class="section-title">Detailed Report by Category</div>';
  for (const r of results) {
    if (!r.kws.length) continue;
    const chips = r.kws.map((k,i) =>
      `<span class="kw-chip" style="background:${k.color}">${esc(k.kw.toUpperCase())} (${k.count})</span>`
    ).join(" ");

    const kwColorMap = Object.fromEntries(r.kws.map(k => [k.kw.toLowerCase(), k.color]));

    // Only show report columns (PPA Name, Description, Amount, Fund Account)
    const showCols = r.columns;
    const hlRows = r.rows.map(row => {
      const filtered = {};
      for (const c of showCols) {
        const v = String(row[c] ?? "");
        // Highlight only the kw_col
        filtered[c] = (c === kwCol) ? hlText(v, kwColorMap) : esc(v);
      }
      return filtered;
    });

    html += `<div class="kw-category-card">
      <div class="kw-category-title">${esc(r.cat)}<span class="kw-category-sub">(${r.n} proposals${r.amount > 0 ? " · ₱" + r.amount.toLocaleString() : ""})</span></div>
      <div class="kw-chips-label">Top Keywords</div><div class="kw-chips">${chips}</div></div>`;
    html += buildTableRaw(showCols, hlRows, 380) + "<br>";
  }
  container.innerHTML = html;
}

function hlText(text, map) {
  const kws = Object.keys(map).sort((a,b) => b.length - a.length);
  for (const kw of kws) {
    const pat = new RegExp("\\b(" + escRe(kw) + ")\\b", "gi");
    text = text.replace(pat, `<mark style="background:${map[kw]};color:#111;font-weight:700;border-radius:3px;padding:0 2px">$1</mark>`);
  }
  return text;
}

// ══════════════════════════════════════════════════════════
// Upload
// ══════════════════════════════════════════════════════════

function handleFileSelect(inp) { if (inp.files[0]) uploadFile(inp.files[0]); }

(function setupDragDrop() {
  const z = document.getElementById("upload-zone");
  if (!z) return;
  z.addEventListener("dragover", e => { e.preventDefault(); z.classList.add("dragover"); });
  z.addEventListener("dragleave", () => z.classList.remove("dragover"));
  z.addEventListener("drop", e => { e.preventDefault(); z.classList.remove("dragover"); if (e.dataTransfer.files[0]) uploadFile(e.dataTransfer.files[0]); });
  z.addEventListener("click", e => { if (e.target.tagName !== "LABEL") id("file-input").click(); });
})();

async function uploadFile(file) {
  const statusEl = id("upload-status"), pw = id("progress-wrap"), fill = id("progress-fill"), lbl = id("progress-label");

  statusEl.className = "upload-status info"; statusEl.textContent = 'Processing "' + file.name + '"…';
  statusEl.classList.remove("hidden"); pw.classList.remove("hidden");
  fill.style.width = "10%"; lbl.textContent = "Uploading…";

  const fd = new FormData();
  fd.append("file", file);

  let prog = 10;
  const iv = setInterval(() => { prog = Math.min(prog + Math.random() * 8, 88); fill.style.width = prog + "%"; }, 400);

  try {
    const data = await apiFetch("/api/upload", { method: "POST", body: fd });
    clearInterval(iv);

    fill.style.width = "100%"; lbl.textContent = "Done ✓";
    let msg = `✅ ${data.inserted.toLocaleString()} proposals uploaded from "${file.name}".`;
    if (data.unmatched > 0) {
      msg += ` (${data.unmatched} unrecognised rows auto-assigned to "${data.fallback_cluster}" — majority cluster.)`;
    }
    msg += ` Detected: Cluster: ${data.detected.cluster_col}`;
    if (data.detected.resp_col) msg += " · Resp: " + data.detected.resp_col;
    if (data.detected.content_col) msg += " · Content: " + data.detected.content_col;
    statusEl.className = "upload-status success"; statusEl.textContent = msg;
    showToast(data.inserted + " proposals uploaded!", "success");
    setTimeout(() => pw.classList.add("hidden"), 1500);
    loadHistory();
  } catch (e) {
    clearInterval(iv); fill.style.width = "0%"; pw.classList.add("hidden");
    statusEl.className = "upload-status error"; statusEl.textContent = "❌ Upload failed: " + e.message;
    showToast("Upload failed: " + e.message, "error");
  }
}


// ── History ──────────────────────────────────────────────

async function loadHistory() {
  const wrap = id("history-wrap");
  wrap.innerHTML = '<div class="loading-block"><div class="spinner"></div><span>Loading history…</span></div>';
  try {
    const data = await apiFetch("/api/history");
    if (!data.history.length) {
      wrap.innerHTML = '<div class="empty-state"><div class="empty-icon">📭</div>No files uploaded yet.</div>';
      return;
    }
    const rows = data.history.map(r => {
      const date = (r.upload_date || "").slice(0,19).replace("T"," ");
      const rc = r.row_count ? ` (${r.row_count} rows)` : "";
      return `<tr><td class="history-id">#${r.id}</td><td>${esc(r.filename||"")}${rc}</td><td>${date}</td>
        <td><button class="btn-danger" onclick="deleteHistory(${r.id},'${esc(r.filename||"").replace(/'/g,"\\'")}')">🗑 Delete</button></td></tr>`;
    }).join("");
    wrap.innerHTML = `<div class="history-table-wrap"><table class="history-table"><thead><tr>
      <th>ID</th><th>Filename</th><th>Upload Date (UTC)</th><th>Action</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  } catch (e) {
    wrap.innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div>${esc(e.message)}</div>`;
  }
}

async function deleteHistory(hid, fname) {
  if (!confirm(`Delete "${fname}" and all its proposal data? This cannot be undone.`)) return;
  try {
    await apiFetch("/api/history/" + hid, { method: "DELETE" });
    showToast("File and proposals deleted.", "success"); loadHistory();
  } catch (e) { showToast("Delete failed: " + e.message, "error"); }
}

// ══════════════════════════════════════════════════════════
// Init
// ══════════════════════════════════════════════════════════

document.addEventListener("DOMContentLoaded", () => navigate("dashboard"));
