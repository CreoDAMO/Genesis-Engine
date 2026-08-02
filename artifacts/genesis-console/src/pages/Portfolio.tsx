import React from 'react';
import { useSimulation } from '@/lib/store';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Trophy, Code, ArrowRight, PieChart as PieIcon, BarChart2 } from 'lucide-react';
import { format } from 'date-fns';
import {
  PieChart, Pie, Cell, Tooltip as RTooltip, ResponsiveContainer, Legend,
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
} from 'recharts';

// ── Synthetic capital / trade data ────────────────────────────────────────────

const DEFAULT_CAPITAL = [
  { name: 'GP Elite α', value: 38 },
  { name: 'GP Elite β', value: 27 },
  { name: 'Gravity LP',  value: 20 },
  { name: 'Cash Buffer', value: 15 },
];

const DEFAULT_TRADES = [
  { outcome: 'YES Win', count: 142, pnl: 31240 },
  { outcome: 'NO Win',  count:  98, pnl: 18760 },
  { outcome: 'Scratch', count:  44, pnl: -1200 },
  { outcome: 'NO Loss', count:  31, pnl: -8840 },
  { outcome: 'YES Loss', count: 18, pnl: -5440 },
];

const PIE_COLORS = [
  'var(--neon-green)',
  'var(--neon-amber)',
  'var(--neon-cyan)',
  'rgba(255,255,255,0.2)',
];

const monoStyle = { fontFamily: 'var(--app-font-mono)', fontSize: 9 };

function PieTooltip({ active, payload }: { active?: boolean; payload?: { name: string; value: number }[] }) {
  if (!active || !payload?.[0]) return null;
  return (
    <div className="bg-[#111] border border-white/10 rounded px-3 py-2 font-mono text-[11px] shadow-xl">
      <p className="text-foreground font-bold">{payload[0].name}</p>
      <p className="text-muted-foreground">{payload[0].value}%</p>
    </div>
  );
}

