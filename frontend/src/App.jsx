import React, { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import BacktestPanel from "./components/BacktestPanel";
import EquityChart from "./components/EquityChart";

export default function App() {
  const [tab, setTab] = useState("overview");
  const [connected, setConnected] = useState(true);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState(null);
  const [portfolio, setPortfolio] = useState(null);
  const [positions, setPositions] = useState([]);
  const [trades, setTrades] = useState([]);
  const [signals, setSignals] = useState([]);
  const [equityCurve, setEquityCurve] = useState([]);
  const [history, setHistory] = useState([]);

  const refreshAll = useCallback(async () => {
    try {
      const [st, pf, pos, tr, sig, eq, hist] = await Promise.all([
        api.getStatus(),
        api.getPortfolio(),
        api.getPositions(),
        api.getTrades(50),
        api.getSignals(25),
        api.getEquityCurve(200),
        api.getBacktestHistory(10),
      ]);
      setStatus(st);
      setPortfolio(pf);
      setPositions(pos);
      setTrades(tr);
      setSignals(sig);
      setEquityCurve(eq);
      setHistory(hist);
      setConnected(true);
    } catch {
      setConnected(false);
    }
  }, []);

  useEffect(() => {
    refreshAll();
    const timer = setInterval(refreshAll, 10000);
    return () => clearInterval(timer);
  }, [refreshAll]);

  const handleAction = async (fn) => {
    setBusy(true);
    try {
      await fn();
      await refreshAll();
    } finally {
      setBusy(false);
    }
  };

  const equity = portfolio?.equity ?? status?.equity ?? 10000;
  const totalReturn = portfolio?.total_return_pct ?? 0;
  const drawdown = portfolio?.drawdown_pct ?? status?.drawdown_pct ?? 0;

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div>
            <h1>Binance Algorithmic Trading Bot</h1>
            <div className="brand-sub">
              {status
                ? `${status.exchange.toUpperCase()} ${status.market_type.toUpperCase()} • ${status.strategy} • ${status.timeframe} • ${status.symbols.join(", ")}`
                : "Connecting to FastAPI backend..."}
            </div>
          </div>
        </div>

        <div className="badges">
          <span className={`pill ${connected ? "green" : "red"}`}>
            {connected ? "API Online" : "API Offline"}
          </span>
          {status && (
            <>
              <span className={`pill ${status.mode === "live" ? "red" : "amber"}`}>
                Mode: {status.mode}
              </span>
              <span className={`pill ${status.is_running ? "green" : "blue"}`}>
                {status.is_running ? "Running" : "Idle"}
              </span>
            </>
          )}
        </div>

        <div className="controls">
          {!status?.is_running ? (
            <button
              className="btn-green"
              disabled={!connected || busy}
              onClick={() => handleAction(api.startBot)}
            >
              Start Bot
            </button>
          ) : (
            <button
              className="btn-red"
              disabled={!connected || busy}
              onClick={() => handleAction(api.stopBot)}
            >
              Stop Bot
            </button>
          )}
          <button
            className="btn-primary"
            disabled={!connected || busy}
            onClick={() => handleAction(api.runCycle)}
          >
            Run 1 Cycle
          </button>
          <button disabled={busy} onClick={refreshAll}>
            Refresh
          </button>
        </div>
      </header>

      {!connected && (
        <div className="banner warn">
          <span>
            Backend API is unreachable at <code>http://localhost:8000</code>. Start it with{" "}
            <code>uvicorn backend.api:app --reload</code> or <code>docker compose up --build</code>.
          </span>
        </div>
      )}

      {status?.is_halted && (
        <div className="banner danger">
          <span>
            <strong>RISK CIRCUIT BREAKER ACTIVE:</strong> {status.halt_reason}
          </span>
          <button className="btn-red" onClick={() => handleAction(api.resetHalt)}>
            Reset Risk Halt
          </button>
        </div>
      )}

      <div className="tabs">
        <button className={tab === "overview" ? "active" : ""} onClick={() => setTab("overview")}>
          Live Monitor
        </button>
        <button className={tab === "backtest" ? "active" : ""} onClick={() => setTab("backtest")}>
          Backtester
        </button>
        <button className={tab === "trades" ? "active" : ""} onClick={() => setTab("trades")}>
          Trade Ledger ({trades.length})
        </button>
      </div>

      {tab === "overview" && (
        <>
          <section className="kpi-grid">
            <div className="kpi-card">
              <div className="kpi-label">Total Equity</div>
              <div className="kpi-value">${equity.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
              <div className={`kpi-sub ${totalReturn >= 0 ? "pos" : "neg"}`}>
                {totalReturn >= 0 ? "+" : ""}
                {totalReturn}% vs initial
              </div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Realized / Unrealized</div>
              <div className={`kpi-value ${(portfolio?.realized_pnl ?? 0) >= 0 ? "pos" : "neg"}`}>
                ${(portfolio?.realized_pnl ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </div>
              <div className="kpi-sub">
                Unrealized: ${(portfolio?.unrealized_pnl ?? 0).toFixed(2)}
              </div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Win Rate</div>
              <div className="kpi-value">{portfolio?.win_rate_pct ?? 0}%</div>
              <div className="kpi-sub">Closed trades: {portfolio?.total_trades ?? 0}</div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Profit Factor</div>
              <div className="kpi-value">{portfolio?.profit_factor ?? 0}</div>
              <div className="kpi-sub">Fees paid: ${(portfolio?.total_fees_paid ?? 0).toFixed(2)}</div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Current Drawdown</div>
              <div className={`kpi-value ${drawdown > 5 ? "neg" : ""}`}>-{drawdown}%</div>
              <div className="kpi-sub">
                Limit: {((status?.max_drawdown_pct ?? 0.1) * 100).toFixed(0)}%
              </div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Open Positions</div>
              <div className="kpi-value">{positions.length}</div>
              <div className="kpi-sub">
                Cash: ${(portfolio?.cash ?? equity).toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </div>
            </div>
          </section>

          <div className="main-grid">
            <div className="card">
              <div className="card-header">
                <h2>Equity Curve</h2>
                <span className="pill blue">{equityCurve.length} snapshots</span>
              </div>
              <EquityChart data={equityCurve} />
            </div>

            <div className="card">
              <div className="card-header">
                <h2>Recent Strategy Signals</h2>
                <span className="pill blue">{signals.length}</span>
              </div>
              {signals.length === 0 ? (
                <div className="empty-state">No signals recorded yet. Click "Run 1 Cycle".</div>
              ) : (
                <div className="signal-list">
                  {signals.map((s) => (
                    <div className="signal-item" key={s.id}>
                      <div className="signal-top">
                        <strong>{s.symbol}</strong>
                        <span
                          className={`pill ${
                            s.action === "BUY" ? "green" : s.action === "SELL" ? "red" : "blue"
                          }`}
                        >
                          {s.action} ({Math.round(s.confidence * 100)}%)
                        </span>
                      </div>
                      <div style={{ color: "#9ca3af", fontSize: "0.78rem" }}>
                        ${s.price.toLocaleString()} • {s.reason}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="card">
            <div className="card-header">
              <h2>Active Positions</h2>
            </div>
            {positions.length === 0 ? (
              <div className="empty-state">No open positions right now.</div>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Symbol</th>
                      <th>Side</th>
                      <th>Qty</th>
                      <th>Entry</th>
                      <th>Current</th>
                      <th>Stop Loss</th>
                      <th>Take Profit</th>
                      <th>Unrealized PnL</th>
                    </tr>
                  </thead>
                  <tbody>
                    {positions.map((p) => (
                      <tr key={p.symbol}>
                        <td><strong>{p.symbol}</strong></td>
                        <td><span className={`pill ${p.side === "long" ? "green" : "red"}`}>{p.side}</span></td>
                        <td>{p.quantity}</td>
                        <td>${p.entry_price.toLocaleString()}</td>
                        <td>${p.current_price.toLocaleString()}</td>
                        <td className="neg">${p.stop_loss.toLocaleString()}</td>
                        <td className="pos">${p.take_profit.toLocaleString()}</td>
                        <td className={p.unrealized_pnl >= 0 ? "pos" : "neg"}>
                          ${p.unrealized_pnl >= 0 ? "+" : ""}
                          {p.unrealized_pnl.toFixed(2)} ({p.unrealized_pnl_pct}%)
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}

      {tab === "backtest" && (
        <>
          <BacktestPanel onBacktestComplete={refreshAll} />
          <div className="card">
            <div className="card-header">
              <h2>Saved Backtest Runs</h2>
            </div>
            {history.length === 0 ? (
              <div className="empty-state">No saved backtest runs yet.</div>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Symbol</th>
                      <th>TF</th>
                      <th>Strategy</th>
                      <th>Return</th>
                      <th>Sharpe</th>
                      <th>Max DD</th>
                      <th>Win Rate</th>
                      <th>PF</th>
                      <th>Trades</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((h) => (
                      <tr key={h.id}>
                        <td><strong>{h.symbol}</strong></td>
                        <td>{h.timeframe}</td>
                        <td>{h.strategy}</td>
                        <td className={h.total_return_pct >= 0 ? "pos" : "neg"}>
                          {h.total_return_pct >= 0 ? "+" : ""}
                          {h.total_return_pct}%
                        </td>
                        <td>{h.sharpe_ratio}</td>
                        <td className="neg">-{h.max_drawdown_pct}%</td>
                        <td>{h.win_rate_pct}%</td>
                        <td>{h.profit_factor}</td>
                        <td>{h.total_trades}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}

      {tab === "trades" && (
        <div className="card">
          <div className="card-header">
            <h2>Execution History</h2>
          </div>
          {trades.length === 0 ? (
            <div className="empty-state">No trades executed yet.</div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Symbol</th>
                    <th>Side</th>
                    <th>Action</th>
                    <th>Qty</th>
                    <th>Price</th>
                    <th>Fee</th>
                    <th>Realized PnL</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.map((t) => (
                    <tr key={t.order_id}>
                      <td>{new Date(t.timestamp).toLocaleString()}</td>
                      <td><strong>{t.symbol}</strong></td>
                      <td><span className={`pill ${t.side === "buy" ? "green" : "red"}`}>{t.side}</span></td>
                      <td>{t.action}</td>
                      <td>{t.quantity}</td>
                      <td>${t.price.toLocaleString()}</td>
                      <td>${t.fee.toFixed(4)}</td>
                      <td className={t.realized_pnl >= 0 ? "pos" : "neg"}>
                        {t.action === "exit"
                          ? `$${t.realized_pnl >= 0 ? "+" : ""}${t.realized_pnl.toFixed(2)} (${t.pnl_pct}%)`
                          : "—"}
                      </td>
                      <td style={{ color: "#9ca3af" }}>{t.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
