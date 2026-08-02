/**
 * SkewHelix — sinusoidal bid/ask visualization driven by GravityMarketMaker state.
 *
 * Two smooth cubic-spline curves (bid above center, ask below) whose amplitude
 * tracks spread_bps and whose relative phase-shift tracks inventory skew.
 * The filled region between them is the live spread.
 */
import React, { useRef, useEffect, useState, useCallback } from 'react';
import { cn } from '@/lib/utils';

export interface GravityTick {
  t: number;          // tick index (monotonically increasing)
  bid_skew: number;   // -1 … +1 (positive = bid above fair)
  ask_skew: number;   // -1 … +1 (positive = ask above fair)
  spread_bps: number; // 5 … 80
  inventory_pct: number; // -100 … +100
}

// ── Synthetic live data generator ──────────────────────────────────────────

function lcg(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = Math.imul(s, 1664525) + 1013904223 >>> 0;
    return s / 0xffffffff;
  };
}

export function generateHelixTicks(n = 90, seedOffset = 0): GravityTick[] {
  const rand = lcg(42 + seedOffset);
  const ticks: GravityTick[] = [];
  let inv = 0;
  let phase = 0;
  for (let i = 0; i < n; i++) {
    // inventory drifts like a mean-reverting random walk
    inv = inv * 0.97 + (rand() - 0.5) * 8;
    inv = Math.max(-80, Math.min(80, inv));
    phase += 0.12 + (rand() - 0.5) * 0.02;
    const spread = 15 + 20 * Math.abs(Math.sin(phase * 0.3)) + rand() * 10;
    const skew = inv / 100;
    ticks.push({
      t: i,
      bid_skew: Math.sin(phase + skew * Math.PI) * (0.7 + rand() * 0.3),
      ask_skew: -Math.sin(phase - skew * Math.PI) * (0.7 + rand() * 0.3),
      spread_bps: spread,
      inventory_pct: inv,
    });
  }
  return ticks;
}

// ── Smooth path helpers ─────────────────────────────────────────────────────

type Point = { x: number; y: number };

function smoothPath(pts: Point[]): string {
  if (pts.length < 2) return '';
  let d = `M ${pts[0].x.toFixed(1)},${pts[0].y.toFixed(1)}`;
  for (let i = 1; i < pts.length; i++) {
    const prev = pts[i - 1];
    const curr = pts[i];
    const next = pts[i + 1] ?? curr;
    const pprev = pts[i - 2] ?? prev;
    const cp1x = prev.x + (curr.x - pprev.x) / 6;
    const cp1y = prev.y + (curr.y - pprev.y) / 6;
    const cp2x = curr.x - (next.x - prev.x) / 6;
    const cp2y = curr.y - (next.y - prev.y) / 6;
    d += ` C ${cp1x.toFixed(1)},${cp1y.toFixed(1)} ${cp2x.toFixed(1)},${cp2y.toFixed(1)} ${curr.x.toFixed(1)},${curr.y.toFixed(1)}`;
  }
  return d;
}

// ── Component ───────────────────────────────────────────────────────────────

interface SkewHelixProps {
  ticks?: GravityTick[];
  height?: number;
  className?: string;
  live?: boolean; // auto-advance synthetic data
}

