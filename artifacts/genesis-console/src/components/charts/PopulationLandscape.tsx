/**
 * PopulationLandscape — scatter plot of the entire GP population.
 * x = Sharpe ratio, y = Fitness, bubble radius = tree complexity.
 * Color tier: green (Sharpe > 1.5), amber (0.5–1.5), red (< 0.5).
 */
import React, { useState, useEffect } from 'react';
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid,
  Tooltip as RTooltip, ResponsiveContainer, Cell, ReferenceLine,
} from 'recharts';

export interface PopulationGenome {
  id: string;
  sharpe: number;
  fitness: number;
  complexity: number;
  generation: number;
}

// ── Synthetic ───────────────────────────────────────────────────────────────

function lcg(seed: number) {
  let s = seed >>> 0;
  return () => { s = Math.imul(s, 1664525) + 1013904223 >>> 0; return s / 0xffffffff; };
}

function randn(rand: () => number) {
  // Box-Muller
  const u = rand() || 1e-9, v = rand();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

export function generatePopulation(n = 100, generation = 0): PopulationGenome[] {
  const rand = lcg(42 + generation * 17);
  return Array.from({ length: n }, (_, i) => {
    const sharpe = 1.2 + randn(rand) * 0.9;
    const fitness = Math.max(0, Math.min(1, (sharpe > 0 ? sharpe * 0.38 : 0) + rand() * 0.25));
    const complexity = Math.floor(3 + rand() * 22);
    return { id: `g${generation}-${i}`, sharpe, fitness, complexity, generation };
  });
}

// ── Custom dot ──────────────────────────────────────────────────────────────

function colorFor(sharpe: number) {
  if (sharpe > 1.5) return '#00ff88';
  if (sharpe > 0.5) return '#ffaa00';
  return '#ff3366';
}

interface DotProps {
  cx?: number; cy?: number;
  payload?: PopulationGenome;
}

function GenomeDot({ cx = 0, cy = 0, payload }: DotProps) {
  if (!payload) return null;
  const r = Math.max(2, Math.min(9, payload.complexity / 3));
  const color = colorFor(payload.sharpe);
  return (
    <circle
      cx={cx} cy={cy} r={r}
      fill={color} fillOpacity={0.65}
      stroke={color} strokeWidth={0.5} strokeOpacity={0.9}
    />
  );
}

// ── Tooltip ─────────────────────────────────────────────────────────────────

function CustomTooltip({ active, payload }: { active?: boolean; payload?: { payload: PopulationGenome }[] }) {
  if (!active || !payload?.[0]) return null;
  const g = payload[0].payload;
  return (
    <div className="bg-[#111] border border-white/10 rounded px-3 py-2 font-mono text-[11px] shadow-xl">
      <p style={{ color: colorFor(g.sharpe) }} className="font-bold mb-1">{g.id}</p>
      <p className="text-muted-foreground">Sharpe <span className="text-white">{g.sharpe.toFixed(3)}</span></p>
      <p className="text-muted-foreground">Fitness <span className="text-white">{g.fitness.toFixed(4)}</span></p>
      <p className="text-muted-foreground">Complexity <span className="text-white">{g.complexity}</span></p>
    </div>
  );
}

// ── Component ────────────────────────────────────────────────────────────────

interface PopulationLandscapeProps {
  population?: PopulationGenome[];
  generation?: number;
  height?: number;
  live?: boolean;
}

export default function PopulationLandscape({
  population: propPop,
  generation = 0,
  height = 280,
  live = true,
}: PopulationLandscapeProps) {
  const [pop, setPop] = useState<PopulationGenome[]>(() => propPop ?? generatePopulation(100, generation));

  useEffect(() => { if (propPop) setPop(propPop); }, [propPop]);

  // Re-generate every 8s in live mode
  useEffect(() => {
    if (!live || propPop) return;
    let gen = generation;
    const id = setInterval(() => {
      gen++;
      setPop(generatePopulation(100, gen));
    }, 8000);
    return () => clearInterval(id);
  }, [live, propPop, generation]);

  const monoStyle = { fontFamily: 'var(--app-font-mono)', fontSize: 9 };

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ScatterChart margin={{ top: 10, right: 8, bottom: 0, left: -12 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
        <XAxis
          type="number" dataKey="sharpe"
          domain={[-2.5, 4]} name="Sharpe"
          tick={{ ...monoStyle, fill: 'hsl(var(--muted-foreground))' }}
          tickLine={false} axisLine={false}
          label={{ value: 'SHARPE', position: 'insideBottom', offset: -2, style: { ...monoStyle, fill: 'hsl(var(--muted-foreground))' } }}
        />
        <YAxis
          type="number" dataKey="fitness"
          domain={[0, 1.05]} name="Fitness"
          tick={{ ...monoStyle, fill: 'hsl(var(--muted-foreground))' }}
          tickLine={false} axisLine={false}
          tickFormatter={v => v.toFixed(1)}
        />
        {/* Zero-Sharpe divider */}
        <ReferenceLine x={0} stroke="rgba(255,255,255,0.12)" strokeDasharray="4 4" />
        {/* Elite zone marker */}
        <ReferenceLine x={1.5} stroke="#00ff88" strokeOpacity={0.2} strokeDasharray="2 6" />
        <RTooltip content={<CustomTooltip />} cursor={{ strokeDasharray: '3 3', stroke: 'rgba(255,255,255,0.1)' }} />
        <Scatter data={pop} shape={<GenomeDot />}>
          {pop.map(g => <Cell key={g.id} fill={colorFor(g.sharpe)} />)}
        </Scatter>
      </ScatterChart>
    </ResponsiveContainer>
  );
}
