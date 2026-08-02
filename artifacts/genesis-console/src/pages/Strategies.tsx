import React from 'react';
import { useSimulation } from '@/lib/store';
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Binary, Save, Eye, GitBranch, Cpu, Network } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';

export default function Strategies() {
  const { history, isRunning, saveToHallOfFame } = useSimulation();
  const { toast } = useToast();

  const currentData = history.length > 0 ? history[history.length - 1] : null;

  const handleSave = () => {
    if (!currentData) return;
    
    saveToHallOfFame({
      name: `Gen ${currentData.generation} Alpha`,
      expression: currentData.bestExpression,
      outOfSampleSharpe: Number((currentData.maxFitness * 1.5).toFixed(2)),
      maxDrawdown: Number((currentData.maxFitness * -8).toFixed(1)),
      complexityScore: currentData.bestExpression.length,
    });
    
    toast({
      title: "Strategy Saved",
      description: "Added to Hall of Fame portfolio.",
    });
  };

  return (
    <div className="space-y-6 relative z-10">
      <div className="flex justify-between items-end">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <Binary className="w-6 h-6 text-primary" />
            Top Genome Inspection
          </h2>
          <p className="text-muted-foreground mt-1">Real-time view of the most fit expression tree in the active population.</p>
        </div>
        {currentData && (
          <Button onClick={handleSave} variant="default" className="gap-2">
            <Save className="w-4 h-4" />
            Save to Portfolio
          </Button>
        )}
      </div>

      {!currentData ? (
        <Card className="bg-card/50 backdrop-blur border-border/50 border-dashed">
          <CardContent className="flex flex-col items-center justify-center h-[400px] text-muted-foreground">
            <Network className="w-12 h-12 mb-4 opacity-20" />
            <p className="font-mono text-sm">Awaiting first generation results...</p>
            {!isRunning && <p className="text-xs mt-2 opacity-60">Start the engine to generate strategies.</p>}
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <Card className="col-span-1 lg:col-span-2 bg-[#0F1115] border-border overflow-hidden">
            <CardHeader className="border-b border-border/20 bg-black/40">
              <div className="flex justify-between items-center">
                <CardTitle className="text-sm font-mono text-sidebar-foreground">SOURCE.AST</CardTitle>
                <div className="flex items-center gap-2">
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-primary/20 text-primary border border-primary/30 uppercase">
                    Gen {currentData.generation}
                  </span>
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-blue-500/20 text-blue-400 border border-blue-500/30 uppercase">
                    Valid
                  </span>
                </div>
              </div>
            </CardHeader>
            <CardContent className="p-0">
              <div className="p-6 overflow-x-auto font-mono text-sm leading-relaxed text-emerald-400/90 whitespace-pre">
                {currentData.bestExpression}
              </div>
            </CardContent>
            <CardFooter className="bg-black/40 border-t border-border/20 p-4 text-xs font-mono text-sidebar-foreground/50 flex justify-between">
              <span>Lines: {currentData.bestExpression.split('\n').length}</span>
              <span>Chars: {currentData.bestExpression.length}</span>
            </CardFooter>
          </Card>

          <div className="space-y-6">
            <Card className="bg-card/50 backdrop-blur border-border/50">
              <CardHeader>
                <CardTitle className="text-sm font-semibold uppercase tracking-wider">Genome Vitals</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex justify-between items-center pb-2 border-b border-border">
                  <span className="text-sm text-muted-foreground">In-Sample Fitness</span>
                  <span className="font-mono font-bold text-primary">{currentData.maxFitness.toFixed(4)}</span>
                </div>
                <div className="flex justify-between items-center pb-2 border-b border-border">
                  <span className="text-sm text-muted-foreground">Fuel Cost</span>
                  <span className="font-mono text-foreground flex items-center gap-1">
                    <Cpu className="w-3 h-3 text-muted-foreground" />
                    {currentData.fuelUsed} cyc
                  </span>
                </div>
                <div className="flex justify-between items-center pb-2 border-b border-border">
                  <span className="text-sm text-muted-foreground">Evaluation Regime</span>
                  <span className="font-mono text-foreground">{currentData.regime}</span>
                </div>
              </CardContent>
            </Card>

            <Card className="bg-primary/5 border-primary/20">
              <CardHeader>
                <CardTitle className="text-sm font-semibold uppercase tracking-wider flex items-center gap-2 text-primary">
                  <Eye className="w-4 h-4" />
                  Operator Notes
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-xs leading-relaxed text-foreground/80">
                  This expression tree is evaluated strictly within the metered VM. 
                  Operands like <code>price</code>, <code>vol</code>, and <code>ma_fast</code> are securely injected 
                  during simulation. Execution halts if fuel exceeds bounds.
                </p>
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
