import React from 'react';
import { useSimulation } from '@/lib/store';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Waves, Activity, Target, Clock } from 'lucide-react';
import SkewHelix, { generateHelixTicks } from '@/components/charts/SkewHelix';
import RealitySurfacePanel from '@/components/charts/RealitySurfacePanel';

// ── Inventory gauge (semicircle needle) ──────────────────────────────────────

function InventoryGauge({ pct }: { pct: number }) {
  // pct: -100 to +100; 0 = neutral; + = net long (want to sell)
  const clamped = Math.max(-100, Math.min(100, pct));
  // Map -100…+100 → -90°…+90° (semicircle from left to right)
  const angle = (clamped / 100) * 90;
  const rad = ((angle - 90) * Math.PI) / 180; // rotate CCW from top
  const cx = 70, cy = 70, r = 50;
  const nx = cx + r * Math.cos(rad);
  const ny = cy + r * Math.sin(rad);
  const color = Math.abs(clamped) > 60
    ? 'var(--neon-amber)'
    : Math.abs(clamped) > 30
    ? 'var(--neon-cyan)'
    : 'var(--neon-green)';

  return (
    <div className="flex flex-col items-center">
      <svg width="140" height="82" viewBox="0 0 140 82">
        <defs>
          <linearGradient id="gaugeGrad" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#00ff88" stopOpacity={0.6} />
            <stop offset="50%" stopColor="#00d4ff" stopOpacity={0.4} />
            <stop offset="100%" stopColor="#ffaa00" stopOpacity={0.6} />
          </linearGradient>
        </defs>
        {/* Gauge arc */}
        <path d="M 20 70 A 50 50 0 0 1 120 70" fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth={8} strokeLinecap="round" />
        <path d="M 20 70 A 50 50 0 0 1 120 70" fill="none" stroke="url(#gaugeGrad)" strokeWidth={4} strokeLinecap="round" />
        {/* Tick marks */}
        {[-90, -60, -30, 0, 30, 60, 90].map((deg) => {
          const r2 = ((deg - 90) * Math.PI) / 180;
          const x1 = cx + 46 * Math.cos(r2), y1 = cy + 46 * Math.sin(r2);
          const x2 = cx + 54 * Math.cos(r2), y2 = cy + 54 * Math.sin(r2);
          return <line key={deg} x1={x1} y1={y1} x2={x2} y2={y2} stroke="rgba(255,255,255,0.2)" strokeWidth={1} />;
        })}
        {/* Needle */}
        <line x1={cx} y1={cy} x2={nx} y2={ny} stroke={color} strokeWidth={2} strokeLinecap="round" />
        <circle cx={cx} cy={cy} r={4} fill={color} />
        {/* Labels */}
        <text x="14" y="80" fontSize="9" fill="#00ff88" fontFamily="monospace" textAnchor="middle">LONG</text>
        <text x="126" y="80" fontSize="9" fill="#ffaa00" fontFamily="monospace" textAnchor="middle">SHORT</text>
      </svg>
      <span className="font-mono text-sm font-bold mt-1" style={{ color }}>
        {clamped > 0 ? '+' : ''}{clamped.toFixed(1)}%
      </span>
      <span className="font-mono text-[9px] text-muted-foreground uppercase mt-0.5">Net Inventory</span>
    </div>
  );
}

// ── Stat tile ─────────────────────────────────────────────────────────────────

