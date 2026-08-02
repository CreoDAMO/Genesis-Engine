/**
 * RealitySurfacePanel — probability gauges per prediction market.
 * Each row shows: market label, probability bar, fair-value diamond,
 * divergence badge (+/- bps from consensus).
 */
import React, { useState, useEffect } from 'react';
import { cn } from '@/lib/utils';
import { motion, AnimatePresence } from 'framer-motion';

export interface MarketSurfacePoint {
  market: string;
  probability: number;    // 0 … 1
  confidence: number;     // 0 … 1
  divergence_bps: number; // +200 = we're 200bps above consensus
  venue_count: number;
  trend: 'up' | 'down' | 'flat';
}

// ── Synthetic ───────────────────────────────────────────────────────────────

const MARKETS = [
  'FED CUT NOV',
  'BTC > 100K EOY',
  'TRUMP WIN 2028',
  'US RECESSION Q1',
  'NVDA > $200',
  'DOGE ADOPT BILL',
];

function lcg(seed: number) {
  let s = seed >>> 0;
  return () => { s = Math.imul(s, 1664525) + 1013904223 >>> 0; return s / 0xffffffff; };
}

export function generateSurface(tick = 0): MarketSurfacePoint[] {
  const rand = lcg(99 + tick * 7);
  return MARKETS.map((market, i) => {
    const base = 0.15 + rand() * 0.7;
    const prob = Math.max(0.05, Math.min(0.95, base + Math.sin(tick * 0.05 + i) * 0.04));
    const div = (rand() - 0.5) * 400;
    const trends: MarketSurfacePoint['trend'][] = ['up', 'down', 'flat'];
    return {
      market,
      probability: prob,
      confidence: 0.55 + rand() * 0.4,
      divergence_bps: div,
      venue_count: 2 + Math.floor(rand() * 3),
      trend: trends[Math.floor(rand() * 3)],
    };
  });
}

// ── Sub-components ───────────────────────────────────────────────────────────

function TrendArrow({ trend }: { trend: MarketSurfacePoint['trend'] }) {
  if (trend === 'up') return <span style={{ color: '#00ff88' }}>↑</span>;
  if (trend === 'down') return <span style={{ color: '#ff3366' }}>↓</span>;
  return <span className="text-muted-foreground">→</span>;
}

function DivBadge({ bps }: { bps: number }) {
  const pos = bps > 0;
  const abs = Math.abs(bps);
  if (abs < 5) return <span className="text-muted-foreground font-mono text-[10px]">FLAT</span>;
  return (
    <span
      className="font-mono text-[10px] font-bold"
      style={{ color: pos ? '#00ff88' : '#ff3366' }}
    >
      {pos ? '+' : '-'}{abs.toFixed(0)} bps
    </span>
  );
}

function ProbBar({ prob, confidence }: { prob: number; confidence: number }) {
  const pct = (prob * 100).toFixed(1);
  const barColor = prob > 0.7 ? '#00ff88' : prob < 0.3 ? '#ff3366' : '#ffaa00';
  // Fair-value diamond position (50% line = center)
  const diamondX = prob * 100;

  return (
    <div className="relative w-full h-5 flex items-center">
      {/* Track */}
      <div className="absolute inset-0 bg-white/5 rounded-sm overflow-hidden">
        <motion.div
          className="h-full rounded-sm"
          style={{ background: barColor, opacity: 0.3 }}
          initial={false}
          animate={{ width: `${prob * 100}%` }}
          transition={{ duration: 0.6, ease: 'easeOut' }}
        />
        {/* Confidence overlay */}
        <div
          className="absolute top-0 h-full rounded-sm"
          style={{
            left: `${Math.max(0, prob * 100 - confidence * prob * 100 * 0.5)}%`,
            width: `${confidence * prob * 100 * 0.5}%`,
            background: barColor,
            opacity: 0.15,
          }}
        />
      </div>
      {/* 50% midline */}
      <div className="absolute top-0 bottom-0 w-px bg-white/20" style={{ left: '50%' }} />
      {/* Diamond fair-value marker */}
      <div
        className="absolute w-2 h-2 rotate-45 border"
        style={{
          left: `calc(${diamondX}% - 4px)`,
          borderColor: barColor,
          background: 'transparent',
        }}
      />
      {/* Percentage label */}
      <span
        className="absolute right-2 font-mono text-[11px] font-bold"
        style={{ color: barColor }}
      >
        {pct}%
      </span>
    </div>
  );
}

// ── Main component ───────────────────────────────────────────────────────────

interface RealitySurfacePanelProps {
  surface?: MarketSurfacePoint[];
  live?: boolean;
}

export default function RealitySurfacePanel({ surface: propSurface, live = true }: RealitySurfacePanelProps) {
  const [tick, setTick] = useState(0);
  const [surface, setSurface] = useState<MarketSurfacePoint[]>(() => propSurface ?? generateSurface(0));

  useEffect(() => { if (propSurface) setSurface(propSurface); }, [propSurface]);

  useEffect(() => {
    if (!live || propSurface) return;
    const id = setInterval(() => {
      setTick(t => {
        const next = t + 1;
        setSurface(generateSurface(next));
        return next;
      });
    }, 4000);
    return () => clearInterval(id);
  }, [live, propSurface]);

  return (
    <div className="space-y-2">
      {/* Header row */}
      <div className="grid font-mono text-[9px] text-muted-foreground uppercase tracking-widest px-1"
        style={{ gridTemplateColumns: '160px 1fr 90px 52px' }}>
        <span>Market</span>
        <span className="pl-2">Probability</span>
        <span className="text-right">Divergence</span>
        <span className="text-right">Venues</span>
      </div>

      <AnimatePresence mode="sync">
        {surface.map((pt) => (
          <motion.div
            key={pt.market}
            initial={{ opacity: 0, x: -4 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.3 }}
            className="grid items-center gap-2 px-1 py-1.5 rounded hover:bg-white/3 transition-colors"
            style={{ gridTemplateColumns: '160px 1fr 90px 52px' }}
          >
            {/* Market label */}
            <div className="flex items-center gap-1.5 font-mono text-[11px] text-foreground/80 truncate">
              <TrendArrow trend={pt.trend} />
              <span className="truncate">{pt.market}</span>
            </div>
            {/* Probability bar */}
            <ProbBar prob={pt.probability} confidence={pt.confidence} />
            {/* Divergence */}
            <div className="text-right">
              <DivBadge bps={pt.divergence_bps} />
            </div>
            {/* Venue count */}
            <div className="text-right font-mono text-[11px] text-muted-foreground">
              {pt.venue_count}
            </div>
          </motion.div>
        ))}
      </AnimatePresence>

      <div className="pt-1 border-t border-white/5 flex items-center justify-between px-1">
        <span className="font-mono text-[9px] text-muted-foreground uppercase">
          Tick {tick} · Reality Surface v6
        </span>
        <div className="flex items-center gap-3 font-mono text-[9px] text-muted-foreground">
          <span className="flex items-center gap-1"><span className="w-2 h-2 inline-block rotate-45 border" style={{ borderColor: '#00ff88' }} /> Fair value</span>
          <span>│ 50% midline</span>
        </div>
      </div>
    </div>
  );
}
