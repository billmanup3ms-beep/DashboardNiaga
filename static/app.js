/* ==========================================================================
   DASHBOARD PIUTANG UP3 MAKASSAR SELATAN — FRONTEND CONTROLLER
   ========================================================================== */

const state = {
  tab: "cashin",
  page: 1,
  pageSize: 50,
  sortBy: "rpptl",
  sortDir: "desc",
  nonKogol12: true,
  filters: {
    ulp: "",
    rbm: "",
    lembar: "",
    kogol: "",
    segmen_tarif: "",
    tarif: "",
    daya: "",
    saldo_op: "gte",
    saldo_val: "",
    search: "",
    trend_ulp: "",
    trend_golongan: "",
  },
  kinerjaFilters: {
    periode: "",
    ulp: "",
  },
  billerRows: [],
  charts: {},
  filtersInitialized: false,
  sse: null,
};

// Formatting helpers (Indonesian locale)
const fmtNum = (n) => {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "0";
  return Math.round(Number(n)).toLocaleString("id-ID");
};

const fmtDec = (n, d = 2) => {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "0";
  return Number(n).toLocaleString("id-ID", {
    minimumFractionDigits: d,
    maximumFractionDigits: d,
  });
};

const fmtShortRp = (n) => {
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (abs >= 1e9) return `${sign}${fmtDec(abs / 1e9, 2)} M`;
  if (abs >= 1e6) return `${sign}${fmtDec(abs / 1e6, 2)} jt`;
  if (abs >= 1e3) return `${sign}${fmtDec(abs / 1e3, 1)} rb`;
  return `${sign}${fmtNum(abs)}`;
};

function buildCashinQuery(extra = {}) {
  const params = new URLSearchParams();
  params.set("non_kogol_12", state.nonKogol12 ? "1" : "0");
  params.set("page", String(state.page));
  params.set("page_size", String(state.pageSize));
  params.set("sort_by", state.sortBy);
  params.set("sort_dir", state.sortDir);
  Object.entries(state.filters).forEach(([k, v]) => {
    if (v !== "" && v !== null && v !== undefined) params.set(k, v);
  });
  Object.entries(extra).forEach(([k, v]) => params.set(k, v));
  return params.toString();
}

function populateSelect(el, items, placeholder, preserveVal = true) {
  const current = preserveVal ? el.value : "";
  el.innerHTML = `<option value="">${placeholder}</option>`;
  items.forEach((item) => {
    const opt = document.createElement("option");
    if (typeof item === "object") {
      opt.value = item.value;
      opt.textContent = item.label;
    } else {
      opt.value = String(item);
      opt.textContent = String(item);
    }
    el.appendChild(opt);
  });
  if (current) el.value = current;
}

