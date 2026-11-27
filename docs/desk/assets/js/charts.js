/* Hand-rolled SVG charting — no external libraries, no CDN, nothing to break.
   Exposes window.Charts with:
     line(el, {points, xMin, xMax, yMin, yMax, height, color, markers, label})
     depth(el, orderbook, {depth})
     spark(el, points)
*/
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const fmtPrice = (v) => (v === null || v === undefined || Number.isNaN(v) ? "—" : "$" + Number(v).toFixed(2));
  const pad2 = (n) => String(n).padStart(2, "0");

  function fmtTime(ts, span) {
    const d = new Date(ts * 1000);
    if (span <= 3600 * 2) return `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
    if (span <= 86400 * 2) return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
    return `${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
  }

  function el(name, attrs) {
    const node = document.createElementNS(NS, name);
    for (const key in attrs || {}) node.setAttribute(key, attrs[key]);
    return node;
  }

  function niceTicks(min, max, count) {
    if (!isFinite(min) || !isFinite(max) || min === max) return [min];
    const span = max - min;
    const step = Math.pow(10, Math.floor(Math.log10(span / count)));
    const mult = [1, 2, 2.5, 5, 10].find((m) => span / (step * m) <= count) || 10;
    const s = step * mult;
    const start = Math.ceil(min / s) * s;
    const out = [];
    for (let v = start; v <= max + 1e-9; v += s) out.push(Number(v.toFixed(6)));
    return out;
  }

  function line(container, opts) {
    if (!container) return;
    const state = { opts, width: 0, svg: null, tip: null };
    container.innerHTML = "";

    const tip = document.createElement("div");
    tip.className = "chart-tip";
    container.appendChild(tip);

    const svg = el("svg", { class: "chart", role: "img" });
    svg.setAttribute("aria-label", "Contract price over time");
    container.appendChild(svg);

    const defs = el("defs");
    const grad = el("linearGradient", { id: "areaGradient", x1: "0", y1: "0", x2: "0", y2: "1" });
    grad.appendChild(el("stop", { offset: "0%", "stop-color": opts.color || "#7c8cff", "stop-opacity": "0.55" }));
    grad.appendChild(el("stop", { offset: "100%", "stop-color": opts.color || "#7c8cff", "stop-opacity": "0" }));
    defs.appendChild(grad);
    svg.appendChild(defs);

    function draw() {
      const width = Math.max(280, container.clientWidth || 640);
      const height = opts.height || 300;
      const m = { top: 12, right: 54, bottom: 26, left: 12 };
      const w = width - m.left - m.right;
      const h = height - m.top - m.bottom;
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      svg.setAttribute("width", width);
      svg.setAttribute("height", height);
      svg.innerHTML = "";
      svg.appendChild(defs);

      const points = (opts.points || [])
        .filter((p) => Array.isArray(p) && p.length >= 2 && isFinite(p[0]) && isFinite(p[1]))
        .map((p) => [Number(p[0]), Number(p[1])])
        .sort((a, b) => a[0] - b[0]);

      if (!points.length) {
        const msg = el("text", { x: width / 2, y: height / 2, "text-anchor": "middle" });
        msg.textContent = opts.emptyText || "No price points in this window yet.";
        svg.appendChild(msg);
        return;
      }

      const xMin = opts.xMin || points[0][0];
      const xMax = opts.xMax || points[points.length - 1][0] || xMin + 60;
      const span = Math.max(1, xMax - xMin);
      const values = points.map((p) => p[1]);
      let yMin = opts.yMin;
      let yMax = opts.yMax;
      if (yMin === undefined || yMin === null) {
        yMin = Math.min(...values);
        yMax = Math.max(...values);
        const pad = Math.max(0.01, (yMax - yMin) * 0.15);
        yMin = Math.max(0, yMin - pad);
        yMax = Math.min(1, yMax + pad);
      }
      if (yMax <= yMin) { yMax = Math.min(1, yMin + 0.02); }

      const sx = (t) => m.left + ((t - xMin) / span) * w;
      const sy = (v) => m.top + h - ((v - yMin) / (yMax - yMin)) * h;

      // y grid + labels
      const yTicks = niceTicks(yMin, yMax, 5);
      yTicks.forEach((v) => {
        const y = sy(v);
        svg.appendChild(el("line", { class: "grid-line", x1: m.left, x2: m.left + w, y1: y, y2: y }));
        const label = el("text", { x: m.left + w + 8, y: y + 3.5 });
        label.textContent = "$" + Number(v).toFixed(2);
        svg.appendChild(label);
      });

      // x grid + labels
      const xTicks = niceTicks(xMin, xMax, 5);
      xTicks.forEach((t) => {
        const x = sx(t);
        if (x < m.left - 1 || x > m.left + w + 1) return;
        svg.appendChild(el("line", { class: "grid-line", x1: x, x2: x, y1: m.top, y2: m.top + h }));
        const label = el("text", { x, y: m.top + h + 16, "text-anchor": "middle" });
        label.textContent = fmtTime(t, span);
        svg.appendChild(label);
      });

      svg.appendChild(el("line", { class: "axis", x1: m.left, x2: m.left + w, y1: m.top + h, y2: m.top + h }));

      // markers (alerts)
      (opts.markers || []).forEach((marker) => {
        const x = sx(Number(marker.ts));
        if (!isFinite(x) || x < m.left || x > m.left + w) return;
        svg.appendChild(el("line", {
          x1: x, x2: x, y1: m.top, y2: m.top + h,
          stroke: marker.direction === "down" ? "#ff5d7a" : "#35d07f",
          "stroke-width": 1, "stroke-dasharray": "2 3", opacity: 0.7,
        }));
      });

      // series path
      const path = points.map((p, i) => `${i === 0 ? "M" : "L"}${sx(p[0]).toFixed(2)},${sy(p[1]).toFixed(2)}`).join(" ");
      const area = `${path} L${sx(points[points.length - 1][0]).toFixed(2)},${m.top + h} L${sx(points[0][0]).toFixed(2)},${m.top + h} Z`;
      svg.appendChild(el("path", { class: "area", d: area }));
      svg.appendChild(el("path", { class: "line", d: path, stroke: opts.color || "#7c8cff" }));

      const last = points[points.length - 1];
      svg.appendChild(el("circle", { class: "dot", cx: sx(last[0]), cy: sy(last[1]), r: 4, stroke: opts.color || "#7c8cff" }));

      // crosshair + tooltip
      const cross = el("line", { class: "crosshair", x1: 0, x2: 0, y1: m.top, y2: m.top + h, opacity: 0 });
      const hover = el("circle", { r: 4, fill: "#fff", opacity: 0 });
      svg.appendChild(cross);
      svg.appendChild(hover);

      const hit = el("rect", { x: m.left, y: m.top, width: w, height: h, fill: "transparent" });
      svg.appendChild(hit);

      function move(evt) {
        const rect = svg.getBoundingClientRect();
        const px = ((evt.clientX - rect.left) / rect.width) * width;
        let best = points[0];
        let bestDist = Infinity;
        points.forEach((p) => {
          const d = Math.abs(sx(p[0]) - px);
          if (d < bestDist) { bestDist = d; best = p; }
        });
        const x = sx(best[0]);
        const y = sy(best[1]);
        cross.setAttribute("x1", x); cross.setAttribute("x2", x); cross.setAttribute("opacity", 1);
        hover.setAttribute("cx", x); hover.setAttribute("cy", y); hover.setAttribute("opacity", 1);
        tip.style.display = "block";
        tip.textContent = `${fmtTime(best[0], span)} · ${fmtPrice(best[1])}`;
        const tipX = Math.min(Math.max(x / width * rect.width, 8), rect.width - tip.offsetWidth - 8);
        tip.style.left = `${tipX}px`;
        tip.style.top = `${Math.max(4, (y / height) * rect.height - 34)}px`;
      }
      function leave() {
        cross.setAttribute("opacity", 0);
        hover.setAttribute("opacity", 0);
        tip.style.display = "none";
      }
      hit.addEventListener("mousemove", move);
      hit.addEventListener("mouseleave", leave);
      hit.addEventListener("touchmove", (e) => move(e.touches[0]), { passive: true });
      hit.addEventListener("touchend", leave);

      state.width = width;
    }

    draw();
    if (typeof ResizeObserver === "function") {
      const observer = new ResizeObserver(() => draw());
      observer.observe(container);
    }
    state.redraw = draw;
    container.__chart = state;
  }

  function depth(container, book, opts) {
    if (!container) return;
    const maxLevels = (opts && opts.depth) || 6;
    container.innerHTML = "";
    if (!book) {
      container.innerHTML = '<div class="empty">Orderbook depth not captured for this market (only the most active markets are enriched each cycle).</div>';
      return;
    }
    const bids = (book.yes_bids || []).slice(0, maxLevels);
    const asks = (book.yes_asks || []).slice(0, maxLevels);
    const maxContracts = Math.max(1, ...bids.map((l) => l.contracts), ...asks.map((l) => l.contracts));

    const grid = document.createElement("div");
    grid.className = "depth";

    function column(title, levels, cls) {
      const box = document.createElement("div");
      const h = document.createElement("h4");
      h.textContent = title;
      box.appendChild(h);
      if (!levels.length) {
        const empty = document.createElement("div");
        empty.className = "small";
        empty.textContent = "No resting orders.";
        box.appendChild(empty);
      }
      levels.forEach((level) => {
        const row = document.createElement("div");
        row.className = "depth-row";
        const p = document.createElement("span");
        p.className = "p";
        p.textContent = fmtPrice(level.price);
        const bar = document.createElement("div");
        bar.className = "depth-bar " + cls;
        const fill = document.createElement("span");
        fill.style.width = `${Math.max(2, (level.contracts / maxContracts) * 100)}%`;
        bar.appendChild(fill);
        const c = document.createElement("span");
        c.className = "c";
        c.textContent = Number(level.contracts).toLocaleString(undefined, { maximumFractionDigits: 0 });
        row.append(p, bar, c);
        box.appendChild(row);
      });
      return box;
    }

    grid.appendChild(column("Yes bids (buy YES here)", bids, "bid"));
    grid.appendChild(column("Yes asks (implied from NO bids)", asks, "ask"));
    container.appendChild(grid);

    const note = document.createElement("div");
    note.className = "chart-note";
    const spread = book.spread !== null && book.spread !== undefined ? `$${Number(book.spread).toFixed(2)}` : "n/a";
    note.textContent = `Spread ${spread} · ${Number(book.yes_depth_contracts || 0).toLocaleString()} YES-bid contracts · ${Number(book.no_depth_contracts || 0).toLocaleString()} NO-bid contracts resting. Asks are implied as $1.00 − opposite bid (Kalshi returns bids only).`;
    container.appendChild(note);
  }

  function spark(container, points, color) {
    if (!container) return;
    const width = Math.max(60, container.clientWidth || 120);
    const height = 26;
    const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, width, height });
    const vals = (points || []).map((p) => Number(p[1])).filter((v) => isFinite(v));
    if (vals.length < 2) {
      container.innerHTML = '<span class="small">—</span>';
      return;
    }
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const span = max - min || 0.01;
    const d = vals
      .map((v, i) => `${i === 0 ? "M" : "L"}${(i / (vals.length - 1)) * width},${height - ((v - min) / span) * (height - 4) - 2}`)
      .join(" ");
    svg.appendChild(el("path", { d, fill: "none", stroke: color || "#7c8cff", "stroke-width": 1.5 }));
    container.innerHTML = "";
    container.appendChild(svg);
  }

  window.Charts = { line, depth, spark, fmtPrice, fmtTime };
})();
