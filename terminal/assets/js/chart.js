/* chart.js — dependency-free canvas price chart.
 *
 * X axis: time, over the window the visitor picked (30 s … 1 day).
 * Y axis: contract price, $0.00–$1.00 (a binary contract cannot settle outside that).
 *
 * Two kinds of point share the line and are distinguished in the tooltip, because
 * they are not the same evidence:
 *   candle — a period from the official candlestick endpoint: its last traded price,
 *            or, when nothing traded in that period, the quoted bid/ask midpoint.
 *   poll   — a price this tab read itself, with the time it read it.
 * Nothing is drawn between two points that do not exist, and the "no data" state says
 * which of the two is missing.
 */
'use strict';

class PriceChart {
  constructor(canvas, opts = {}) {
    this.canvas = canvas;
    /* jsdom (used by terminal/tests/render.test.mjs) has no 2-D context, and a real
       browser can refuse one too. The chart then renders nothing rather than throwing
       and taking the rest of the dashboard down with it. */
    this.ctx = canvas.getContext ? canvas.getContext('2d') : null;
    if (!this.ctx) { this.points = []; this.rangeSec = opts.rangeSec || 300; return; }
    this.points = [];                      // [{t: ms, p: dollars, source, basis}]
    this.rangeSec = opts.rangeSec || 300;
    this.interval = null;                  // candle period in minutes, for the axis label
    this.keepMs = 7 * 24 * 3600 * 1000;
    this.hover = null;
    this.maxPoints = 6000;
    canvas.addEventListener('mousemove', (e) => this.onHover(e));
    canvas.addEventListener('touchmove', (e) => {
      if (e.touches && e.touches[0]) this.onHover({ clientX: e.touches[0].clientX, clientY: e.touches[0].clientY });
    }, { passive: true });
    canvas.addEventListener('mouseleave', () => { this.hover = null; this.draw(); });
    window.addEventListener('resize', () => this.draw());
  }

  setRange(sec) { this.rangeSec = sec; this.draw(); }

  clear() { this.points = []; this.draw(); }

  /* Replace the whole series (used after a candle backfill merges with live points). */
  setPoints(points, { rangeSec, interval } = {}) {
    if (rangeSec) this.rangeSec = rangeSec;
    if (interval !== undefined) this.interval = interval;
    this.points = (points || [])
      .filter((p) => p && Number.isFinite(p.t) && Number.isFinite(p.p))
      .sort((a, b) => a.t - b.t);
    if (this.points.length > this.maxPoints) this.points = this.points.slice(-this.maxPoints);
    this.draw();
  }

  addPoint(t, p, meta = {}) {
    if (p == null || !Number.isFinite(p)) return;
    const last = this.points[this.points.length - 1];
    if (last && last.source === 'poll' && Math.abs(last.t - t) < 50 && Math.abs(last.p - p) < 1e-9) {
      // identical poll reading: keep one point
    } else {
      this.points.push({ t, p, source: meta.source || 'poll', basis: meta.basis });
    }
    const cutoff = Date.now() - this.keepMs;
    while (this.points.length > 2 && this.points[0].t < cutoff) this.points.shift();
    if (this.points.length > this.maxPoints) this.points.splice(0, this.points.length - this.maxPoints);
    this.draw();
  }

  onHover(e) {
    const rect = this.canvas.getBoundingClientRect();
    this.hover = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    this.draw();
  }

  resize() {
    const dpr = window.devicePixelRatio || 1;
    const rect = this.canvas.getBoundingClientRect();
    if (rect.width === 0) return false;
    this.canvas.width = Math.round(rect.width * dpr);
    this.canvas.height = Math.round(rect.height * dpr);
    if (this.ctx && this.ctx.setTransform) this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.W = rect.width; this.H = rect.height;
    return true;
  }

