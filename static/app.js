const fmt = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 });
const pct = (v) => (Number.isFinite(v) ? `${fmt.format(v * 100)}%` : "--");
const val = (v, suffix = "") => (Number.isFinite(v) ? `${fmt.format(v)}${suffix}` : "--");
const STATIC_HOST_RE = /(^|\.)github\.io$/i;

const elements = {
  refreshBtn: document.getElementById("refreshBtn"),
  lastUpdated: document.getElementById("lastUpdated"),
  totalScore: document.getElementById("totalScore"),
  scoreRing: document.getElementById("scoreRing"),
  scoreStatus: document.getElementById("scoreStatus"),
  scoreDetail: document.getElementById("scoreDetail"),
  phaseDetail: document.getElementById("phaseDetail"),
  actionHint: document.getElementById("actionHint"),
  modelVersion: document.getElementById("modelVersion"),
  erpValue: document.getElementById("erpValue"),
  tenYield: document.getElementById("tenYield"),
  advanceRatio: document.getElementById("advanceRatio"),
  financingRatio: document.getElementById("financingRatio"),
  financingSource: document.getElementById("financingSource"),
  dataConfidence: document.getElementById("dataConfidence"),
  dataConfidenceSource: document.getElementById("dataConfidenceSource"),
  moduleBars: document.getElementById("moduleBars"),
  signalsTable: document.getElementById("signalsTable"),
  sourceSummary: document.getElementById("sourceSummary"),
  sourceQuality: document.getElementById("sourceQuality"),
  warnings: document.getElementById("warnings"),
  redFlags: document.getElementById("redFlags"),
  confirmationMatrix: document.getElementById("confirmationMatrix"),
};

function scoreColor(score) {
  if (score >= 75) return "#f97066";
  if (score >= 60) return "#fdb022";
  if (score >= 40) return "#f7c948";
  return "#32d583";
}

function statusLabel(status) {
  const labels = {
    ok: "实时正常",
    fresh_cache: "有效缓存",
    stale: "日期偏旧",
    stale_cache: "过期缓存",
    not_available: "不可用",
    error: "错误",
  };
  return labels[status] || status || "--";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function compactWarning(value) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  if (text.includes("HTTPSConnectionPool") || text.includes("push2.eastmoney") || text.includes("clist/get")) {
    return "GitHub Actions 环境临时无法访问东方财富全A快照，本次使用最近快照继续发布；宽度、成交额、流通市值相关指标请结合数据源状态核对。";
  }
  return text.length > 180 ? `${text.slice(0, 180)}…` : text;
}

function isStaticFirstHost() {
  return window.location.protocol === "file:" || STATIC_HOST_RE.test(window.location.hostname);
}

function dashboardSnapshotUrl(force = false) {
  const url = new URL("dashboard.json", window.location.href);
  if (force) url.searchParams.set("_", Date.now().toString());
  return url.toString();
}

async function readJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`返回 ${response.status}`);
  return response.json();
}

async function fetchDashboardPayload(force = false) {
  const errors = [];
  const preferStatic = isStaticFirstHost();
  if (!preferStatic) {
    try {
      const payload = await readJson(`/api/dashboard${force ? "?force=true" : ""}`, {
        cache: force ? "reload" : "default",
      });
      return { payload, mode: "api" };
    } catch (error) {
      errors.push(`实时接口不可用：${error.message}`);
    }
  }

  try {
    const payload = await readJson(dashboardSnapshotUrl(force), {
      cache: force ? "reload" : "default",
    });
    return { payload, mode: "static" };
  } catch (error) {
    errors.push(`静态快照不可用：${error.message}`);
  }

  throw new Error(errors.join("；"));
}

function renderHeadline(payload, mode = "api") {
  const headline = payload.headline || {};
  const modeText = mode === "static" ? "GitHub Pages 快照" : "实时接口";
  elements.totalScore.textContent = fmt.format(payload.total_score);
  elements.scoreRing.style.setProperty("--score", `${payload.total_score * 3.6}deg`);
  elements.scoreRing.style.background = `radial-gradient(circle, var(--panel) 58%, transparent 60%), conic-gradient(${scoreColor(payload.total_score)} ${payload.total_score * 3.6}deg, rgba(255,255,255,0.10) 0)`;
  elements.scoreStatus.textContent = headline.market_phase || payload.status;
  elements.scoreDetail.textContent = payload.status_detail;
  elements.phaseDetail.textContent = headline.phase_detail || "等待阶段研判。";
  elements.actionHint.textContent = headline.action_hint || "等待风控动作提示。";
  elements.modelVersion.textContent = headline.model_version || "A股顶部指标";
  elements.erpValue.textContent = val(headline.latest_erp, "%");
  elements.tenYield.textContent = val(headline.ten_year_yield, "%");
  elements.advanceRatio.textContent = pct(headline.advance_ratio);
  elements.financingRatio.textContent = val(headline.financing_balance_float_mcap_ratio, "%");
  elements.financingSource.textContent = headline.float_market_cap_source || "融资杠杆拥挤度";
  elements.dataConfidence.textContent = Number.isFinite(headline.data_confidence_score)
    ? `${fmt.format(headline.data_confidence_score)}分`
    : "--";
  elements.dataConfidenceSource.textContent = headline.data_confidence_detail || "按核心数据源质量折算";
  elements.lastUpdated.textContent = `生成：${payload.generated_at || "--"}｜数据：${payload.as_of || "--"}｜${modeText}`;
}

