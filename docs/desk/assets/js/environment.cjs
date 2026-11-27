/* Strict environment allow-list shared by the GitHub Pages UI and Node tests. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.KalshiDemoEnvironment = api;
})(typeof globalThis === "undefined" ? this : globalThis, function () {
  "use strict";

  const BASES = Object.freeze([
    "https://external-api.demo.kalshi.co/trade-api/v2",
    "https://demo-api.kalshi.co/trade-api/v2",
  ]);
  const PRIMARY = BASES[0];

  function exactDemoBase(value) {
    if (typeof value !== "string") return null;
    const candidate = value.replace(/\/$/, "");
    return BASES.includes(candidate) ? candidate : null;
  }

  function isDemoSnapshot(snapshot) {
    return !!snapshot && snapshot.data_env === "demo" && exactDemoBase(snapshot.rest_base) !== null;
  }

  function restBase(override) {
    if (override === undefined || override === null || override === "") return PRIMARY;
    return exactDemoBase(override);
  }

  return Object.freeze({ BASES, PRIMARY, exactDemoBase, isDemoSnapshot, restBase });
});