// ==========================================================================
// LOAD & RENDER CASH IN
// ==========================================================================
async function loadCashin(forceRefresh = false) {
  const qs = buildCashinQuery(forceRefresh ? { refresh: "1" } : {});
  const res = await fetch(`/api/dashboard/cashin?${qs}`);
  const data = await res.json();
  if (data.error) {
    console.error("Cashin error:", data.error);
    return;
  }

  // Meta badges
  const badge = document.getElementById("sourceBadge");
  const modeMap = {
    live_google_sheets: { text: "● Live Google Sheets", cls: "" },
    disk_cache: { text: "● Cache Lokal", cls: "" },
    local_excel: { text: "● Excel Lokal", cls: "" },
    offline_snapshot: { text: "● Offline Snapshot", cls: "offline" },
  };
  const m = modeMap[data.meta.source_mode] || { text: data.meta.source_mode, cls: "" };
  badge.textContent = m.text;
  badge.className = `source-badge ${m.cls}`;
  document.getElementById("lastUpdateVal").textContent = data.kpi.last_update || "-";
  document.getElementById("scopeLabel").textContent = data.kpi.scope_label;
  document.getElementById("footerFetchedAt").textContent = `Data Terakhir Diperbarui: ${data.meta.fetched_at}`;

  // Filter dropdowns (initialize once or update options)
  if (!state.filtersInitialized) {
    const fo = data.filter_options;
    populateSelect(document.getElementById("fUlp"), fo.ulp, "ULP");
    populateSelect(document.getElementById("fRbm"), fo.rbm, "RBM");
    populateSelect(document.getElementById("fLembar"), fo.lembar, "lembar");
    populateSelect(document.getElementById("fKogol"), fo.kogol, "KOGOL");
    populateSelect(document.getElementById("fSegmen"), fo.segmen_tarif, "Segmen Tarif");
    populateSelect(document.getElementById("fTarif"), fo.tarif, "tarif");
    populateSelect(document.getElementById("fDaya"), fo.daya, "daya");
    populateSelect(document.getElementById("fTrendUlp"), fo.ulp, "Semua ULP");
    if (data.meta.harian && data.meta.harian.golongan_options) {
      populateSelect(
        document.getElementById("fTrendGolongan"),
        data.meta.harian.golongan_options,
        "Semua Golongan (Non 1,2)"
      );
    }
    state.filtersInitialized = true;
  }

  // KPIs & Gauge
  document.getElementById("kpiSaldo").textContent = fmtNum(data.kpi.saldo_saat_ini);
  document.getElementById("kpiPelanggan").textContent = fmtNum(data.kpi.total_pelanggan);
  document.getElementById("gaugeValueText").textContent = fmtNum(data.kpi.saldo_saat_ini);
  const ratio = Math.min(1, data.kpi.saldo_saat_ini / (data.kpi.target_up3 || 600_000_000));
  const arcLen = 326.7;
  document.getElementById("gaugeArc").setAttribute("stroke-dashoffset", String(arcLen * (1 - ratio)));

  renderSaldoUnit(data.saldo_unit, data.saldo_unit_total);
  renderSaldoKogol(data.saldo_kogol, data.saldo_kogol_total);
  renderDetailTable(data.detail_pelanggan);
  renderTrendSection(data.trend_comparison, data.meta.harian);
  renderUlpComparison(data.ulp_comparison, data.ulp_comparison_total);
  renderKomposisiTarif(data.komposisi_tarif);
  renderPemda(data.saldo_pemda, data.saldo_pemda_total);
  renderKomposisiUnit(data.komposisi_unit);

  state.billerRows = data.saldo_biller || [];
  renderBillerTable();
}

function renderSaldoUnit(rows, total) {
  const tbody = document.getElementById("tbodySaldoUnit");
  const cell = (val, isMoney = false) => {
    if (!val || val === 0) return `<td class="zero-cell">-</td>`;
    return `<td class="num">${fmtNum(val)}</td>`;
  };

  tbody.innerHTML = rows
    .map(
      (r) => `
      <tr class="${state.filters.ulp === r.unit ? "selected-unit" : ""}" data-unit="${r.unit}" title="Klik untuk filter ULP ${r.unit} (${r.unit_name})">
        <td><strong>${r.unit}</strong></td>
        ${cell(r.l1_plg)}
        ${cell(r.l1_rp, true)}
        ${cell(r.l2_plg)}
        ${cell(r.l2_rp, true)}
        ${cell(r.l3_plg)}
        ${cell(r.l3_rp, true)}
        <td class="num"><strong>${fmtNum(r.up3_plg)}</strong></td>
        <td class="num"><strong>${fmtNum(r.up3_rp)}</strong></td>
      </tr>`
    )
    .join("");

  tbody.querySelectorAll("tr").forEach((tr) => {
    tr.addEventListener("click", () => {
      const u = tr.dataset.unit;
      state.filters.ulp = state.filters.ulp === u ? "" : u;
      document.getElementById("fUlp").value = state.filters.ulp;
      state.page = 1;
      loadCashin();
    });
  });

  document.getElementById("tfootSaldoUnit").innerHTML = `
    <tr>
      <td>${total.unit}</td>
      <td class="num">${fmtNum(total.l1_plg)}</td>
      <td class="num">${fmtNum(total.l1_rp)}</td>
      <td class="num">${fmtNum(total.l2_plg)}</td>
      <td class="num">${fmtNum(total.l2_rp)}</td>
      <td class="num">${fmtNum(total.l3_plg)}</td>
      <td class="num">${fmtNum(total.l3_rp)}</td>
      <td class="num">${fmtNum(total.up3_plg)}</td>
      <td class="num">${fmtNum(total.up3_rp)}</td>
    </tr>`;
}