function renderWarnings(warnings) {
  if (!warnings || warnings.length === 0) {
    elements.warnings.classList.add("hidden");
    elements.warnings.innerHTML = "";
    return;
  }
  elements.warnings.classList.remove("hidden");
  elements.warnings.innerHTML = `<strong>风险提示</strong><ul>${warnings
    .map((w) => `<li>${escapeHtml(compactWarning(w))}</li>`)
    .join("")}</ul>`;
}

function renderRedFlags(flags) {
  elements.redFlags.innerHTML = (flags || [])
    .map((flag, index) => `<li><span>${String(index + 1).padStart(2, "0")}</span>${flag}</li>`)
    .join("");
}

function renderConfirmationMatrix(matrix) {
  elements.confirmationMatrix.innerHTML = (matrix || [])
    .map((item) => {
      const score = Number(item.score || 0);
      return `
        <article class="matrix-card">
          <div class="matrix-head">
            <strong>${item.name}</strong>
            <span class="pill">${item.status || "--"}</span>
          </div>
          <div class="matrix-score" style="color:${scoreColor(score)}">${fmt.format(score)}分</div>
          <div class="bar-bg"><div class="bar-fill" style="width:${Math.max(0, Math.min(100, score))}%; background:${scoreColor(score)};"></div></div>
          <p>${item.detail || ""}</p>
        </article>
      `;
    })
    .join("");
}

function renderModules(modules) {
  elements.moduleBars.innerHTML = modules
    .map((m) => {
      const color = scoreColor(m.raw_score);
      const summary = (m.signals || [])
        .slice(0, 2)
        .map((s) => `${s.name}：${s.value ?? "--"}${s.unit || ""}`)
        .join("；");
      return `
        <div class="module-row">
          <div>
            <strong>${m.name}</strong>
            <small>${summary}</small>
          </div>
          <div class="bar-bg"><div class="bar-fill" style="width:${m.raw_score}%; background:${color};"></div></div>
          <span>${fmt.format(m.raw_score)}分 / +${fmt.format(m.contribution)}</span>
        </div>
      `;
    })
    .join("");
}

function renderSignals(modules) {
  const rows = [];
  modules.forEach((m) => {
    (m.signals || []).forEach((s) => {
      rows.push(`
        <tr>
          <td>${m.name}</td>
          <td>${s.name}</td>
          <td>${s.value ?? "--"}${s.unit || ""}</td>
          <td>${fmt.format(s.score)}</td>
          <td><span class="pill">${s.status}</span></td>
          <td>${s.detail}</td>
          <td>${s.source}</td>
        </tr>
      `);
    });
  });
  elements.signalsTable.innerHTML = rows.join("");
}

function renderSources(sources) {
  renderSourceSummary(sources);
  elements.sourceQuality.innerHTML = (sources || [])
    .map((s) => {
      const safeUrl = escapeHtml(s.url || "");
      const link = s.url && !s.url.startsWith("local://") ? `<a href="${safeUrl}" target="_blank" rel="noreferrer">打开来源</a>` : "本地探测";
      return `
        <article class="source-card">
          <div class="source-head">
            <h3>${escapeHtml(s.name || "--")}</h3>
            <span class="pill ${escapeHtml(s.status || "")}">${escapeHtml(statusLabel(s.status))}</span>
          </div>
          <dl>
            <div><dt>数据日期</dt><dd>${escapeHtml(s.as_of || "--")}</dd></div>
            <div><dt>行数</dt><dd>${fmt.format(s.row_count ?? 0)}</dd></div>
          </dl>
          <p>${escapeHtml(compactWarning(s.message || ""))}</p>
          <p class="source-link">${link}</p>
        </article>
      `;
    })
    .join("");
}

function renderSourceSummary(sources) {
  const list = sources || [];
  const coreSources = list.filter((s) => !String(s.name || "").toLowerCase().includes("xtquant") && !String(s.name || "").toLowerCase().includes("qmt"));
  const okCount = coreSources.filter((s) => ["ok", "fresh_cache"].includes(s.status)).length;
  const degradedCount = coreSources.filter((s) => !["ok", "fresh_cache"].includes(s.status)).length;
  const latestDate = coreSources.map((s) => s.as_of).filter(Boolean).sort().at(-1) || "--";
  const cacheCount = list.filter((s) => s.from_cache).length;
  elements.sourceSummary.innerHTML = [
    { label: "正常/有效缓存", value: okCount, hint: "可直接纳入当前评分" },
    { label: "核心需核对", value: degradedCount, hint: "不含可选 QMT 探测" },
    { label: "最新数据日", value: latestDate, hint: "来自核心数据源 as_of 最大值" },
    { label: "缓存来源数", value: cacheCount, hint: "缓存不等于错误，但需看是否过期" },
  ]
    .map((item) => `
      <article class="summary-card">
        <span>${item.label}</span>
        <strong>${item.value}</strong>
        <small>${item.hint}</small>
      </article>
    `)
    .join("");
}

