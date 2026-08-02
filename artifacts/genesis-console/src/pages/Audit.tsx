import React from 'react';
import { useSimulation } from '@/lib/store';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { History, Shield, Lock } from 'lucide-react';
import { format } from 'date-fns';
import { cn } from '@/lib/utils';

export default function Audit() {
  const { auditTrail } = useSimulation();

  return (
    <div className="space-y-6 relative z-10">
      <div className="flex justify-between items-end">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <History className="w-6 h-6 text-primary" />
            Immutable Audit Trail
          </h2>
          <p className="text-muted-foreground mt-1">Cryptographically verifiable log of all console interactions and engine states.</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <Card className="col-span-1 md:col-span-3 bg-card/50 backdrop-blur border-border/50">
          <CardHeader className="border-b border-border bg-muted/20">
            <CardTitle className="text-sm font-semibold uppercase tracking-wider flex items-center gap-2">
              <Lock className="w-4 h-4 text-muted-foreground" />
              Event Log
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {auditTrail.length === 0 ? (
              <div className="p-8 text-center text-muted-foreground text-sm font-mono">
                No events recorded in current session.
              </div>
            ) : (
              <div className="divide-y divide-border/50 max-h-[600px] overflow-y-auto">
                {auditTrail.map((log) => (
                  <div key={log.id} className="p-4 flex gap-4 hover:bg-muted/10 transition-colors">
                    <div className="text-[10px] text-muted-foreground font-mono shrink-0 pt-0.5">
                      {format(new Date(log.timestamp), 'HH:mm:ss.SSS')}
                    </div>
                    <div className="flex-1 space-y-1">
                      <div className="flex items-center gap-2">
                        <span className={cn(
                          "text-xs font-bold font-mono px-1.5 py-0.5 rounded uppercase",
                          log.action.includes('STARTED') ? "bg-primary/20 text-primary" :
                          log.action.includes('PAUSED') ? "bg-orange-500/20 text-orange-500" :
                          log.action.includes('SAVED') ? "bg-emerald-500/20 text-emerald-500" :
                          "bg-muted text-muted-foreground"
                        )}>
                          {log.action}
                        </span>
                        <span className="text-[10px] text-muted-foreground font-mono uppercase">ID: {log.id}</span>
                      </div>
                      <p className="text-sm text-foreground/80">{log.details}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="col-span-1 bg-primary/5 border-primary/20 h-fit">
          <CardHeader>
            <CardTitle className="text-sm font-semibold uppercase tracking-wider flex items-center gap-2 text-primary">
              <Shield className="w-4 h-4" />
              Compliance
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-xs text-foreground/80 leading-relaxed">
              All interactions with the research console are recorded in local state for review. In a production environment, this trail would be cryptographically signed and stored in WORM storage.
            </p>
            <div className="text-[10px] text-muted-foreground space-y-1 font-mono uppercase bg-background/50 p-2 rounded border border-border/50">
              <p>State: SECURE</p>
              <p>Env: SANDBOX</p>
              <p>Integrity: VERIFIED</p>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
