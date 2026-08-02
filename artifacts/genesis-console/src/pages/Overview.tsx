import React from 'react';
import { useSimulation } from '@/lib/store';
import {
  ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid,
  Tooltip as RTooltip, ResponsiveContainer, Legend,
} from 'recharts';
import { Activity, Flame, Cpu, GitBranch, Settings2, SlidersHorizontal, TrendingUp } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Slider } from '@/components/ui/slider';
import { cn } from '@/lib/utils';
import EquityCurve from '@/components/charts/EquityCurve';
import PopulationLandscape from '@/components/charts/PopulationLandscape';

// ── Stat tile ────────────────────────────────────────────────────────────────

interface StatTileProps {
  label: string;
  value: string;
  sub: string;
  glow?: 'green' | 'amber' | 'red' | 'orange';
  icon: React.ElementType;
}

function StatTile({ label, value, sub, glow = 'orange', icon: Icon }: StatTileProps) {
  const glowMap: Record<string, string> = {
    green:  'hsl(var(--chart-1))',
    amber:  'hsl(var(--chart-2))',
    red:    'hsl(var(--chart-3))',
    orange: 'hsl(var(--primary))',
  };
  const col = glowMap[glow];
  return (
    <div className="bg-card border border-white/6 rounded p-4 flex flex-col gap-2 relative overflow-hidden">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10px] text-muted-foreground uppercase tracking-widest">{label}</span>
        <Icon className="w-3.5 h-3.5" style={{ color: col, opacity: 0.7 }} />
      </div>
      <div className="font-mono font-bold tabular-nums text-2xl leading-none" style={{ color: col, textShadow: `0 0 16px ${col}44` }}>
        {value}
      </div>
      <p className="font-mono text-[9px] text-muted-foreground uppercase">{sub}</p>
      {/* subtle corner glow */}
      <div className="pointer-events-none absolute -bottom-6 -right-6 w-20 h-20 rounded-full opacity-10"
        style={{ background: `radial-gradient(circle, ${col}, transparent 70%)` }} />
    </div>
  );
}

// ── Fitness chart tooltip ────────────────────────────────────────────────────

function FitnessTooltip({ active, payload, label }: { active?: boolean; payload?: { name: string; value: number; color: string }[]; label?: string | number }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-[#111] border border-white/10 rounded px-3 py-2 font-mono text-[11px] shadow-xl space-y-1">
      <p className="text-muted-foreground mb-1">Gen {label}</p>
      {payload.map((p) => (
        <p key={p.name} style={{ color: p.color }}>
          {p.name}: <span className="font-bold">{p.value?.toFixed(4)}</span>
        </p>
      ))}
    </div>
  );
}

// ── Main ─────────────────────────────────────────────────────────────────────

