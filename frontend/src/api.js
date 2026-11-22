const API_BASE = import.meta.env.VITE_API_URL || "";

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json();
}

export const api = {
  health: () => request("/health"),
  getStatus: () => request("/api/bot/status"),
  startBot: () => request("/api/bot/start", { method: "POST" }),
  stopBot: () => request("/api/bot/stop", { method: "POST" }),
  runCycle: () => request("/api/bot/cycle", { method: "POST" }),
  resetHalt: () => request("/api/bot/reset-halt", { method: "POST" }),
  updateConfig: (body) =>
    request("/api/bot/config", { method: "PATCH", body: JSON.stringify(body) }),
  getPortfolio: () => request("/api/portfolio"),
  getPositions: () => request("/api/positions"),
  getTrades: (limit = 50) => request(`/api/trades?limit=${limit}`),
  getEquityCurve: (limit = 200) => request(`/api/equity-curve?limit=${limit}`),
  getSignals: (limit = 30) => request(`/api/signals?limit=${limit}`),
  runBacktest: (body) =>
    request("/api/backtest/run", { method: "POST", body: JSON.stringify(body) }),
  getBacktestHistory: (limit = 15) => request(`/api/backtest/history?limit=${limit}`),
};