export default function SkewHelix({ ticks: propTicks, height = 220, className, live = true }: SkewHelixProps) {
  const [ticks, setTicks] = useState<GravityTick[]>(() => propTicks ?? generateHelixTicks(90, 0));
  const tickRef = useRef(0);
  const synthRef = useRef(generateHelixTicks(300, 0));

  // Advance by one tick every 2.5s when live and no external data
  useEffect(() => {
    if (!live || propTicks) return;
    const id = setInterval(() => {
      tickRef.current++;
      const offset = tickRef.current;
      setTicks(prev => {
        const next = synthRef.current[offset % synthRef.current.length];
        if (!next) return prev;
        const updated = [...prev.slice(1), { ...next, t: prev[prev.length - 1].t + 1 }];
        return updated;
      });
    }, 2500);
    return () => clearInterval(id);
  }, [live, propTicks]);

  // Sync prop changes
  useEffect(() => { if (propTicks) setTicks(propTicks); }, [propTicks]);

  const svgRef = useRef<SVGSVGElement>(null);
  const [svgW, setSvgW] = useState(800);

  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const ro = new ResizeObserver(entries => setSvgW(entries[0].contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const H = height;
  const centerY = H / 2;
  const ampScale = (H * 0.38) / 50; // 50 bps → 38% of half-height

  const bidPts: Point[] = ticks.map((tk, i) => ({
    x: (i / (ticks.length - 1)) * svgW,
    y: centerY - tk.spread_bps * ampScale * tk.bid_skew,
  }));
  const askPts: Point[] = ticks.map((tk, i) => ({
    x: (i / (ticks.length - 1)) * svgW,
    y: centerY - tk.spread_bps * ampScale * tk.ask_skew,
  }));

  const bidPath = smoothPath(bidPts);
  const askPath = smoothPath(askPts);

  // Closed fill region: bid forward, ask reversed
  const fillPath = bidPath + ' ' +
    [...askPts].reverse().map((p, i) => (i === 0 ? `L ${p.x.toFixed(1)},${p.y.toFixed(1)}` : `L ${p.x.toFixed(1)},${p.y.toFixed(1)}`)).join(' ') +
    ' Z';

  // Inventory needle (current last tick)
  const lastTick = ticks[ticks.length - 1];
  const invFrac = (lastTick?.inventory_pct ?? 0) / 100; // -1 … +1
  const needleX = svgW - 1;
  const needleY = centerY + invFrac * (H * 0.35);

  return (
    <div className={cn('relative select-none', className)}>
      <svg
        ref={svgRef}
        width="100%"
        height={H}
        className="overflow-visible"
        style={{ display: 'block' }}
      >
        <defs>
          <linearGradient id="helixFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#ffaa00" stopOpacity={0.18} />
            <stop offset="50%" stopColor="#00ff88" stopOpacity={0.10} />
            <stop offset="100%" stopColor="#ffaa00" stopOpacity={0.18} />
          </linearGradient>
          <filter id="helixGlow">
            <feGaussianBlur stdDeviation="1.5" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          {/* Fade mask: first 5% and last 2% transparent */}
          <linearGradient id="fadeMask" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="white" stopOpacity={0} />
            <stop offset="6%" stopColor="white" stopOpacity={1} />
            <stop offset="96%" stopColor="white" stopOpacity={1} />
            <stop offset="100%" stopColor="white" stopOpacity={0.4} />
          </linearGradient>
          <mask id="edgeFade">
            <rect x={0} y={0} width={svgW} height={H} fill="url(#fadeMask)" />
          </mask>
        </defs>

        {/* Grid lines */}
        {[-2, -1, 0, 1, 2].map(i => (
          <line
            key={i}
            x1={0} y1={centerY + i * H * 0.18}
            x2={svgW} y2={centerY + i * H * 0.18}
            stroke="#ffffff" strokeOpacity={0.04} strokeWidth={1}
          />
        ))}

        {/* Center axis */}
        <line x1={0} y1={centerY} x2={svgW} y2={centerY}
          stroke="#ffffff" strokeOpacity={0.08} strokeWidth={1} strokeDasharray="4 6" />

        <g mask="url(#edgeFade)">
          {/* Spread fill */}
          <path d={fillPath} fill="url(#helixFill)" />

          {/* Ask curve — neon green */}
          <path
            d={askPath}
            fill="none"
            style={{ stroke: '#00ff88' }}
            strokeWidth={1.5}
            strokeOpacity={0.85}
            filter="url(#helixGlow)"
          />

          {/* Bid curve — amber */}
          <path
            d={bidPath}
            fill="none"
            style={{ stroke: '#ffaa00' }}
            strokeWidth={1.5}
            strokeOpacity={0.85}
            filter="url(#helixGlow)"
          />
        </g>

        {/* "Now" vertical marker */}
        <line
          x1={needleX} y1={0} x2={needleX} y2={H}
          stroke="#ffffff" strokeOpacity={0.15} strokeWidth={1}
          strokeDasharray="2 4"
        />

        {/* Inventory position dot */}
        <circle cx={needleX} cy={needleY} r={4}
          fill={invFrac > 0.1 ? '#ffaa00' : invFrac < -0.1 ? '#00ff88' : '#ffffff'}
          opacity={0.9}
          filter="url(#helixGlow)"
        />
        <circle cx={needleX} cy={needleY} r={8}
          fill="none"
          stroke={invFrac > 0.1 ? '#ffaa00' : invFrac < -0.1 ? '#00ff88' : '#ffffff'}
          strokeWidth={1}
          strokeOpacity={0.3}
        />
      </svg>

      {/* Legend */}
      <div className="absolute bottom-2 left-3 flex items-center gap-4 font-mono text-[10px]">
        <span className="flex items-center gap-1.5">
          <span className="w-4 h-0.5 inline-block" style={{ background: '#ffaa00' }} />
          BID
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-4 h-0.5 inline-block" style={{ background: '#00ff88' }} />
          ASK
        </span>
        <span className="text-muted-foreground">
          SPREAD {lastTick?.spread_bps?.toFixed(0) ?? '--'} bps
        </span>
        <span className={cn(
          'font-bold',
          Math.abs(lastTick?.inventory_pct ?? 0) > 50 ? 'text-orange-400' : 'text-muted-foreground'
        )}>
          INV {lastTick?.inventory_pct?.toFixed(0) ?? '--'}%
        </span>
      </div>
    </div>
  );
}
