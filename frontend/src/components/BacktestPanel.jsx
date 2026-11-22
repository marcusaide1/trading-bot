import React, { useState } from "react";
import { api } from "../api";
import EquityChart from "./EquityChart";

export default function BacktestPanel({ onBacktestComplete }) {
  const [form, setForm] = useState({
    symbol: "BTC/USDT",
    timeframe: "15m",
    strategy: "composite",
    bars: 500,
    initial_capital: 10000,
    stop_loss_pct: 2.0,
    take_profit_pct: 4.0,
    risk_per_trade_pct: 1.0,
    use_synthetic: false,
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const res = await api.runBacktest({
        symbol: form.symbol,
        timeframe: form.timeframe,
        strategy: form.strategy,
        bars: Number(form.bars),
        initial_capital: Number(form.initial_capital),
        stop_loss_pct: Number(form.stop_loss_pct) / 100,
        take_profit_pct: Number(form.take_profit_pct) / 100,
        risk_per_trade_pct: Number(form.risk_per_trade_pct) / 100,
        use_synthetic: form.use_synthetic,
      });
      setResult(res);
      if (onBacktestComplete) onBacktestComplete(res);
    } catch (err) {
      setError(err.message || "Backtest failed");
    } finally {
      setLoading(false);
    }
  };

  const m = result?.metrics;

  return (
    <div className="card">
      <div className="card-header">
        <h2>Strategy Backtester</h2>
        <span className="pill blue">Zero-Lookahead Bar Replay</span>
      </div>

      <form onSubmit={handleSubmit}>
        <div className="form-grid">
          <div className="field">
            <label>Symbol</label>
            <input
              value={form.symbol}
              onChange={(e) => setForm({ ...form, symbol: e.target.value })}
            />
          </div>
          <div className="field">
            <label>Timeframe</label>
            <select
              value={form.timeframe}
              onChange={(e) => setForm({ ...form, timeframe: e.target.value })}
            >
              <option value="5m">5m</option>
              <option value="15m">15m</option>
              <option value="1h">1h</option>
              <option value="4h">4h</option>
              <option value="1d">1d</option>
            </select>
          </div>
          <div className="field">
            <label>Strategy</label>
            <select
              value={form.strategy}
              onChange={(e) => setForm({ ...form, strategy: e.target.value })}
            >
              <option value="composite">Composite Ensemble</option>
              <option value="trend_following">Trend Following</option>
              <option value="moving_average">Moving Average Crossover</option>
            </select>
          </div>
          <div className="field">
            <label>Candles</label>
            <input
              type="number"
              min="150"
              max="2000"
              value={form.bars}
              onChange={(e) => setForm({ ...form, bars: e.target.value })}
            />
          </div>
          <div className="field">
            <label>Initial Capital ($)</label>
            <input
              type="number"
              min="500"
              step="500"
              value={form.initial_capital}
              onChange={(e) => setForm({ ...form, initial_capital: e.target.value })}
            />
          </div>
          <div className="field">
            <label>Risk / Trade (%)</label>
            <input
              type="number"
              min="0.2"
              max="5"
              step="0.1"
              value={form.risk_per_trade_pct}
              onChange={(e) => setForm({ ...form, risk_per_trade_pct: e.target.value })}
            />
          </div>
          <div className="field">
            <label>Stop Loss (%)</label>
            <input
              type="number"
              min="0.5"
              max="15"
              step="0.5"
              value={form.stop_loss_pct}
              onChange={(e) => setForm({ ...form, stop_loss_pct: e.target.value })}
            />
          </div>
          <div className="field">
            <label>Take Profit (%)</label>
            <input
              type="number"
              min="1"
              max="40"
              step="0.5"
              value={form.take_profit_pct}
              onChange={(e) => setForm({ ...form, take_profit_pct: e.target.value })}
            />
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "0.84rem", color: "#9ca3af" }}>
            <input
              type="checkbox"
              checked={form.use_synthetic}
              onChange={(e) => setForm({ ...form, use_synthetic: e.target.checked })}
            />
            Use offline synthetic market data (skip Binance API fetch)
          </label>
          <button type="submit" className="btn-primary" disabled={loading}>
            {loading ? "Running Simulation..." : "Run Backtest"}
          </button>
        </div>
      </form>

      {error && (
        <div className="banner danger" style={{ marginTop: 14 }}>
          {error}
        </div>
      )}

      {m && (
        <div style={{ marginTop: 20 }}>
          <div className="kpi-grid">
            <div className="kpi-card">
              <div className="kpi-label">Final Equity</div>
              <div className={`kpi-value ${m.total_return_pct >= 0 ? "pos" : "neg"}`}>
                ${m.final_equity.toLocaleString()}
              </div>
              <div className="kpi-sub">
                Return: {m.total_return_pct >= 0 ? "+" : ""}
                {m.total_return_pct}%
              </div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Sharpe / Sortino</div>
              <div className="kpi-value">{m.sharpe_ratio}</div>
              <div className="kpi-sub">Sortino: {m.sortino_ratio}</div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Max Drawdown</div>
              <div className="kpi-value neg">-{m.max_drawdown_pct}%</div>
              <div className="kpi-sub">Calmar: {m.calmar_ratio}</div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Win Rate / PF</div>
              <div className="kpi-value">{m.win_rate_pct}%</div>
              <div className="kpi-sub">
                PF: {m.profit_factor} ({m.total_trades} trades)
              </div>
            </div>
          </div>

          <EquityChart data={result.equity_curve} height={240} />
        </div>
      )}
    </div>
  );
}
