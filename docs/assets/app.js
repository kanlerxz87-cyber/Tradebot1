/* Shared dashboard utilities — vanilla JS, no external dependencies/CDNs,
   so the site works fully offline-reproducibly and nothing here depends on a
   third-party script's uptime. */

const DATA_BASE = (() => {
  // Works whether the page is served at the repo root or under a subpath.
  const path = window.location.pathname;
  const depth = path.replace(/^\//, "").split("/").filter(Boolean);
  // pages live directly under docs/, so data/ is always a sibling.
  return "data/";
})();

async function fetchJSON(relPath, fallback = null) {
  try {
    const res = await fetch(DATA_BASE + relPath + "?_=" + Date.now(), { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    return await res.json();
  } catch (err) {
    console.warn("fetchJSON failed for", relPath, err);
    return fallback;
  }
}

function timeAgo(iso) {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const diffMs = Date.now() - then;
  const s = Math.floor(diffMs / 1000);
  if (s < 5) return "just now";
  if (s < 60) return s + "s ago";
  const m = Math.floor(s / 60);
  if (m < 60) return m + "m ago";
  const h = Math.floor(m / 60);
  if (h < 24) return h + "h ago";
  const d = Math.floor(h / 24);
  return d + "d ago";
}

function fmtMoney(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  return "$" + Number(v).toFixed(2);
}

function fmtPrice(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  return "$" + Number(v).toFixed(2);
}

function fmtNum(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  return Number(v).toLocaleString();
}

function escapeHtml(s) {
  if (s === null || s === undefined) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function statusBadge(status) {
  if (!status) return "";
  if (status === "awaiting_first_collection_run") {
    return '<span class="badge empty">no data yet</span>';
  }
  if (status === "ok") return '<span class="badge ok">live</span>';
  if (status === "partial_error") return '<span class="badge warn">partial</span>';
  if (status === "error") return '<span class="badge warn">error</span>';
  return "";
}

function setActiveNav(id) {
  document.querySelectorAll("nav.main-nav a[data-nav]").forEach((a) => {
    if (a.getAttribute("data-nav") === id) a.classList.add("active");
  });
}

function renderEmptyState(container, title, body) {
  container.innerHTML = `<div class="empty-state"><strong>${escapeHtml(title)}</strong><br/>${body}</div>`;
}

/* ---------------- Markets table ---------------- */
function renderMarketsTable(container, doc) {
  if (!doc || !doc.markets || doc.markets.length === 0) {
    renderEmptyState(
      container,
      "No data yet",
      `The scheduled collector (<code>.github/workflows/collect-kalshi-data.yml</code>) hasn't completed a run against this topic yet, or found no open markets in it this run. No placeholder numbers are shown — see the <a href="flagged-for-review.html">Flagged for Review</a> page.`
    );
    return;
  }
  const rows = doc.markets
    .map((m) => {
      const resCell =
        m.result === "yes" || m.result === "no"
          ? `<span class="${m.result === "yes" ? "pill-up" : "pill-down"}">${m.result.toUpperCase()}</span>`
          : (m.status || "—");
      return `<tr>
        <td><a href="${escapeHtml(m.kalshi_url)}" target="_blank" rel="noopener">${escapeHtml(m.title || m.ticker)}</a>
            <div class="source-link">${escapeHtml(m.ticker)}</div></td>
        <td class="num">${fmtPrice(m.price)}</td>
        <td class="num">${fmtNum(m.volume)}</td>
        <td class="num">${fmtNum(m.open_interest)}</td>
        <td>${resCell}</td>
        <td class="source-link"><a href="${escapeHtml(m.kalshi_url)}" target="_blank" rel="noopener">kalshi.com ↗</a></td>
      </tr>`;
    })
    .join("");
  container.innerHTML = `<div class="table-wrap"><table>
    <thead><tr><th>Market</th><th>Price</th><th>Volume</th><th>Open Int.</th><th>Status / Result</th><th>Source</th></tr></thead>
    <tbody>${rows}</tbody>
  </table></div>`;
}

/* ---------------- Alert feeds (scrolling chat style) ---------------- */
function renderAlertsFeed(container, alerts, opts = {}) {
  if (!alerts || alerts.length === 0) {
    renderEmptyState(
      container,
      "No alerts yet",
      `Alerts fire when a tracked market's price moves \u2265 $0.10 between collector runs. None recorded yet.`
    );
    return;
  }
  const items = alerts
    .map((a) => {
      const dirClass = a.direction === "up" ? "pill-up" : "pill-down";
      const arrow = a.direction === "up" ? "\u25B2" : "\u25BC";
      const scoreHtml = opts.showScore && a.high_roi_score !== undefined
        ? `<div class="score">high-ROI score: ${a.high_roi_score}</div>` : "";
      return `<div class="msg">
        <div class="ts">${timeAgo(a.timestamp)}</div>
        <div class="body">
          <strong>[${escapeHtml(a.topic_label || a.topic)}]</strong>
          <a href="${escapeHtml(a.kalshi_url)}" target="_blank" rel="noopener">${escapeHtml(a.title || a.ticker)}</a>
          moved <span class="${dirClass}">${arrow} ${Math.abs(a.delta).toFixed(2)}</span>
          (${fmtPrice(a.previous_price)} \u2192 ${fmtPrice(a.new_price)})
          ${scoreHtml}
        </div>
      </div>`;
    })
    .join("");
  container.innerHTML = items;
}

/* ---------------- Tiny dependency-free line chart ---------------- */
function drawLineChart(canvas, points, { color = "#35d08a", yMin = 0, yMax = 1 } = {}) {
  const ctx = canvas.getContext && canvas.getContext("2d");
  if (!ctx) return; // canvas 2D context unavailable in this environment; fail quietly
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 600;
  const h = canvas.clientHeight || 300;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  const padL = 46, padB = 24, padT = 10, padR = 10;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;

  ctx.strokeStyle = "#262c3a";
  ctx.fillStyle = "#8d95a8";
  ctx.font = "11px -apple-system, sans-serif";
  ctx.lineWidth = 1;
  const gridLines = 4;
  for (let i = 0; i <= gridLines; i++) {
    const y = padT + (plotH * i) / gridLines;
    ctx.beginPath();
    ctx.moveTo(padL, y);
    ctx.lineTo(w - padR, y);
    ctx.stroke();
    const val = yMax - ((yMax - yMin) * i) / gridLines;
    ctx.fillText("$" + val.toFixed(2), 4, y + 4);
  }

  if (!points || points.length === 0) {
    ctx.fillStyle = "#8d95a8";
    ctx.fillText("No price history yet", padL, padT + plotH / 2);
    return;
  }

  const xs = points.map((p) => new Date(p.ts).getTime());
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const spanX = Math.max(maxX - minX, 1);

  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  points.forEach((p, i) => {
    const x = padL + ((new Date(p.ts).getTime() - minX) / spanX) * plotW;
    const y = padT + plotH - ((p.price - yMin) / (yMax - yMin)) * plotH;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  ctx.fillStyle = color;
  const last = points[points.length - 1];
  const lastX = padL + ((new Date(last.ts).getTime() - minX) / spanX) * plotW;
  const lastY = padT + plotH - ((last.price - yMin) / (yMax - yMin)) * plotH;
  ctx.beginPath();
  ctx.arc(lastX, lastY, 3.5, 0, Math.PI * 2);
  ctx.fill();
}

function filterPointsByRange(points, rangeSeconds) {
  if (!points || points.length === 0) return [];
  const cutoff = Date.now() - rangeSeconds * 1000;
  const filtered = points.filter((p) => new Date(p.ts).getTime() >= cutoff);
  return filtered.length >= 2 ? filtered : points.slice(-Math.max(points.length, 2));
}

/* ---------------- Minimal, dependency-free Markdown renderer ----------------
   Supports just enough of GitHub-flavored markdown for our own three report
   files (headers, bold/italic, links, tables, code, blockquotes, lists, hr).
   Not a general-purpose parser. */
function mdToHtml(md) {
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  let html = "";
  let inCode = false, inTable = false, inList = false;
  let paraBuf = [];

  // Links first (so underscores/asterisks inside URLs or link text never get
  // mistaken for emphasis markers), then code spans, then bold, then italic
  // — italic only matches underscores at word boundaries so mid-identifier
  // underscores (e.g. in a URL like getting_started) are left alone.
  const inline = (s) => {
    const escaped = escapeHtml(s);
    const withLinks = escaped.replace(
      /\[([^\]]+)\]\(([^)]+)\)/g,
      (_m, text, href) => `@@LINK@@${encodeURIComponent(text)}@@${encodeURIComponent(href)}@@ENDLINK@@`
    );
    let out = withLinks
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[\s(])_([^_\s][^_]*?)_(?=[\s).,;:!?]|$)/g, "$1<em>$2</em>");
    out = out.replace(
      /@@LINK@@([^@]*)@@([^@]*)@@ENDLINK@@/g,
      (_m, text, href) => `<a href="${decodeURIComponent(href)}" target="_blank" rel="noopener">${decodeURIComponent(text)}</a>`
    );
    return out;
  };

  const flushPara = () => {
    if (paraBuf.length) {
      html += `<p>${inline(paraBuf.join(" "))}</p>`;
      paraBuf = [];
    }
  };

  for (let raw of lines) {
    const line = raw;
    if (line.trim().startsWith("```")) {
      flushPara();
      inCode = !inCode;
      html += inCode ? "<pre><code>" : "</code></pre>";
      continue;
    }
    if (inCode) { html += escapeHtml(line) + "\n"; continue; }

    if (/^\s*\|.*\|\s*$/.test(line)) {
      flushPara();
      const cells = line.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      if (!inTable) { html += "<table><thead><tr>" + cells.map((c) => `<th>${inline(c)}</th>`).join("") + "</tr></thead><tbody>"; inTable = true; continue; }
      if (cells.every((c) => /^:?-+:?$/.test(c))) { continue; }
      html += "<tr>" + cells.map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>";
      continue;
    } else if (inTable) {
      html += "</tbody></table>";
      inTable = false;
    }

    if (/^#{1,6}\s/.test(line)) {
      flushPara();
      const level = line.match(/^#+/)[0].length;
      html += `<h${Math.min(level + 1, 6)}>${inline(line.replace(/^#{1,6}\s/, ""))}</h${Math.min(level + 1, 6)}>`;
      continue;
    }
    if (/^>\s?/.test(line)) {
      flushPara();
      html += `<blockquote>${inline(line.replace(/^>\s?/, ""))}</blockquote>`;
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      flushPara();
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${inline(line.replace(/^\s*[-*]\s+/, ""))}</li>`;
      continue;
    } else if (inList) {
      html += "</ul>";
      inList = false;
    }
    if (/^\s*---+\s*$/.test(line)) { flushPara(); html += "<hr/>"; continue; }
    if (line.trim() === "") { flushPara(); continue; }
    paraBuf.push(line.trim());
  }
  flushPara();
  if (inTable) html += "</tbody></table>";
  if (inList) html += "</ul>";
  return html;
}

async function renderMarkdownPage(containerId, mdPath) {
  const container = document.getElementById(containerId);
  try {
    const res = await fetch(mdPath + "?_=" + Date.now(), { cache: "no-store" });
    const text = await res.text();
    container.innerHTML = mdToHtml(text);
  } catch (err) {
    container.innerHTML = `<p>Could not load ${escapeHtml(mdPath)}: ${escapeHtml(String(err))}</p>`;
  }
}
