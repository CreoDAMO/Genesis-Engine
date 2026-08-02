import React from 'react';
import { useSimulation } from '@/lib/store';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Trophy, Code, ArrowRight } from 'lucide-react';
import { format } from 'date-fns';

export default function Portfolio() {
  const { hallOfFame } = useSimulation();

  return (
    <div className="space-y-6 relative z-10">
      <div className="flex justify-between items-end">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <Trophy className="w-6 h-6 text-primary" />
            Hall of Fame Portfolio
          </h2>
          <p className="text-muted-foreground mt-1">Curated collection of high-fitness strategies preserved for out-of-sample testing.</p>
        </div>
      </div>

      <div className="space-y-4">
        {hallOfFame.length === 0 ? (
          <Card className="bg-card/50 backdrop-blur border-border/50 border-dashed">
            <CardContent className="flex flex-col items-center justify-center h-48 text-muted-foreground">
              <Trophy className="w-8 h-8 mb-4 opacity-20" />
              <p className="text-sm">No strategies saved yet.</p>
            </CardContent>
          </Card>
        ) : (
          hallOfFame.map((entry) => (
            <Card key={entry.id} className="bg-card/50 backdrop-blur border-border hover:border-primary/50 transition-colors group">
              <CardContent className="p-6">
                <div className="flex flex-col lg:flex-row justify-between gap-6">
                  
                  <div className="flex-1 space-y-4">
                    <div>
                      <div className="flex items-center gap-3 mb-1">
                        <h3 className="font-bold text-lg text-foreground group-hover:text-primary transition-colors">{entry.name}</h3>
                        <span className="text-[10px] font-mono text-muted-foreground uppercase border border-border px-2 py-0.5 rounded">
                          {format(new Date(entry.dateAdded), 'yyyy-MM-dd')}
                        </span>
                      </div>
                      <p className="text-xs text-muted-foreground font-mono">ID: {entry.id}</p>
                    </div>

                    <div className="bg-[#0F1115] p-4 rounded border border-border/50 relative">
                      <Code className="absolute top-3 right-3 w-4 h-4 text-muted-foreground/30" />
                      <pre className="text-xs font-mono text-emerald-400 whitespace-pre-wrap overflow-x-auto leading-relaxed">
                        {entry.expression}
                      </pre>
                    </div>
                  </div>

                  <div className="w-full lg:w-64 shrink-0 space-y-4 lg:border-l lg:border-border lg:pl-6 flex flex-col justify-center">
                    <div className="grid grid-cols-2 lg:grid-cols-1 gap-4">
                      <div>
                        <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">OOS Sharpe</p>
                        <p className="text-xl font-bold font-mono text-foreground">{entry.outOfSampleSharpe.toFixed(2)}</p>
                      </div>
                      <div>
                        <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">Max Drawdown</p>
                        <p className="text-xl font-bold font-mono text-destructive">{entry.maxDrawdown}%</p>
                      </div>
                      <div>
                        <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">Complexity</p>
                        <p className="text-xl font-bold font-mono text-foreground">{entry.complexityScore}</p>
                      </div>
                    </div>
                    
                    <button className="w-full mt-4 flex items-center justify-center gap-2 py-2 text-xs font-bold uppercase tracking-wider border border-border rounded hover:bg-primary hover:text-primary-foreground hover:border-primary transition-colors">
                      Export to CSV
                      <ArrowRight className="w-3 h-3" />
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