function renderSaldoKogol(rows, total) {
  document.getElementById("tbodySaldoKogol").innerHTML = rows
    .map(
      (r, i) => `
      <tr>
        <td>${i + 1}.</td>
        <td><strong>${r.kogol}</strong></td>
        <td class="num">${fmtNum(r.plg)}</td>
        <td class="num">${fmtNum(r.rp_ptl)}</td>
      </tr>`
    )
    .join("");

  document.getElementById("tfootSaldoKogol").innerHTML = `
    <tr>
      <td></td>
      <td>UP3</td>
      <td class="num">${fmtNum(total.plg)}</td>
      <td class="num">${fmtNum(total.rp_ptl)}</td>
    </tr>`;
}

function renderDetailTable(detail) {
  const tbody = document.getElementById("tbodyDetail");
  if (!detail.rows.length) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align:center;padding:24px;color:#64748B;">Tidak ada data sesuai filter.</td></tr>`;
  } else {
    tbody.innerHTML = detail.rows
      .map(
        (r) => `
        <tr>
          <td class="num">${r.no}.</td>
          <td>${r.ulp}</td>
          <td><code>${r.idpel}</code></td>
          <td>${r.nama}</td>
          <td>${r.alamat}</td>
          <td>${r.tarif}</td>
          <td class="num">${fmtNum(r.daya)}</td>
          <td>${r.rbm}</td>
          <td class="num">${fmtNum(r.lembar)}</td>
          <td class="num"><strong>${fmtNum(r.rpptl)}</strong></td>
        </tr>`
      )
      .join("");
  }

  document.getElementById("tfootDetail").innerHTML = `
    <tr>
      <td colspan="8">Total keseluruhan</td>
      <td class="num">${fmtNum(detail.total_lembar)}</td>
      <td class="num">${fmtNum(detail.total_rpptl)}</td>
    </tr>`;

  const start = detail.total_rows ? (detail.page - 1) * detail.page_size + 1 : 0;
  const end = Math.min(detail.page * detail.page_size, detail.total_rows);
  document.getElementById("paginationInfo").textContent = `${fmtNum(start)} - ${fmtNum(end)} / ${fmtNum(detail.total_rows)}`;
  document.getElementById("btnPrevPage").disabled = detail.page <= 1;
  document.getElementById("btnNextPage").disabled = end >= detail.total_rows;
}

