import React from 'react';
import { useSimulation } from '@/lib/store';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer } from 'recharts';
import { Activity, Flame, Cpu, GitBranch, Settings2, SlidersHorizontal } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Slider } from '@/components/ui/slider';
import { cn } from '@/lib/utils';

export default function Overview() {
  const { history, generation, isRunning, settings, updateSetting } = useSimulation();

  const currentData = history.length > 0 ? history[history.length - 1] : null;
  
  const metrics = [
    {
      title: "Peak Fitness",
      value: currentData ? currentData.maxFitness.toFixed(4) : "1.0000",
      icon: Activity,
      color: "text-primary",
      trend: "+0.12% vs last gen",
    },
    {
      title: "Fuel Burn Rate",
      value: currentData ? currentData.fuelUsed.toLocaleString() : "0",
      icon: Flame,
      color: "text-orange-500",
      trend: `Max capacity: ${settings.maxFuelPerEval}`,
    },
    {
      title: "Active Regime",
      value: currentData ? currentData.regime : "NONE",
      icon: Cpu,
      color: "text-blue-500",
      trend: "Simulated market env",
    },
    {
      title: "Tree Depth",
      value: currentData ? (currentData.bestExpression.match(/\n/g)?.length || 1).toString() : "0",
      icon: GitBranch,
      color: "text-emerald-500",
      trend: "Complexity indicator",
    }
  ];

  return (
    <div className="space-y-6 relative z-10">
      <div className="flex justify-between items-end">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-foreground">Evolution Overview</h2>
          <p className="text-muted-foreground mt-1">Monitoring live strategy generation and fitness convergence.</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {metrics.map((m, i) => (
          <Card key={i} className="bg-card/50 backdrop-blur border-border/50">
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                {m.title}
              </CardTitle>
              <m.icon className={cn("w-4 h-4", m.color)} />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-mono font-bold text-foreground">{m.value}</div>
              <p className="text-[10px] text-muted-foreground mt-1 uppercase">{m.trend}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="col-span-1 lg:col-span-2 bg-card/50 backdrop-blur border-border/50">
          <CardHeader>
            <CardTitle className="text-sm font-semibold uppercase tracking-wider flex items-center gap-2">
              <Activity className="w-4 h-4 text-primary" />
              Fitness Progression
            </CardTitle>
          </CardHeader>
          <CardContent>
            {history.length > 0 ? (
              <div className="h-[300px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={history} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                    <defs>
                      <linearGradient id="colorFitness" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="hsl(var(--primary))" stopOpacity={0.3}/>
                        <stop offset="95%" stopColor="hsl(var(--primary))" stopOpacity={0}/>
                      </linearGradient>
                      <linearGradient id="colorAvg" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="hsl(var(--muted-foreground))" stopOpacity={0.2}/>
                        <stop offset="95%" stopColor="hsl(var(--muted-foreground))" stopOpacity={0}/>
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                    <XAxis 
                      dataKey="generation" 
                      stroke="hsl(var(--muted-foreground))" 
                      fontSize={10}
                      tickFormatter={(val) => `Gen ${val}`}
                      fontFamily="var(--font-mono)"
                    />
                    <YAxis 
                      domain={['auto', 'auto']} 
                      stroke="hsl(var(--muted-foreground))" 
                      fontSize={10}
                      fontFamily="var(--font-mono)"
                      tickFormatter={(val) => val.toFixed(2)}
                    />
                    <RechartsTooltip 
                      contentStyle={{ backgroundColor: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: '4px', fontFamily: 'var(--font-mono)' }}
                      labelStyle={{ color: 'hsl(var(--muted-foreground))', marginBottom: '4px' }}
                      itemStyle={{ fontSize: '12px' }}
                    />
                    <Area 
                      type="monotone" 
                      dataKey="maxFitness" 
                      stroke="hsl(var(--primary))" 
                      fillOpacity={1} 
                      fill="url(#colorFitness)" 
                      strokeWidth={2}
                      name="Max Fitness"
                    />
                    <Area 
                      type="monotone" 
                      dataKey="avgFitness" 
                      stroke="hsl(var(--muted-foreground))" 
                      fillOpacity={1} 
                      fill="url(#colorAvg)" 
                      strokeWidth={1}
                      strokeDasharray="3 3"
                      name="Avg Fitness"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="h-[300px] w-full flex flex-col items-center justify-center text-muted-foreground border border-dashed border-border rounded-md bg-muted/20">
                <Activity className="w-8 h-8 mb-2 opacity-20" />
                <p className="text-sm">No data available. Start the evolution run.</p>
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="bg-card/50 backdrop-blur border-border/50">
          <CardHeader>
            <CardTitle className="text-sm font-semibold uppercase tracking-wider flex items-center gap-2">
              <Settings2 className="w-4 h-4 text-primary" />
              Engine Parameters
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <label className="text-xs font-semibold text-foreground uppercase">Mutation Rate</label>
                <span className="text-xs font-mono text-muted-foreground">{(settings.mutationRate * 100).toFixed(1)}%</span>
              </div>
              <Slider 
                value={[settings.mutationRate]} 
                min={0.01} 
                max={0.2} 
                step={0.01}
                onValueChange={([val]) => updateSetting('mutationRate', val)}
                className="my-2"
              />
              <p className="text-[10px] text-muted-foreground leading-tight">Controls the probability of random alterations in the expression tree during crossover.</p>
            </div>

            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <label className="text-xs font-semibold text-foreground uppercase">Population Size</label>
                <span className="text-xs font-mono text-muted-foreground">{settings.populationSize}</span>
              </div>
              <Slider 
                value={[settings.populationSize]} 
                min={100} 
                max={5000} 
                step={100}
                onValueChange={([val]) => updateSetting('populationSize', val)}
                className="my-2"
              />
              <p className="text-[10px] text-muted-foreground leading-tight">Number of candidate strategies evaluated per generation. Higher values require more VM fuel.</p>
            </div>

            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <label className="text-xs font-semibold text-foreground uppercase">Max Fuel Per Eval</label>
                <span className="text-xs font-mono text-muted-foreground">{settings.maxFuelPerEval}</span>
              </div>
              <Slider 
                value={[settings.maxFuelPerEval]} 
                min={1000} 
                max={10000} 
                step={500}
                onValueChange={([val]) => updateSetting('maxFuelPerEval', val)}
                className="my-2"
              />
              <p className="text-[10px] text-muted-foreground leading-tight">Hard ceiling on execution cycles per strategy to prevent infinite loops in generated code.</p>
            </div>
            
            <div className="pt-4 border-t border-border mt-6">
               <div className="flex items-center gap-2 p-3 bg-muted/50 rounded-md border border-border">
                 <SlidersHorizontal className="w-4 h-4 text-muted-foreground" />
                 <span className="text-xs text-muted-foreground">Parameters persist via localStorage</span>
               </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