function drawLineChart(canvasId, series, lines) {
  const canvas = document.getElementById(canvasId);
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const cssHeight = Number(canvas.getAttribute("height")) || 240;
  canvas.width = rect.width * dpr;
  canvas.height = cssHeight * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  const width = rect.width;
  const height = cssHeight;
  ctx.clearRect(0, 0, width, height);
  if (!series || series.length < 2) return;

  const padding = { top: 18, right: 20, bottom: 28, left: 52 };
  const values = [];
  lines.forEach((line) => {
    series.forEach((d) => {
      const value = Number(d[line.key]);
      if (Number.isFinite(value)) values.push(value);
    });
  });
  if (values.length === 0) return;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const x = (i) => padding.left + (i / (series.length - 1)) * (width - padding.left - padding.right);
  const y = (v) => padding.top + (1 - (v - min) / span) * (height - padding.top - padding.bottom);

  const gradient = ctx.createLinearGradient(0, padding.top, 0, height - padding.bottom);
  gradient.addColorStop(0, "rgba(92,169,255,0.12)");
  gradient.addColorStop(1, "rgba(92,169,255,0)");
  ctx.fillStyle = gradient;
  ctx.fillRect(padding.left, padding.top, width - padding.left - padding.right, height - padding.top - padding.bottom);

  ctx.strokeStyle = "rgba(255,255,255,0.10)";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i += 1) {
    const yy = padding.top + (i / 4) * (height - padding.top - padding.bottom);
    ctx.beginPath();
    ctx.moveTo(padding.left, yy);
    ctx.lineTo(width - padding.right, yy);
    ctx.stroke();
  }

  ctx.fillStyle = "rgba(232,238,252,0.72)";
  ctx.font = "12px Microsoft YaHei";
  ctx.fillText(fmt.format(max), 8, padding.top + 4);
  ctx.fillText(fmt.format(min), 8, height - padding.bottom);
  ctx.fillText(series[0].date, padding.left, height - 8);
  ctx.fillText(series[series.length - 1].date, width - padding.right - 88, height - 8);

  lines.forEach((line) => {
    ctx.strokeStyle = line.color;
    ctx.lineWidth = line.width || 2;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.beginPath();
    let started = false;
    series.forEach((d, i) => {
      const value = Number(d[line.key]);
      if (!Number.isFinite(value)) return;
      if (!started) {
        ctx.moveTo(x(i), y(value));
        started = true;
      } else {
        ctx.lineTo(x(i), y(value));
      }
    });
    ctx.stroke();
  });
}

function renderCharts(charts) {
  drawLineChart("trendChart", charts.hs300_trend, [
    { key: "close", color: "#5ca9ff", width: 2.5 },
    { key: "ma20", color: "#fdb022", width: 1.5 },
    { key: "ma60", color: "#32d583", width: 1.5 },
    { key: "ma120", color: "#9b8cff", width: 1.2 },
  ]);
  drawLineChart("rsChart", charts.relative_strength, [
    { key: "ratio", color: "#9b8cff", width: 2.5 },
    { key: "ma20", color: "#fdb022", width: 1.5 },
    { key: "ma60", color: "#32d583", width: 1.5 },
  ]);
  drawLineChart("erpChart", charts.erp, [
    { key: "erp", color: "#fdb022", width: 2.5 },
  ]);
  drawLineChart("marginChart", charts.margin, [
    { key: "融资余额流通市值占比", color: "#f97066", width: 2.5 },
  ]);
}

async function loadDashboard(force = false) {
  elements.refreshBtn.disabled = true;
  elements.refreshBtn.textContent = force ? "刷新中..." : "加载中...";
  try {
    const { payload, mode } = await fetchDashboardPayload(force);
    state.lastPayload = payload;
    state.mode = mode;
    renderHeadline(payload, mode);
    renderWarnings(payload.warnings);
    renderRedFlags(payload.headline?.red_flags || []);
    renderConfirmationMatrix(payload.headline?.confirmation_matrix || []);
    renderModules(payload.modules || []);
    renderSignals(payload.modules || []);
    renderSources(payload.source_quality || []);
    renderCharts(payload.charts || {});
  } catch (error) {
    elements.warnings.classList.remove("hidden");
    elements.warnings.innerHTML = `<strong>加载失败</strong><p>${error.message}</p>`;
  } finally {
    elements.refreshBtn.disabled = false;
    elements.refreshBtn.textContent = state.mode === "static" ? "重新读取快照" : "立即刷新";
  }
}

elements.refreshBtn.addEventListener("click", () => loadDashboard(true));
window.addEventListener("resize", () => renderCharts(state.lastPayload?.charts || {}));
const state = { lastPayload: null, timer: null, mode: null };
loadDashboard(false);
state.timer = window.setInterval(() => loadDashboard(false), 5 * 60_000);