function renderTrendSection(rows, meta) {
  if (meta && meta.curr_ym) {
    document.getElementById("harianPeriodLabel").textContent = `Perbandingan: ${meta.prev_ym} vs ${meta.curr_ym} (H-${meta.latest_day})`;
  }

  // Table (descending tanggal 31 -> 1)
  const desc = [...rows].sort((a, b) => b.tanggal - a.tanggal);
  document.getElementById("tbodyPerbandinganTanggal").innerHTML = desc
    .map((r) => {
      const cls = r.selisih >= 0 ? "delta-pos" : "delta-neg";
      return `
        <tr>
          <td><strong>${r.tanggal}</strong></td>
          <td class="num">${fmtShortRp(r.rp_lalu)}</td>
          <td class="num">${fmtShortRp(r.rp_ini)}</td>
          <td class="num ${cls}">${fmtShortRp(r.selisih)}</td>
        </tr>`;
    })
    .join("");

  // Line Chart (ascending tanggal 1 -> 31)
  const asc = [...rows].sort((a, b) => a.tanggal - b.tanggal);
  const ctx = document.getElementById("chartPenurunan").getContext("2d");
  if (state.charts.penurunan) state.charts.penurunan.destroy();
  state.charts.penurunan = new Chart(ctx, {
    type: "line",
    data: {
      labels: asc.map((r) => String(r.tanggal)),
      datasets: [
        {
          label: "Rp PTL (Bulan Lalu)",
          data: asc.map((r) => r.rp_lalu),
          borderColor: "#94A3B8",
          backgroundColor: "rgba(148,163,184,0.12)",
          borderDash: [5, 4],
          tension: 0.25,
          pointRadius: 2,
        },
        {
          label: "Rp PTL (Bulan Ini)",
          data: asc.map((r) => r.rp_ini || null),
          borderColor: "#00798C",
          backgroundColor: "rgba(0,121,140,0.14)",
          fill: true,
          tension: 0.25,
          pointRadius: 3,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        tooltip: {
          callbacks: {
            label: (c) => `${c.dataset.label}: Rp ${fmtNum(c.parsed.y)}`,
          },
        },
      },
      scales: {
        y: {
          ticks: { callback: (v) => fmtShortRp(v) },
        },
      },
    },
  });
}

function renderUlpComparison(rows, total) {
  const fmtDelta = (v, suffix = "") => {
    const cls = v >= 0 ? "delta-pos" : "delta-neg";
    return `<td class="num ${cls}">${suffix ? fmtDec(v, 2) + suffix : fmtNum(v)}</td>`;
  };

  document.getElementById("tbodyPerbandinganUlp").innerHTML = rows
    .map(
      (r) => `
      <tr>
        <td><strong>${r.ulp}</strong></td>
        <td class="num">${fmtNum(r.plg_lalu)}</td>
        <td class="num">${fmtNum(r.rp_lalu)}</td>
        <td class="num">${fmtNum(r.plg_h1)}</td>
        <td class="num">${fmtNum(r.rp_h1)}</td>
        ${fmtDelta(r.selisih_plg)}
        ${fmtDelta(r.selisih_ptl)}
        ${fmtDelta(r.pct_plg, "%")}
        ${fmtDelta(r.pct_ptl, "%")}
      </tr>`
    )
    .join("");

  if (total && total.ulp) {
    document.getElementById("tfootPerbandinganUlp").innerHTML = `
      <tr>
        <td>${total.ulp}</td>
        <td class="num">${fmtNum(total.plg_lalu)}</td>
        <td class="num">${fmtNum(total.rp_lalu)}</td>
        <td class="num">${fmtNum(total.plg_h1)}</td>
        <td class="num">${fmtNum(total.rp_h1)}</td>
        ${fmtDelta(total.selisih_plg)}
        ${fmtDelta(total.selisih_ptl)}
        ${fmtDelta(total.pct_plg, "%")}
        ${fmtDelta(total.pct_ptl, "%")}
      </tr>`;
  }
}

function renderKomposisiTarif(items) {
  const ctx = document.getElementById("chartTarif").getContext("2d");
  if (state.charts.tarif) state.charts.tarif.destroy();
  const palette = ["#00798C", "#F58220", "#0EA5E9", "#10B981", "#6366F1", "#EC4899", "#F59E0B", "#14B8A6", "#8B5CF6", "#64748B"];
  state.charts.tarif = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: items.map((x) => x.tarif),
      datasets: [{ data: items.map((x) => x.rp_ptl), backgroundColor: palette }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "right", labels: { boxWidth: 12, font: { size: 11 } } },
        tooltip: {
          callbacks: { label: (c) => `${c.label}: Rp ${fmtNum(c.parsed)}` },
        },
      },
    },
  });
}