  timeLabel(t, rangeSec) {
    if (rangeSec <= 120) return new Date(t).toLocaleTimeString('en-US', { hour12: false, minute: '2-digit', second: '2-digit' });
    if (rangeSec <= 7200) return new Date(t).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' });
    return new Date(t).toLocaleDateString('en-US', { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
  }

  resolutionLabel() {
    if (this.interval === 1) return '1-minute candles';
    if (this.interval === 60) return '1-hour candles';
    if (this.interval === 1440) return '1-day candles';
    return 'tab observations only';
  }

  draw() {
    if (!this.ctx) return;
    if (!this.resize()) return;
    const { ctx, W, H } = this;
    const padL = 46, padR = 12, padT = 14, padB = 26;
    const iw = W - padL - padR, ih = H - padT - padB;
    ctx.clearRect(0, 0, W, H);

    const now = Date.now();
    const t0 = now - this.rangeSec * 1000;
    const inWindow = this.points.filter((pt) => pt.t >= t0 && pt.t <= now + 1000);

    /* Y axis grid + labels ($0.00..$1.00) */
    ctx.font = '11px ui-monospace, Menlo, Consolas, monospace';
    ctx.textBaseline = 'middle';
    for (let i = 0; i <= 10; i += 1) {
      const price = i / 10;
      const y = padT + ih - price * ih;
      const major = i % 2 === 0;
      ctx.strokeStyle = major ? '#243154' : '#1a2440';
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
      if (major) {
        ctx.fillStyle = '#8b96b8';
        ctx.fillText('$' + price.toFixed(2), 6, y);
      }
    }

    ctx.save();
    ctx.translate(12, padT + ih / 2); ctx.rotate(-Math.PI / 2);
    ctx.fillStyle = '#5d688f'; ctx.fillText('Contract price', -34, 0);
    ctx.restore();

    /* X axis ticks */
    const tickN = Math.min(6, Math.max(3, Math.floor(iw / 110)));
    ctx.textBaseline = 'top';
    for (let i = 0; i <= tickN; i++) {
      const t = t0 + (this.rangeSec * 1000 * i) / tickN;
      const x = padL + (iw * i) / tickN;
      ctx.strokeStyle = '#1a2440';
      ctx.beginPath(); ctx.moveTo(x, padT + ih); ctx.lineTo(x, padT + ih + 4); ctx.stroke();
      ctx.fillStyle = '#8b96b8';
      const label = this.timeLabel(t, this.rangeSec);
      const w = ctx.measureText(label).width;
      ctx.fillText(label, Math.min(Math.max(x - w / 2, padL - 10), W - padR - w), padT + ih + 8);
    }

    const X = (t) => padL + ((t - t0) / (this.rangeSec * 1000)) * iw;
    const Y = (p) => padT + (1 - p) * ih;

    if (inWindow.length < 2) {
      ctx.fillStyle = '#5d688f';
      ctx.font = '13px -apple-system, Segoe UI, sans-serif';
      ctx.textAlign = 'center';
      const msg = inWindow.length === 1
        ? 'One point in this window — wait for the next poll, or widen the window.'
        : 'No points in this window yet. Candle history and tab observations both load from the Kalshi demo API.';
      ctx.fillText(msg, padL + iw / 2, padT + ih / 2);
      ctx.textAlign = 'left';
      ctx.strokeStyle = '#243154'; ctx.strokeRect(padL, padT, iw, ih);
      return;
    }

    /* area fill under the line */
    ctx.beginPath();
    ctx.moveTo(X(inWindow[0].t), Y(inWindow[0].p));
    for (let i = 1; i < inWindow.length; i++) ctx.lineTo(X(inWindow[i].t), Y(inWindow[i].p));
    const grad = ctx.createLinearGradient(0, padT, 0, padT + ih);
    grad.addColorStop(0, 'rgba(0, 221, 148, 0.28)');
    grad.addColorStop(1, 'rgba(0, 221, 148, 0.01)');
    ctx.save();
    ctx.lineTo(X(inWindow[inWindow.length - 1].t), padT + ih);
    ctx.lineTo(X(inWindow[0].t), padT + ih);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();
    ctx.restore();

    /* candle-derived points form the first segment; poll points are drawn on top and
       slightly thicker so a visitor can see where their own session took over. */
    const drawLine = (pts, colour, width) => {
      if (pts.length < 2) return;
      ctx.beginPath();
      ctx.moveTo(X(pts[0].t), Y(pts[0].p));
      for (let i = 1; i < pts.length; i++) ctx.lineTo(X(pts[i].t), Y(pts[i].p));
      ctx.strokeStyle = colour;
      ctx.lineWidth = width;
      ctx.lineJoin = 'round';
      ctx.stroke();
    };
    drawLine(inWindow.filter((p) => p.source !== 'poll'), 'rgba(0,221,148,0.55)', 1.5);
    drawLine(inWindow, '#00dd94', 2);
    ctx.strokeStyle = '#243154'; ctx.lineWidth = 1;
    ctx.strokeRect(padL, padT, iw, ih);

    /* last price marker */
    const last = inWindow[inWindow.length - 1];
    ctx.beginPath(); ctx.arc(X(last.t), Y(last.p), 4, 0, Math.PI * 2);
    ctx.fillStyle = '#00dd94'; ctx.fill();
    ctx.strokeStyle = '#04120a'; ctx.stroke();

    /* hover crosshair + readout */
    if (this.hover && this.hover.x >= padL && this.hover.x <= padL + iw) {
      const targetT = t0 + ((this.hover.x - padL) / iw) * this.rangeSec * 1000;
      let nearest = inWindow[0], best = Infinity;
      for (const pt of inWindow) {
        const d = Math.abs(pt.t - targetT);
        if (d < best) { best = d; nearest = pt; }
      }
      const x = X(nearest.t), y = Y(nearest.p);
      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = '#5aa9ff';
      ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, padT + ih); ctx.stroke();
      ctx.setLineDash([]);
      ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2); ctx.fillStyle = '#5aa9ff'; ctx.fill();
      const how = nearest.source === 'poll' ? 'observed by this tab'
        : nearest.basis === 'quote_mid' ? 'candle: quoted midpoint (no trade)'
          : nearest.basis === 'previous_trade' ? 'candle: last trade before the period'
            : 'candle: last traded price';
      const text = `$${nearest.p.toFixed(4)}  ·  ${new Date(nearest.t).toLocaleString('en-US', { hour12: false })}  ·  ${how}`;
      ctx.font = '12px ui-monospace, Menlo, Consolas, monospace';
      const tw = ctx.measureText(text).width + 14;
      const bx = Math.min(Math.max(x - tw / 2, padL), W - padR - tw);
      const by = padT + 2;
      ctx.fillStyle = 'rgba(14, 21, 38, 0.92)';
      ctx.fillRect(bx, by, tw, 20);
      ctx.strokeStyle = '#5aa9ff'; ctx.strokeRect(bx, by, tw, 20);
      ctx.fillStyle = '#dfe6ff'; ctx.textBaseline = 'middle';
      ctx.fillText(text, bx + 7, by + 10);
    }

    /* resolution label, bottom-left */
    ctx.font = '10px ui-monospace, Menlo, Consolas, monospace';
    ctx.fillStyle = '#5d688f';
    ctx.textBaseline = 'bottom';
    ctx.fillText(this.resolutionLabel(), padL + 2, H - 2);
  }
}
