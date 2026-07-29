(() => {
  const required = [
    ["fetch", typeof window.fetch === "function"],
    ["ReadableStream", typeof window.ReadableStream === "function"],
    ["AbortController", typeof window.AbortController === "function"],
    ["TextDecoder", typeof window.TextDecoder === "function"],
  ];
  const missing = required.filter(([, supported]) => !supported).map(([name]) => name);
  if (!missing.length) return;
  const warning = document.createElement("div");
  warning.className = "notice error browser-compat-warning";
  warning.setAttribute("role", "alert");
  warning.textContent = `当前浏览器版本过旧，缺少 ${missing.join("、")}。请使用公司批准的新版 Microsoft Edge 或 Google Chrome。`;
  const main = document.querySelector("main");
  if (main) main.prepend(warning);
})();