function renderPemda(rows, total) {
  const tbody = document.getElementById("tbodyPemda");
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="4" style="text-align:center;color:#64748B;">Tidak ada data Kogol 3.</td></tr>`;
  } else {
    tbody.innerHTML = rows
      .map(
        (r, i) => `
        <tr>
          <td>${i + 1}.</td>
          <td><strong>${r.pemda}</strong></td>
          <td class="num">${fmtNum(r.plg)}</td>
          <td class="num">${fmtNum(r.rp_ptl)}</td>
        </tr>`
      )
      .join("");
  }
  document.getElementById("tfootPemda").innerHTML = `
    <tr>
      <td></td>
      <td>UP3</td>
      <td class="num">${fmtNum(total.plg)}</td>
      <td class="num">${fmtNum(total.rp_ptl)}</td>
    </tr>`;
}

function renderKomposisiUnit(items) {
  const ctx = document.getElementById("chartUnit").getContext("2d");
  if (state.charts.unit) state.charts.unit.destroy();
  state.charts.unit = new Chart(ctx, {
    type: "bar",
    data: {
      labels: items.map((x) => `${x.unit} ${x.short}`),
      datasets: [
        {
          label: "Rp PTL",
          data: items.map((x) => x.rp_ptl),
          backgroundColor: "#00798C",
          borderRadius: 6,
        },
      ],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: { label: (c) => `Rp ${fmtNum(c.parsed.x)}` },
        },
      },
      scales: {
        x: { ticks: { callback: (v) => fmtShortRp(v) } },
      },
    },
  });
}

function renderBillerTable() {
  const q = (document.getElementById("fBillerSearch").value || "").trim().toLowerCase();
  const filtered = q
    ? state.billerRows.filter(
        (r) =>
          r.ulp.toLowerCase().includes(q) ||
          r.rbm.toLowerCase().includes(q) ||
          r.nama.toLowerCase().includes(q)
      )
    : state.billerRows;

  document.getElementById("tbodyBiller").innerHTML = filtered
    .map(
      (r, idx) => `
      <tr>
        <td class="num">${idx + 1}.</td>
        <td>${r.ulp}</td>
        <td><code>${r.rbm}</code></td>
        <td>${r.nama}</td>
        <td class="num">${fmtNum(r.plg)}</td>
        <td class="num">${fmtNum(r.lembar)}</td>
        <td class="num"><strong>${fmtNum(r.rp_ptl)}</strong></td>
      </tr>`
    )
    .join("");
}

// ==========================================================================
// LOAD & RENDER KINERJA TAB
// ==========================================================================
async function loadKinerja() {
  const params = new URLSearchParams();
  if (state.kinerjaFilters.periode) params.set("periode", state.kinerjaFilters.periode);
  if (state.kinerjaFilters.ulp) params.set("ulp", state.kinerjaFilters.ulp);

  const res = await fetch(`/api/dashboard/kinerja?${params.toString()}`);
  const data = await res.json();

  populateSelect(document.getElementById("kPeriode"), data.periodes || [], "Semua Periode");
  const ulpOpts = (data.by_ulp || []).map((x) => ({ value: x.unit_code, label: x.ulp }));
  if (ulpOpts.length && document.getElementById("kUlp").options.length <= 1) {
    populateSelect(document.getElementById("kUlp"), ulpOpts, "Semua ULP");
  }

  document.getElementById("kTargetSaldo").textContent = `${fmtDec(data.kpi.target_saldo_juta)} Jt`;
  document.getElementById("kRealSaldo").textContent = `${fmtDec(data.kpi.realisasi_saldo_juta)} Jt`;
  document.getElementById("kRealPrr").textContent = fmtShortRp(data.kpi.realisasi_prr);

  // Bar Chart: Target vs Realisasi Saldo per ULP
  const ctx1 = document.getElementById("chartKinerjaUlp").getContext("2d");
  if (state.charts.kUlp) state.charts.kUlp.destroy();
  state.charts.kUlp = new Chart(ctx1, {
    type: "bar",
    data: {
      labels: (data.by_ulp || []).map((x) => x.unit_code),
      datasets: [
        { label: "Target (Jt)", data: (data.by_ulp || []).map((x) => x.target_saldo), backgroundColor: "#94A3B8", borderRadius: 4 },
        { label: "Realisasi (Jt)", data: (data.by_ulp || []).map((x) => x.realisasi_saldo), backgroundColor: "#00798C", borderRadius: 4 },
      ],
    },
    options: { responsive: true, maintainAspectRatio: false },
  });

  // Line Chart: Monthly PRR
  const ctx2 = document.getElementById("chartKinerjaTren").getContext("2d");
  if (state.charts.kTren) state.charts.kTren.destroy();
  state.charts.kTren = new Chart(ctx2, {
    type: "line",
    data: {
      labels: (data.by_periode || []).map((x) => x.periode),
      datasets: [
        { label: "Target PRR", data: (data.by_periode || []).map((x) => x.target_prr), borderColor: "#F58220", tension: 0.25 },
        { label: "Realisasi PRR", data: (data.by_periode || []).map((x) => x.realisasi_prr), borderColor: "#00798C", backgroundColor: "rgba(0,121,140,0.12)", fill: true, tension: 0.25 },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: { y: { ticks: { callback: (v) => fmtShortRp(v) } } },
    },
  });

  document.getElementById("tbodyKinerja").innerHTML = (data.rows || [])
    .map(
      (r) => `
      <tr>
        <td>${r.periode}</td>
        <td>${r.ulp}</td>
        <td class="num">${fmtDec(r.target_saldo)}</td>
        <td class="num"><strong>${fmtDec(r.realisasi_saldo)}</strong></td>
        <td class="num">${fmtNum(r.target_prr)}</td>
        <td class="num">${fmtNum(r.prr_1)}</td>
        <td class="num">${fmtNum(r.ex_prr)}</td>
        <td class="num">${fmtNum(r.prabayar)}</td>
        <td class="num"><strong>${fmtNum(r.realisasi_prr)}</strong></td>
      </tr>`
    )
    .join("");
}

// ==========================================================================
// PIPELINE AUTOMATION (UAT.PY -> UPDATE_SALDO_DB.PY) + SSE LIVE LOGS
// ==========================================================================
function connectPipelineSSE() {
  if (state.sse) state.sse.close();
  const es = new EventSource("/api/pipeline/stream");
  state.sse = es;

  es.addEventListener("state", (ev) => {
    const st = JSON.parse(ev.data);
    applyPipelineState(st);
  });

  es.addEventListener("log", (ev) => {
    const entry = JSON.parse(ev.data);
    appendTerminalLine(entry);
  });

  es.addEventListener("done", (ev) => {
    const d = JSON.parse(ev.data);
    if (d.status === "success") {
      loadCashin(false);
    }
  });
}

function applyPipelineState(st) {
  const running = Boolean(st.running);
  document.getElementById("seqSpinner").classList.toggle("hidden", !running);
  document.getElementById("btnRunSequence").disabled = running;
  document.getElementById("btnModalRunSeq").disabled = running;
  document.getElementById("btnModalRunUat").disabled = running;
  document.getElementById("btnModalRunUpdate").disabled = running;
  document.getElementById("btnModalStop").disabled = !running;

  document.getElementById("seqBtnText").textContent = running
    ? "Menjalankan Pipeline..."
    : "▶ Eksekusi UAT → Update Saldo DB";

  const dot = document.getElementById("pipelineBadgeDot");
  dot.className = `status-dot ${st.overall_status || "idle"}`;

  // Token status
  const tokEl = document.getElementById("tokenStatusText");
  if (st.token && st.token.valid) {
    tokEl.textContent = `✓ Aktif (${st.token.updated_at})`;
    tokEl.className = "token-badge valid";
  } else {
    tokEl.textContent = "✗ Belum ada token valid (Jalankan UAT)";
    tokEl.className = "token-badge invalid";
  }

  // Stepper cards
  ["uat", "update_db", "refresh"].forEach((key) => {
    const info = st.steps && st.steps[key];
    if (!info) return;
    const card = document.getElementById(`stepCard-${key}`);
    const badge = document.getElementById(`stepBadge-${key}`);
    card.className = `step-card ${info.status}`;
    badge.textContent = info.status;
  });

  // Render initial buffered logs if terminal is still default
  if (st.logs && st.logs.length) {
    const term = document.getElementById("terminalLogs");
    term.innerHTML = "";
    st.logs.forEach(appendTerminalLine);
  }
}

function appendTerminalLine(entry) {
  const term = document.getElementById("terminalLogs");
  const span = document.createElement("div");
  span.className = `log-${entry.level || "info"}`;
  span.textContent = `[${entry.ts}] ${entry.text}`;
  term.appendChild(span);
  term.scrollTop = term.scrollHeight;
}

async function triggerPipeline(mode) {
  document.getElementById("pipelineModal").classList.remove("hidden");
  document.getElementById("terminalLogs").innerHTML = "";
  const thbl = document.getElementById("inputThbl").value.trim();
  const res = await fetch("/api/pipeline/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode, thbl: thbl || undefined }),
  });
  const data = await res.json();
  if (!data.ok) {
    appendTerminalLine({ ts: "--:--:--", level: "warn", text: data.message || "Gagal memulai pipeline." });
  }
}

// ==========================================================================
// EVENT WIRING
// ==========================================================================
function wireEvents() {
  // Default THBL = current YYYYMM
  const now = new Date();
  document.getElementById("inputThbl").value = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, "0")}`;

  // Tabs
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => {
        b.classList.remove("active");
        b.setAttribute("aria-selected", "false");
      });
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      btn.setAttribute("aria-selected", "true");
      const tab = btn.dataset.tab;
      state.tab = tab;
      document.getElementById(`tab-${tab}`).classList.add("active");
      if (tab === "kinerja") loadKinerja();
    });
  });

  // Scope toggle
  document.getElementById("chkNonKogol12").addEventListener("change", (e) => {
    state.nonKogol12 = e.target.checked;
    state.page = 1;
    loadCashin();
  });

  // Filters
  const bindSelect = (id, key) => {
    document.getElementById(id).addEventListener("change", (e) => {
      state.filters[key] = e.target.value;
      state.page = 1;
      loadCashin();
    });
  };
  bindSelect("fUlp", "ulp");
  bindSelect("fRbm", "rbm");
  bindSelect("fLembar", "lembar");
  bindSelect("fKogol", "kogol");
  bindSelect("fSegmen", "segmen_tarif");
  bindSelect("fTarif", "tarif");
  bindSelect("fDaya", "daya");
  bindSelect("fSaldoOp", "saldo_op");
  bindSelect("fTrendUlp", "trend_ulp");
  bindSelect("fTrendGolongan", "trend_golongan");

  let searchTimer = null;
  const bindDebounced = (id, key) => {
    document.getElementById(id).addEventListener("input", (e) => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        state.filters[key] = e.target.value;
        state.page = 1;
        loadCashin();
      }, 300);
    });
  };
  bindDebounced("fSaldoVal", "saldo_val");
  bindDebounced("fSearch", "search");

  document.getElementById("fBillerSearch").addEventListener("input", renderBillerTable);

  document.getElementById("btnResetFilters").addEventListener("click", () => {
    Object.keys(state.filters).forEach((k) => {
      state.filters[k] = k === "saldo_op" ? "gte" : "";
    });
    ["fUlp", "fRbm", "fLembar", "fKogol", "fSegmen", "fTarif", "fDaya", "fSaldoVal", "fSearch", "fTrendUlp", "fTrendGolongan"].forEach((id) => {
      document.getElementById(id).value = "";
    });
    document.getElementById("fSaldoOp").value = "gte";
    state.page = 1;
    loadCashin();
  });

  document.getElementById("btnExportCsv").addEventListener("click", () => {
    window.location.href = `/api/data/export?${buildCashinQuery()}`;
  });

  // Sortable columns
  document.querySelectorAll("#tblDetailPelanggan th.sortable").forEach((th) => {
    th.addEventListener("click", () => {
      const col = th.dataset.sort;
      if (state.sortBy === col) {
        state.sortDir = state.sortDir === "desc" ? "asc" : "desc";
      } else {
        state.sortBy = col;
        state.sortDir = "desc";
      }
      state.page = 1;
      loadCashin();
    });
  });

  // Pagination
  document.getElementById("btnPrevPage").addEventListener("click", () => {
    if (state.page > 1) {
      state.page -= 1;
      loadCashin();
    }
  });
  document.getElementById("btnNextPage").addEventListener("click", () => {
    state.page += 1;
    loadCashin();
  });

  // Kinerja filters
  document.getElementById("kPeriode").addEventListener("change", (e) => {
    state.kinerjaFilters.periode = e.target.value;
    loadKinerja();
  });
  document.getElementById("kUlp").addEventListener("change", (e) => {
    state.kinerjaFilters.ulp = e.target.value;
    loadKinerja();
  });

  // Refresh Data
  document.getElementById("btnRefreshData").addEventListener("click", async () => {
    const btn = document.getElementById("btnRefreshData");
    btn.disabled = true;
    btn.textContent = "↻ Memuat...";
    try {
      await fetch("/api/data/refresh", { method: "POST" });
      await loadCashin(false);
      if (state.tab === "kinerja") await loadKinerja();
    } finally {
      btn.disabled = false;
      btn.textContent = "↻ Refresh";
    }
  });

  // Pipeline modal & buttons
  document.getElementById("btnRunSequence").addEventListener("click", () => triggerPipeline("sequential"));
  document.getElementById("btnOpenPipeline").addEventListener("click", () => {
    document.getElementById("pipelineModal").classList.remove("hidden");
  });
  document.getElementById("btnClosePipeline").addEventListener("click", () => {
    document.getElementById("pipelineModal").classList.add("hidden");
  });
  document.getElementById("btnModalRunSeq").addEventListener("click", () => triggerPipeline("sequential"));
  document.getElementById("btnModalRunUat").addEventListener("click", () => triggerPipeline("uat"));
  document.getElementById("btnModalRunUpdate").addEventListener("click", () => triggerPipeline("update_db"));
  document.getElementById("btnModalStop").addEventListener("click", async () => {
    await fetch("/api/pipeline/stop", { method: "POST" });
  });
  document.getElementById("btnClearLogs").addEventListener("click", () => {
    document.getElementById("terminalLogs").innerHTML = "";
  });
}

document.addEventListener("DOMContentLoaded", () => {
  wireEvents();
  connectPipelineSSE();
  loadCashin(false);
});
