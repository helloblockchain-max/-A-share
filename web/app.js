const fmt = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 });
const pct = (v) => (Number.isFinite(v) ? `${fmt.format(v * 100)}%` : "--");
const val = (v, suffix = "") => (Number.isFinite(v) ? `${fmt.format(v)}${suffix}` : "--");

const elements = {
  refreshBtn: document.getElementById("refreshBtn"),
  lastUpdated: document.getElementById("lastUpdated"),
  totalScore: document.getElementById("totalScore"),
  scoreRing: document.getElementById("scoreRing"),
  scoreStatus: document.getElementById("scoreStatus"),
  scoreDetail: document.getElementById("scoreDetail"),
  erpValue: document.getElementById("erpValue"),
  tenYield: document.getElementById("tenYield"),
  advanceRatio: document.getElementById("advanceRatio"),
  financingRatio: document.getElementById("financingRatio"),
  moduleBars: document.getElementById("moduleBars"),
  signalsTable: document.getElementById("signalsTable"),
  sourceQuality: document.getElementById("sourceQuality"),
  warnings: document.getElementById("warnings"),
};

function scoreColor(score) {
  if (score >= 75) return "#f97066";
  if (score >= 60) return "#fdb022";
  if (score >= 40) return "#f7c948";
  return "#32d583";
}

function renderHeadline(payload) {
  const headline = payload.headline || {};
  elements.totalScore.textContent = fmt.format(payload.total_score);
  elements.scoreRing.style.setProperty("--score", `${payload.total_score * 3.6}deg`);
  elements.scoreRing.style.background = `radial-gradient(circle, var(--panel) 58%, transparent 60%), conic-gradient(${scoreColor(payload.total_score)} ${payload.total_score * 3.6}deg, rgba(255,255,255,0.10) 0)`;
  elements.scoreStatus.textContent = payload.status;
  elements.scoreDetail.textContent = payload.status_detail;
  elements.erpValue.textContent = val(headline.latest_erp, "%");
  elements.tenYield.textContent = val(headline.ten_year_yield, "%");
  elements.advanceRatio.textContent = pct(headline.advance_ratio);
  elements.financingRatio.textContent = val(headline.financing_buy_ratio, "%");
  elements.lastUpdated.textContent = `生成：${payload.generated_at || "--"}｜数据：${payload.as_of || "--"}`;
}

function renderWarnings(warnings) {
  if (!warnings || warnings.length === 0) {
    elements.warnings.classList.add("hidden");
    elements.warnings.innerHTML = "";
    return;
  }
  elements.warnings.classList.remove("hidden");
  elements.warnings.innerHTML = `<strong>风险提示</strong><ul>${warnings.map((w) => `<li>${w}</li>`).join("")}</ul>`;
}

function renderModules(modules) {
  elements.moduleBars.innerHTML = modules
    .map((m) => {
      const color = scoreColor(m.raw_score);
      return `
        <div class="module-row">
          <strong>${m.name}</strong>
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
  elements.sourceQuality.innerHTML = (sources || [])
    .map((s) => {
      const link = s.url && !s.url.startsWith("local://") ? `<a href="${s.url}" target="_blank" rel="noreferrer">打开来源</a>` : "本地探测";
      return `
        <article class="source-card">
          <h3>${s.name}</h3>
          <span class="pill ${s.status}">${s.status}</span>
          <p>数据日期：${s.as_of || "--"}｜拉取：${s.fetched_at || "--"}｜行数：${s.row_count ?? 0}</p>
          <p>${s.message || ""}</p>
          <p>${link}</p>
        </article>
      `;
    })
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
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const x = (i) => padding.left + (i / (series.length - 1)) * (width - padding.left - padding.right);
  const y = (v) => padding.top + (1 - (v - min) / span) * (height - padding.top - padding.bottom);

  ctx.strokeStyle = "rgba(255,255,255,0.12)";
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
  ]);
  drawLineChart("rsChart", charts.relative_strength, [
    { key: "ratio", color: "#9b8cff", width: 2.5 },
    { key: "ma20", color: "#fdb022", width: 1.5 },
    { key: "ma60", color: "#32d583", width: 1.5 },
  ]);
}

async function loadDashboard(force = false) {
  elements.refreshBtn.disabled = true;
  elements.refreshBtn.textContent = force ? "刷新中..." : "加载中...";
  try {
    const response = await fetch(`/api/dashboard${force ? "?force=true" : ""}`);
    if (!response.ok) throw new Error(`接口返回 ${response.status}`);
    const payload = await response.json();
    renderHeadline(payload);
    renderWarnings(payload.warnings);
    renderModules(payload.modules || []);
    renderSignals(payload.modules || []);
    renderSources(payload.source_quality || []);
    renderCharts(payload.charts || {});
  } catch (error) {
    elements.warnings.classList.remove("hidden");
    elements.warnings.innerHTML = `<strong>加载失败</strong><p>${error.message}</p>`;
  } finally {
    elements.refreshBtn.disabled = false;
    elements.refreshBtn.textContent = "立即刷新";
  }
}

elements.refreshBtn.addEventListener("click", () => loadDashboard(true));
window.addEventListener("resize", () => loadDashboard(false));
loadDashboard(false);