export default function Overview() {
  const { history, generation, settings, updateSetting, omega } = useSimulation();
  const cur = history.length > 0 ? history[history.length - 1] : null;

  // Augment history with estimated sharpe (best fitness * 2.5 rough estimate when engine doesn't provide it)
  const chartData = history.map(h => ({
    ...h,
    sharpe: h.maxFitness * 2.5,
  }));

  const monoStyle = { fontFamily: 'var(--app-font-mono)', fontSize: 9 };

  const tiles: StatTileProps[] = [
    {
      label: 'Peak Fitness',
      value: cur ? cur.maxFitness.toFixed(4) : '–',
      sub: cur ? `avg ${cur.avgFitness.toFixed(4)}` : 'no data',
      glow: 'green', icon: Activity,
    },
    {
      label: 'Best Sharpe',
      value: cur ? (cur.maxFitness * 2.5).toFixed(2) : '–',
      sub: 'est. from fitness',
      glow: 'amber', icon: TrendingUp,
    },
    {
      label: 'Fuel Burn',
      value: cur ? cur.fuelUsed.toLocaleString() : '0',
      sub: `cap ${settings.maxFuelPerEval.toLocaleString()}`,
      glow: 'orange', icon: Flame,
    },
    {
      label: 'Active Regime',
      value: cur ? cur.regime : 'NONE',
      sub: 'simulated market env',
      glow: cur?.regime === 'BULL' ? 'green' : cur?.regime === 'BEAR' ? 'red' : 'amber',
      icon: Cpu,
    },
  ];

  return (
    <div className="space-y-5 relative z-10">

      {/* ── Row 1: Equity hero + stat tiles ── */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        {/* P&L hero (spans 2 cols) */}
        <Card className="lg:col-span-2 bg-card border-white/6">
          <CardHeader className="pb-1 pt-4 px-5">
            <CardTitle className="font-mono text-[10px] text-muted-foreground uppercase tracking-widest flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full animate-pulse inline-block" style={{ background: '#00ff88' }} />
              Paper Trade P&L
            </CardTitle>
          </CardHeader>
          <CardContent className="px-5 pb-4">
            <EquityCurve
              data={omega?.pnl_series}
              sparklineHeight={100}
              live={!omega}
            />
          </CardContent>
        </Card>

        {/* 4 stat tiles */}
        <div className="lg:col-span-3 grid grid-cols-2 xl:grid-cols-4 gap-3">
          {tiles.map(t => <StatTile key={t.label} {...t} />)}
        </div>
      </div>

      {/* ── Row 2: Fitness chart + Population Landscape ── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

        {/* Fitness + Sharpe dual-axis */}
        <Card className="lg:col-span-2 bg-card border-white/6">
          <CardHeader className="pb-1 pt-4 px-5">
            <CardTitle className="font-mono text-[10px] text-muted-foreground uppercase tracking-widest flex items-center gap-2">
              <Activity className="w-3.5 h-3.5 text-primary" />
              Fitness Progression · Dual Axis
            </CardTitle>
          </CardHeader>
          <CardContent className="px-2 pb-4">
            {chartData.length > 0 ? (
              <ResponsiveContainer width="100%" height={260}>
                <ComposedChart data={chartData} margin={{ top: 8, right: 12, left: -10, bottom: 0 }}>
                  <defs>
                    <linearGradient id="fitFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#00ff88" stopOpacity={0.25} />
                      <stop offset="100%" stopColor="#00ff88" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="avgFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#ffaa00" stopOpacity={0.1} />
                      <stop offset="100%" stopColor="#ffaa00" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
                  <XAxis
                    dataKey="generation"
                    tick={{ ...monoStyle, fill: 'hsl(var(--muted-foreground))' }}
                    tickLine={false} axisLine={false}
                    tickFormatter={v => `G${v}`}
                  />
                  <YAxis
                    yAxisId="fitness"
                    domain={['auto', 'auto']}
                    tick={{ ...monoStyle, fill: 'hsl(var(--muted-foreground))' }}
                    tickLine={false} axisLine={false}
                    tickFormatter={v => v.toFixed(2)}
                    width={36}
                  />
                  <YAxis
                    yAxisId="sharpe"
                    orientation="right"
                    domain={['auto', 'auto']}
                    tick={{ ...monoStyle, fill: 'hsl(var(--muted-foreground))' }}
                    tickLine={false} axisLine={false}
                    tickFormatter={v => v.toFixed(1)}
                    width={32}
                  />
                  <RTooltip content={<FitnessTooltip />} />
                  <Area
                    yAxisId="fitness"
                    type="monotone"
                    dataKey="maxFitness"
                    name="Max Fitness"
                    stroke="#00ff88"
                    strokeWidth={1.5}
                    fill="url(#fitFill)"
                    dot={false}
                  />
                  <Area
                    yAxisId="fitness"
                    type="monotone"
                    dataKey="avgFitness"
                    name="Avg Fitness"
                    stroke="#ffaa00"
                    strokeWidth={1}
                    strokeDasharray="4 4"
                    fill="url(#avgFill)"
                    dot={false}
                  />
                  <Line
                    yAxisId="sharpe"
                    type="monotone"
                    dataKey="sharpe"
                    name="Best Sharpe"
                    stroke="#00d4ff"
                    strokeWidth={1}
                    dot={false}
                    strokeDasharray="2 4"
                  />
                  <Legend
                    wrapperStyle={{ ...monoStyle, fontSize: 9, paddingTop: 6 }}
                    iconType="plainline"
                  />
                </ComposedChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[260px] flex flex-col items-center justify-center text-muted-foreground border border-dashed border-white/8 rounded">
                <Activity className="w-7 h-7 mb-2 opacity-15" />
                <p className="font-mono text-xs">Start the evolution run to see data.</p>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Population Landscape */}
        <Card className="bg-card border-white/6">
          <CardHeader className="pb-1 pt-4 px-5">
            <CardTitle className="font-mono text-[10px] text-muted-foreground uppercase tracking-widest flex items-center gap-2">
              <GitBranch className="w-3.5 h-3.5 text-primary" />
              Population Landscape
            </CardTitle>
          </CardHeader>
          <CardContent className="px-2 pb-4">
            <PopulationLandscape
              population={omega?.population}
              generation={generation}
              height={260}
              live={!omega}
            />
            <div className="flex items-center justify-center gap-4 mt-2 font-mono text-[9px] text-muted-foreground">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full inline-block" style={{ background: '#00ff88' }} /> Sharpe &gt; 1.5</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full inline-block" style={{ background: '#ffaa00' }} /> 0.5–1.5</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full inline-block" style={{ background: '#ff3366' }} /> &lt; 0.5</span>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* ── Row 3: Engine parameters ── */}
      <Card className="bg-card border-white/6">
        <CardHeader className="pb-1 pt-4 px-5">
          <CardTitle className="font-mono text-[10px] text-muted-foreground uppercase tracking-widest flex items-center gap-2">
            <Settings2 className="w-3.5 h-3.5 text-primary" />
            Engine Parameters
          </CardTitle>
        </CardHeader>
        <CardContent className="px-5 pb-5">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {[
              { key: 'mutationRate' as const, label: 'Mutation Rate', fmt: (v: number) => `${(v * 100).toFixed(1)}%`, min: 0.01, max: 0.2, step: 0.01, desc: 'Probability of random tree alterations during crossover' },
              { key: 'populationSize' as const, label: 'Population Size', fmt: (v: number) => `${v}`, min: 100, max: 5000, step: 100, desc: 'Candidate strategies evaluated per generation' },
              { key: 'maxFuelPerEval' as const, label: 'Max Fuel / Eval', fmt: (v: number) => v.toLocaleString(), min: 1000, max: 10000, step: 500, desc: 'Execution cycle ceiling per strategy (WASM fuel)' },
            ].map(({ key, label, fmt, min, max, step, desc }) => (
              <div key={key} className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[10px] text-foreground uppercase tracking-wide">{label}</span>
                  <span className="font-mono text-[11px] text-primary font-bold">{fmt(settings[key])}</span>
                </div>
                <Slider
                  value={[settings[key]]}
                  min={min} max={max} step={step}
                  onValueChange={([val]) => updateSetting(key, val)}
                />
                <p className="font-mono text-[9px] text-muted-foreground">{desc}</p>
              </div>
            ))}
          </div>
          <div className="mt-4 pt-4 border-t border-white/5 flex items-center gap-2 text-muted-foreground">
            <SlidersHorizontal className="w-3 h-3" />
            <span className="font-mono text-[9px] uppercase">Settings persist via localStorage</span>
          </div>
        </CardContent>
      </Card>

    </div>
  );
}
