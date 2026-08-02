import React from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { ShieldAlert, Cpu, AlertTriangle, ShieldCheck, Database, Zap } from 'lucide-react';

export default function Safety() {
  return (
    <div className="space-y-6 relative z-10">
      <div className="flex justify-between items-end">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <ShieldAlert className="w-6 h-6 text-primary" />
            Safety & Containment
          </h2>
          <p className="text-muted-foreground mt-1">Causal regime simulation boundaries and VM metered constraints.</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card className="col-span-1 md:col-span-2 bg-card/50 backdrop-blur border-border/50">
          <CardHeader>
            <CardTitle className="text-sm font-semibold uppercase tracking-wider flex items-center gap-2">
              <Database className="w-4 h-4 text-primary" />
              Causal Regime Context
            </CardTitle>
            <CardDescription>Simulated environments injected during evaluation</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="p-4 rounded-md border border-emerald-500/20 bg-emerald-500/5 relative overflow-hidden">
                <div className="absolute top-0 right-0 w-1 h-full bg-emerald-500/50"></div>
                <h4 className="font-bold text-sm text-emerald-600 dark:text-emerald-400 mb-1">BULL_REGIME</h4>
                <p className="text-xs text-muted-foreground font-mono">
                  Upward drift +0.02, Low Volatility (v=0.15), Positive skew.<br/>
                  Injects 10,000 synthetic ticks simulating 2020 Q3 conditions.
                </p>
              </div>
              <div className="p-4 rounded-md border border-destructive/20 bg-destructive/5 relative overflow-hidden">
                <div className="absolute top-0 right-0 w-1 h-full bg-destructive/50"></div>
                <h4 className="font-bold text-sm text-destructive mb-1">BEAR_REGIME</h4>
                <p className="text-xs text-muted-foreground font-mono">
                  Downward drift -0.03, High Volatility (v=0.45), Negative skew.<br/>
                  Injects 10,000 synthetic ticks simulating 2022 Q2 conditions.
                </p>
              </div>
              <div className="p-4 rounded-md border border-blue-500/20 bg-blue-500/5 relative overflow-hidden">
                <div className="absolute top-0 right-0 w-1 h-full bg-blue-500/50"></div>
                <h4 className="font-bold text-sm text-blue-600 dark:text-blue-400 mb-1">VOLATILE_REGIME</h4>
                <p className="text-xs text-muted-foreground font-mono">
                  Zero drift, Extreme Volatility (v=0.85), Fat tails.<br/>
                  Injects 10,000 synthetic ticks simulating Flash Crash conditions.
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        <div className="space-y-6">
          <Card className="bg-card/50 backdrop-blur border-border/50">
            <CardHeader>
              <CardTitle className="text-sm font-semibold uppercase tracking-wider flex items-center gap-2">
                <Cpu className="w-4 h-4 text-primary" />
                VM Metering
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-start gap-3">
                <ShieldCheck className="w-5 h-5 text-emerald-500 mt-0.5 shrink-0" />
                <div>
                  <h5 className="text-sm font-bold">Fuel Strict Mode</h5>
                  <p className="text-xs text-muted-foreground mt-0.5">Strategies that exceed fuel allocations are instantly terminated with fitness=0.</p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <ShieldCheck className="w-5 h-5 text-emerald-500 mt-0.5 shrink-0" />
                <div>
                  <h5 className="text-sm font-bold">No Network I/O</h5>
                  <p className="text-xs text-muted-foreground mt-0.5">The Bytecode VM is completely isolated from external network access.</p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <AlertTriangle className="w-5 h-5 text-orange-500 mt-0.5 shrink-0" />
                <div>
                  <h5 className="text-sm font-bold">State Persistence</h5>
                  <p className="text-xs text-muted-foreground mt-0.5">Genome evaluation is pure. No state can be retained between evaluation ticks.</p>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="bg-card/50 backdrop-blur border-border/50 border-dashed">
            <CardContent className="pt-6">
              <div className="flex flex-col items-center text-center space-y-2">
                <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center mb-2">
                  <Zap className="w-6 h-6 text-primary" />
                </div>
                <h4 className="font-bold text-sm uppercase tracking-wider">Trading Disabled</h4>
                <p className="text-xs text-muted-foreground px-4">
                  This console is restricted to quantitative research. Live market order execution is strictly disabled.
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
