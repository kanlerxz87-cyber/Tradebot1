
// Minimal, dependency-free behaviour: active nav highlight + table sorting.
document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('table').forEach(function (table) {
    var headers = table.querySelectorAll('thead th');
    headers.forEach(function (th, index) {
      if (th.dataset.nosort !== undefined) return;
      th.style.cursor = 'pointer';
      th.title = 'Click to sort';
      var ascending = false;
      th.addEventListener('click', function () {
        var body = table.tBodies[0];
        var rows = Array.prototype.slice.call(body.rows);
        ascending = !ascending;
        rows.sort(function (a, b) {
          var av = (a.cells[index] || {}).textContent || '';
          var bv = (b.cells[index] || {}).textContent || '';
          var an = parseFloat(av.replace(/[^0-9.\-]/g, ''));
          var bn = parseFloat(bv.replace(/[^0-9.\-]/g, ''));
          if (!isNaN(an) && !isNaN(bn) && an !== bn) return ascending ? an - bn : bn - an;
          return ascending ? av.localeCompare(bv) : bv.localeCompare(av);
        });
        rows.forEach(function (r) { body.appendChild(r); });
      });
    });
  });
});