function TradeTooltip({ active, payload, label }: { active?: boolean; payload?: { name: string; value: number }[]; label?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-[#111] border border-white/10 rounded px-3 py-2 font-mono text-[11px] shadow-xl space-y-1">
      <p className="text-foreground font-bold mb-1">{label}</p>
      {payload.map(p => (
        <p key={p.name} className={p.value >= 0 ? 'text-emerald-400' : 'text-red-400'}>
          {p.name}: {p.value >= 0 ? '+' : ''}${Math.abs(p.value).toLocaleString()}
        </p>
      ))}
    </div>
  );
}

function barFill(outcome: string) {
  if (outcome.includes('Win')) return 'var(--neon-green)';
  if (outcome.includes('Loss')) return 'var(--neon-red)';
  return 'rgba(255,255,255,0.25)';
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function Portfolio() {
  const { hallOfFame, omega } = useSimulation();

  const capitalData = omega?.capital_by_strategy?.length ? omega.capital_by_strategy : DEFAULT_CAPITAL;
  const tradesData  = omega?.trades_by_outcome?.length  ? omega.trades_by_outcome   : DEFAULT_TRADES;

  return (
    <div className="space-y-5 relative z-10">
      <div>
        <h2 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2">
          <Trophy className="w-5 h-5 text-primary" />
          Hall of Fame Portfolio
        </h2>
        <p className="font-mono text-[11px] text-muted-foreground mt-1 uppercase tracking-wider">
          Capital allocation · trade outcomes · curated strategy archive
        </p>
      </div>

      {/* ── Charts row ── */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">

        {/* Capital composition donut */}
        <Card className="lg:col-span-2 bg-card border-white/6">
          <CardHeader className="pb-1 pt-4 px-5">
            <CardTitle className="font-mono text-[10px] text-muted-foreground uppercase tracking-widest flex items-center gap-2">
              <PieIcon className="w-3.5 h-3.5 text-primary" />
              Capital Composition
            </CardTitle>
          </CardHeader>
          <CardContent className="px-2 pb-4">
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie
                  data={capitalData}
                  cx="50%"
                  cy="48%"
                  innerRadius={55}
                  outerRadius={85}
                  paddingAngle={3}
                  dataKey="value"
                  stroke="none"
                >
                  {capitalData.map((_, i) => (
                    <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} opacity={0.85} />
                  ))}
                </Pie>
                <RTooltip content={<PieTooltip />} />
                <Legend
                  iconType="circle"
                  iconSize={7}
                  wrapperStyle={{ ...monoStyle, fontSize: 10 }}
                />
              </PieChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* Trades by outcome */}
        <Card className="lg:col-span-3 bg-card border-white/6">
          <CardHeader className="pb-1 pt-4 px-5">
            <CardTitle className="font-mono text-[10px] text-muted-foreground uppercase tracking-widest flex items-center gap-2">
              <BarChart2 className="w-3.5 h-3.5 text-primary" />
              Trades by Outcome — P&L
            </CardTitle>
          </CardHeader>
          <CardContent className="px-2 pb-4">
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={tradesData} margin={{ top: 8, right: 8, left: -10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
                <XAxis
                  dataKey="outcome"
                  tick={{ ...monoStyle, fill: 'hsl(var(--muted-foreground))' }}
                  tickLine={false} axisLine={false}
                />
                <YAxis
                  tick={{ ...monoStyle, fill: 'hsl(var(--muted-foreground))' }}
                  tickLine={false} axisLine={false}
                  tickFormatter={v => `$${(v / 1000).toFixed(0)}k`}
                  width={44}
                />
                <RTooltip content={<TradeTooltip />} />
                <Bar dataKey="pnl" name="P&L" radius={[2, 2, 0, 0]}>
                  {tradesData.map((t, i) => (
                    <Cell key={i} fill={barFill(t.outcome)} opacity={0.8} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      {/* ── Hall of Fame list ── */}
      <div className="space-y-3">
        <h3 className="font-mono text-[10px] text-muted-foreground uppercase tracking-widest px-1">
          Curated Strategies
        </h3>

        {hallOfFame.length === 0 ? (
          <Card className="bg-card border-white/6 border-dashed">
            <CardContent className="flex flex-col items-center justify-center h-40 text-muted-foreground">
              <Trophy className="w-7 h-7 mb-3 opacity-15" />
              <p className="font-mono text-xs">No strategies saved yet. Run the evolution engine first.</p>
            </CardContent>
          </Card>
        ) : (
          hallOfFame.map((entry) => (
            <Card key={entry.id} className="bg-card border-white/6 hover:border-primary/40 transition-colors group">
              <CardContent className="p-5">
                <div className="flex flex-col lg:flex-row justify-between gap-5">
                  <div className="flex-1 space-y-3">
                    <div className="flex items-center gap-3">
                      <h3 className="font-bold text-base text-foreground group-hover:text-primary transition-colors">{entry.name}</h3>
                      <span className="font-mono text-[9px] text-muted-foreground uppercase border border-white/10 px-2 py-0.5 rounded">
                        {format(new Date(entry.dateAdded), 'yyyy-MM-dd')}
                      </span>
                    </div>
                    <div className="bg-[#080808] p-3 rounded border border-white/6 relative">
                      <Code className="absolute top-2.5 right-2.5 w-3 h-3 text-muted-foreground/20" />
                      <pre className="font-mono text-[11px] text-emerald-400 whitespace-pre-wrap overflow-x-auto leading-relaxed">
                        {entry.expression}
                      </pre>
                    </div>
                  </div>
                  <div className="w-full lg:w-56 shrink-0 space-y-3 lg:border-l lg:border-white/6 lg:pl-5 flex flex-col justify-center">
                    <div className="grid grid-cols-3 lg:grid-cols-1 gap-3">
                      {[
                        { label: 'OOS Sharpe', value: entry.outOfSampleSharpe.toFixed(2), color: 'var(--neon-green)' },
                        { label: 'Max Drawdown', value: `${entry.maxDrawdown}%`, color: 'var(--neon-red)' },
                        { label: 'Complexity', value: String(entry.complexityScore), color: 'hsl(var(--foreground))' },
                      ].map(m => (
                        <div key={m.label}>
                          <p className="font-mono text-[9px] text-muted-foreground uppercase tracking-wider mb-0.5">{m.label}</p>
                          <p className="font-mono font-bold text-lg tabular-nums" style={{ color: m.color }}>{m.value}</p>
                        </div>
                      ))}
                    </div>
                    <button className="w-full flex items-center justify-center gap-2 py-1.5 font-mono text-[10px] font-bold uppercase tracking-wider border border-white/10 rounded hover:bg-primary hover:text-primary-foreground hover:border-primary transition-colors">
                      Export CSV <ArrowRight className="w-3 h-3" />
                    </button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))
        )}
      </div>
    </div>
  );
}
