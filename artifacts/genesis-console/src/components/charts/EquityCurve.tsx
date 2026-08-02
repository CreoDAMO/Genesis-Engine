/**
 * EquityCurve — P&L hero number + equity sparkline area chart.
 * The big green number at top drives the visual impact;
 * the area chart shows the cumulative return curve below it.
 */
import React, { useState, useEffect, useRef } from 'react';
import {
  AreaChart, Area, XAxis, YAxis, Tooltip as RTooltip,
  ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { cn } from '@/lib/utils';

export interface PnlPoint {
  t: number;    // tick / time index
  pnl: number;  // cumulative P&L in USD
}

// ── Synthetic live equity curve ─────────────────────────────────────────────

function lcg(seed: number) {
  let s = seed >>> 0;
  return () => { s = Math.imul(s, 1664525) + 1013904223 >>> 0; return s / 0xffffffff; };
}

export function generatePnlSeries(n = 200, seed = 42): PnlPoint[] {
  const rand = lcg(seed);
  let pnl = 0;
  return Array.from({ length: n }, (_, i) => {
    // Mean-reverting random walk with slight positive drift
    pnl += (rand() - 0.468) * 420 + 8;
    return { t: i, pnl: Math.round(pnl) };
  });
}

// ── Custom tooltip ───────────────────────────────────────────────────────────

function CustomTooltip({ active, payload }: { active?: boolean; payload?: { value: number }[] }) {
  if (!active || !payload?.[0]) return null;
  const v = payload[0].value;
  return (
    <div className="bg-[#111] border border-white/10 rounded px-3 py-2 font-mono text-[11px] shadow-xl">
      <span style={{ color: v >= 0 ? 'var(--neon-green)' : 'var(--neon-red)' }} className="font-bold">
        {v >= 0 ? '+' : ''}{v.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })}
      </span>
    </div>
  );
}

// ── Component ────────────────────────────────────────────────────────────────

interface EquityCurveProps {
  data?: PnlPoint[];
  sparklineHeight?: number;
  live?: boolean;
  className?: string;
}

export default function EquityCurve({ data: propData, sparklineHeight = 110, live = true, className }: EquityCurveProps) {
  const [series, setSeries] = useState<PnlPoint[]>(() => propData ?? generatePnlSeries(200));
  const seedRef = useRef(42);

  useEffect(() => { if (propData) setSeries(propData); }, [propData]);

  // Append one new point every 2s in live mode
  useEffect(() => {
    if (!live || propData) return;
    const id = setInterval(() => {
      setSeries(prev => {
        const last = prev[prev.length - 1];
        const rand = lcg(seedRef.current++);
        const next: PnlPoint = {
          t: last.t + 1,
          pnl: Math.round(last.pnl + (rand() - 0.468) * 420 + 8),
        };
        const updated = [...prev.slice(-200), next];
        return updated;
      });
    }, 2000);
    return () => clearInterval(id);
  }, [live, propData]);

  const currentPnl = series[series.length - 1]?.pnl ?? 0;
  const prevPnl = series[series.length - 6]?.pnl ?? 0;
  const delta = currentPnl - prevPnl;
  const isPositive = currentPnl >= 0;
  const pnlColor = isPositive ? '#00ff88' : '#ff3366';

  // Dynamic Y domain — ensure zero is visible
  const vals = series.map(p => p.pnl);
  const lo = Math.min(0, ...vals);
  const hi = Math.max(0, ...vals);
  const pad = (hi - lo) * 0.08;
  const domain: [number, number] = [lo - pad, hi + pad];

  const formatUsd = (v: number) =>
    `${v >= 0 ? '+' : ''}${v.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })}`;

  return (
    <div className={cn('flex flex-col gap-1', className)}>
      {/* Hero number */}
      <div className="flex items-baseline justify-between px-1">
        <span
          className="font-mono font-bold tabular-nums leading-none"
          style={{ fontSize: '2.6rem', color: pnlColor, textShadow: `0 0 24px ${pnlColor}44` }}
        >
          {formatUsd(currentPnl)}
        </span>
        <div className="text-right font-mono text-[11px]">
          <div className={cn('font-bold', delta >= 0 ? 'text-emerald-400' : 'text-red-400')}>
            {delta >= 0 ? '▲' : '▼'} {formatUsd(Math.abs(delta))}
          </div>
          <div className="text-muted-foreground text-[9px] uppercase mt-0.5">last 10s</div>
        </div>
      </div>

      {/* Sparkline */}
      <ResponsiveContainer width="100%" height={sparklineHeight}>
        <AreaChart data={series} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="pnlFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={pnlColor} stopOpacity={0.25} />
              <stop offset="100%" stopColor={pnlColor} stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis dataKey="t" hide />
          <YAxis domain={domain} hide />
          <ReferenceLine y={0} stroke="rgba(255,255,255,0.12)" strokeDasharray="3 5" />
          <RTooltip content={<CustomTooltip />} />
          <Area
            type="monotone"
            dataKey="pnl"
            stroke={pnlColor}
            strokeWidth={1.5}
            fill="url(#pnlFill)"
            dot={false}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
