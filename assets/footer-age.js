// Relative age for the "Newest observation" footer.
//
// The age used to be baked into the HTML at build time, which made it wrong from the
// moment the page was served and made `scripts/build-site.mjs --check` fail for any
// page older than 90 seconds. The absolute UTC stamp stays in the markup as the record;
// this only annotates it, in the visitor's own clock, every 30 seconds.
(() => {
  const nodes = document.querySelectorAll('[data-obs-iso]');
  if (!nodes.length) return;
  const render = () => {
    const now = Date.now();
    for (const node of nodes) {
      const ms = now - new Date(node.getAttribute('data-obs-iso')).getTime();
      const s = Math.max(0, Math.round(ms / 1000));
      const rel = s < 90 ? s + 's ago' : s < 5400 ? Math.round(s / 60) + 'm ago' : s < 172800 ? Math.round(s / 3600) + 'h ago' : Math.round(s / 86400) + 'd ago';
      const out = node.parentElement && node.parentElement.querySelector('[data-obs-rel]');
      if (out) out.textContent = '(' + rel + ')';
    }
  };
  render();
  setInterval(render, 30000);
})();
