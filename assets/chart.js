// A small dependency-free canvas chart.
//
// X axis is time and Y axis is the YES contract price in cents, which is what
// the brief asks for. Windows are seconds/minutes/hours, chosen by the reader.
// Nothing is drawn for a period with no observation: the line breaks instead of
// interpolating across a gap.

export const WINDOWS = [
  { id: '60s', label: '60s', ms: 60 * 1000, bucket: 5 * 1000 },
  { id: '5m', label: '5m', ms: 5 * 60 * 1000, bucket: 15 * 1000 },
  { id: '15m', label: '15m', ms: 15 * 60 * 1000, bucket: 30 * 1000 },
  { id: '1h', label: '1h', ms: 60 * 60 * 1000, bucket: 60 * 1000 },
  { id: '6h', label: '6h', ms: 6 * 60 * 60 * 1000, bucket: 5 * 60 * 1000 },
  { id: '24h', label: '24h', ms: 24 * 60 * 60 * 1000, bucket: 15 * 60 * 1000 },
];

const COLORS = {
  line: '#22c98a',
  fill: 'rgba(34, 201, 138, 0.13)',
  grid: 'rgba(140, 165, 190, 0.16)',
  axis: '#6f8299',
  markUp: '#2fbf71',
  markDown: '#ef5b5b',
  text: '#a7b8cb',
  bg: 'rgba(17, 24, 35, 0.6)',
};

export function drawChart(canvas, opts) {
  const {
    points = [], // [{ t: iso|ms, mid, bid, ask }]
    windowMs = WINDOWS[3].ms,
    now = Date.now(),
    alerts = [], // [{ observedAt, delta }]
    emptyMessage = 'No observations in this window yet.',
  } = opts ?? {};

  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || 700;
  const cssH = canvas.clientHeight || 300;
  canvas.width = Math.round(cssW * dpr);
  canvas.height = Math.round(cssH * dpr);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  const pad = { l: 46, r: 14, t: 14, b: 26 };
  const plotW = cssW - pad.l - pad.r;
  const plotH = cssH - pad.t - pad.b;
  const start = now - windowMs;

  const pts = points
    .map((p) => ({ t: typeof p.t === 'number' ? p.t : new Date(p.t).getTime(), mid: p.mid }))
    .filter((p) => Number.isFinite(p.t) && Number.isFinite(p.mid) && p.t >= start && p.t <= now)
    .sort((a, b) => a.t - b.t);

  // axes
  ctx.font = '11px ui-monospace, Menlo, monospace';
  ctx.textBaseline = 'middle';
  for (let i = 0; i <= 4; i += 1) {
    const priceCents = 100 - i * 25;
    const y = pad.t + (plotH * i) / 4;
    ctx.strokeStyle = COLORS.grid;
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(pad.l, y + 0.5); ctx.lineTo(pad.l + plotW, y + 0.5); ctx.stroke();
    ctx.fillStyle = COLORS.axis;
    ctx.textAlign = 'right';
    ctx.fillText(`${priceCents}¢`, pad.l - 8, y);
  }

  const ticks = 5;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  for (let i = 0; i <= ticks; i += 1) {
    const t = start + ((now - start) * i) / ticks;
    const x = pad.l + (plotW * i) / ticks;
    ctx.fillStyle = COLORS.axis;
    ctx.fillText(labelFor(t, windowMs), x, pad.t + plotH + 7);
  }

  if (pts.length < 2) {
    ctx.fillStyle = COLORS.axis;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.font = '12px -apple-system, Segoe UI, Roboto, sans-serif';
    ctx.fillText(emptyMessage, pad.l + plotW / 2, pad.t + plotH / 2);
    return { drawn: 0, windowMs };
  }

  const x = (t) => pad.l + ((t - start) / (now - start)) * plotW;
  const y = (p) => pad.t + plotH - Math.min(1, Math.max(0, p)) * plotH;

  // area + line, broken at gaps longer than 3x the median interval so an
  // absence of data never looks like a flat, confident price.
  const gaps = [];
  for (let i = 1; i < pts.length; i += 1) gaps.push(pts[i].t - pts[i - 1].t);
  const median = gaps.slice().sort((a, b) => a - b)[Math.floor(gaps.length / 2)] ?? 0;
  const breakAt = median > 0 ? Math.max(median * 3, 15000) : Infinity;

  ctx.beginPath();
  let started = false;
  let segmentStart = null;
  const segments = [];
  for (let i = 0; i < pts.length; i += 1) {
    const p = pts[i];
    const isBreak = i > 0 && pts[i].t - pts[i - 1].t > breakAt;
    if (!started || isBreak) {
      if (started) segments.push(segmentStart);
      ctx.moveTo(x(p.t), y(p.mid));
      started = true;
      segmentStart = i;
    } else {
      ctx.lineTo(x(p.t), y(p.mid));
    }
  }
  ctx.strokeStyle = COLORS.line;
  ctx.lineWidth = 2;
  ctx.lineJoin = 'round';
  ctx.stroke();

  // markers for alert times
  for (const a of alerts) {
    const t = new Date(a.observedAt).getTime();
    if (!(t >= start && t <= now)) continue;
    const px = x(t);
    ctx.strokeStyle = (a.delta ?? 0) >= 0 ? COLORS.markUp : COLORS.markDown;
    ctx.globalAlpha = 0.55;
    ctx.setLineDash([3, 3]);
    ctx.beginPath(); ctx.moveTo(px, pad.t); ctx.lineTo(px, pad.t + plotH); ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
  }

  // time label
  ctx.fillStyle = COLORS.text;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'top';
  ctx.font = '11px ui-monospace, Menlo, monospace';
  ctx.fillText(`${pts.length} observations · ${labelFor(start, windowMs)} → ${labelFor(now, windowMs)}`, pad.l, 0);

  return { drawn: pts.length, windowMs, from: start, to: now, segments: segments.length + 1 };
}

function labelFor(t, windowMs) {
  const d = new Date(t);
  if (windowMs <= 15 * 60 * 1000) return d.toISOString().slice(11, 19);
  if (windowMs <= 6 * 60 * 60 * 1000) return d.toISOString().slice(11, 16);
  return d.toISOString().slice(5, 16).replace('T', ' ');
}

/**
 * Bucket observations into fixed intervals of `bucket` ms, taking the last
 * observation in each bucket. Used for the "seconds / minutes / hours" switch.
 */
export function bucketSeries(points, windowMs, bucketMs, now = Date.now()) {
  const start = now - windowMs;
  const buckets = new Map();
  for (const p of points) {
    const t = typeof p.t === 'number' ? p.t : new Date(p.t).getTime();
    if (!Number.isFinite(t) || t < start || t > now) continue;
    const key = Math.floor((t - start) / bucketMs);
    const existing = buckets.get(key);
    if (!existing || t > existing.t) buckets.set(key, { ...p, t });
  }
  return [...buckets.entries()].sort((a, b) => a[0] - b[0]).map(([, v]) => v);
}
