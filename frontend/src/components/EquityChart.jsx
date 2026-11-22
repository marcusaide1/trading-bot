import React, { useState } from "react";

export default function EquityChart({ data = [], height = 240 }) {
  const [hoverIdx, setHoverIdx] = useState(null);

  if (!data || data.length < 2) {
    return (
      <div className="empty-state">
        Run a trading cycle or backtest to populate the equity curve.
      </div>
    );
  }

  const width = 760;
  const padLeft = 64;
  const padRight = 18;
  const padTop = 18;
  const padBottom = 28;
  const innerW = width - padLeft - padRight;
  const innerH = height - padTop - padBottom;

  const values = data.map((d) => Number(d.equity));
  const minVal = Math.min(...values);
  const maxVal = Math.max(...values);
  const range = Math.max(maxVal - minVal, 1);

  const toX = (i) => padLeft + (i / (data.length - 1)) * innerW;
  const toY = (v) => padTop + innerH - ((v - minVal) / range) * innerH;

  const linePoints = values.map((v, i) => `${toX(i).toFixed(1)},${toY(v).toFixed(1)}`).join(" ");
  const areaPath = `M ${toX(0).toFixed(1)},${(padTop + innerH).toFixed(1)} L ${linePoints
    .split(" ")
    .join(" L ")} L ${toX(values.length - 1).toFixed(1)},${(padTop + innerH).toFixed(1)} Z`;

  const isUp = values[values.length - 1] >= values[0];
  const stroke = isUp ? "#22c55e" : "#ef4444";
  const fill = isUp ? "rgba(34, 197, 94, 0.16)" : "rgba(239, 68, 68, 0.16)";

  const gridTicks = [0, 0.25, 0.5, 0.75, 1].map((t) => minVal + range * t);
  const active = hoverIdx !== null ? data[hoverIdx] : null;

  return (
    <div className="chart-box">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        style={{ width: "100%", height: "auto", display: "block" }}
        onMouseLeave={() => setHoverIdx(null)}
        onMouseMove={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          const relX = ((e.clientX - rect.left) / rect.width) * width;
          const idx = Math.round(((relX - padLeft) / innerW) * (data.length - 1));
          setHoverIdx(Math.max(0, Math.min(data.length - 1, idx)));
        }}
      >
        {gridTicks.map((val, idx) => {
          const y = toY(val);
          return (
            <g key={idx}>
              <line
                x1={padLeft}
                y1={y}
                x2={width - padRight}
                y2={y}
                stroke="#1f2937"
                strokeDasharray="3 3"
              />
              <text x={padLeft - 8} y={y + 4} textAnchor="end" fill="#9ca3af" fontSize="11">
                ${val.toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </text>
            </g>
          );
        })}

        <path d={areaPath} fill={fill} />
        <polyline fill="none" stroke={stroke} strokeWidth="2.2" points={linePoints} />

        {active && (
          <g>
            <line
              x1={toX(hoverIdx)}
              y1={padTop}
              x2={toX(hoverIdx)}
              y2={padTop + innerH}
              stroke="#38bdf8"
              strokeDasharray="3 3"
            />
            <circle cx={toX(hoverIdx)} cy={toY(active.equity)} r="4.5" fill={stroke} />
          </g>
        )}
      </svg>

      {active && (
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            fontSize: "0.8rem",
            color: "#9ca3af",
            marginTop: 6,
          }}
        >
          <span>Time: {new Date(active.timestamp).toLocaleString()}</span>
          <span style={{ color: "#e5e7eb", fontWeight: 600 }}>
            Equity: ${Number(active.equity).toLocaleString(undefined, { minimumFractionDigits: 2 })}
          </span>
        </div>
      )}
    </div>
  );
}