interface MMStatProps { label: string; value: string; sub: string; color?: string; }
function MMStat({ label, value, sub, color = 'hsl(var(--foreground))' }: MMStatProps) {
  return (
    <div className="bg-card border border-white/6 rounded p-4 space-y-1">
      <p className="font-mono text-[9px] text-muted-foreground uppercase tracking-widest">{label}</p>
      <p className="font-mono font-bold text-xl tabular-nums leading-none" style={{ color }}>{value}</p>
      <p className="font-mono text-[9px] text-muted-foreground">{sub}</p>
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function MarketMaking() {
  const { omega } = useSimulation();

  const helixData = omega?.helix;
  const surfaceData = omega?.surface;

  // Pick last tick for stats
  const lastTick = helixData?.[helixData.length - 1] ?? generateHelixTicks(1, 99)[0];

  const stats: MMStatProps[] = [
    {
      label: 'Bid-Ask Spread',
      value: `${lastTick.spread_bps.toFixed(0)} bps`,
      sub: 'Dynamic gravity spread',
      color: '#ffaa00',
    },
    {
      label: 'Inventory Skew',
      value: `${lastTick.inventory_pct > 0 ? '+' : ''}${lastTick.inventory_pct.toFixed(1)}%`,
      sub: lastTick.inventory_pct > 30 ? 'Skewing asks up ↑' : lastTick.inventory_pct < -30 ? 'Skewing bids up ↑' : 'Near neutral',
      color: Math.abs(lastTick.inventory_pct) > 50 ? '#ff3366' : '#00ff88',
    },
    {
      label: 'Quote Mode',
      value: omega ? 'LIVE' : 'PAPER',
      sub: omega?.paper_trade !== false ? 'Simulated fills' : 'Live CLOB',
      color: omega?.paper_trade !== false ? '#00d4ff' : '#00ff88',
    },
    {
      label: 'Markets Quoted',
      value: `${surfaceData?.length ?? 6}`,
      sub: 'Reality Surface v6',
      color: 'hsl(var(--foreground))',
    },
  ];

  return (
    <div className="space-y-5 relative z-10">

      {/* Header */}
      <div>
        <h2 className="font-bold text-xl tracking-tight flex items-center gap-2 text-foreground">
          <Waves className="w-5 h-5 text-primary" />
          Market Making Terminal
        </h2>
        <p className="font-mono text-[11px] text-muted-foreground mt-1 uppercase tracking-wider">
          Gravity LP · Inventory-Skewed CLOB · Reality Surface Consensus
        </p>
      </div>

      {/* Stat row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {stats.map(s => <MMStat key={s.label} {...s} />)}
      </div>

      {/* Skew Helix */}
      <Card className="bg-card border-white/6">
        <CardHeader className="pb-0 pt-4 px-5">
          <div className="flex items-center justify-between">
            <CardTitle className="font-mono text-[10px] text-muted-foreground uppercase tracking-widest flex items-center gap-2">
              <Activity className="w-3.5 h-3.5 text-primary" />
              Bid / Ask Skew Helix
            </CardTitle>
            <span className="font-mono text-[9px] text-muted-foreground">
              ← scroll of last ~200 quotes →
            </span>
          </div>
        </CardHeader>
        <CardContent className="px-4 pb-6 pt-3">
          <SkewHelix ticks={helixData} height={240} live={!omega} />
        </CardContent>
      </Card>

      {/* Inventory + Reality Surface side-by-side */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        {/* Inventory gauge */}
        <Card className="bg-card border-white/6 flex flex-col items-center justify-center py-6">
          <CardHeader className="pb-2 pt-0 px-5 w-full">
            <CardTitle className="font-mono text-[10px] text-muted-foreground uppercase tracking-widest flex items-center gap-2">
              <Target className="w-3.5 h-3.5 text-primary" />
              Inventory
            </CardTitle>
          </CardHeader>
          <CardContent className="flex justify-center pb-4">
            <InventoryGauge pct={lastTick.inventory_pct} />
          </CardContent>
        </Card>

        {/* Reality Surface probability bars */}
        <Card className="lg:col-span-3 bg-card border-white/6">
          <CardHeader className="pb-2 pt-4 px-5">
            <CardTitle className="font-mono text-[10px] text-muted-foreground uppercase tracking-widest flex items-center gap-2">
              <Clock className="w-3.5 h-3.5 text-primary" />
              Reality Surface — Market Probabilities
            </CardTitle>
          </CardHeader>
          <CardContent className="px-5 pb-5">
            <RealitySurfacePanel surface={surfaceData} live={!omega} />
          </CardContent>
        </Card>
      </div>

    </div>
  );
}
