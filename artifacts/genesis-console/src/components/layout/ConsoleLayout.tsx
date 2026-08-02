import React from 'react';
import { Link, useLocation } from 'wouter';
import { useQuery } from '@tanstack/react-query';
import { 
  Activity, 
  Binary, 
  ShieldAlert, 
  Trophy, 
  History, 
  TerminalSquare, 
  Play, 
  Square,
  RefreshCw,
  Cpu,
  Waves,
} from 'lucide-react';
import { useSimulation } from '@/lib/store';
import { cn } from '@/lib/utils';

interface BtcResponse {
  data: {
    amount: string;
    currency: string;
  }
}

const fetchBtcPrice = async (): Promise<string> => {
  const res = await fetch('https://api.coinbase.com/v2/prices/BTC-USD/spot');
  if (!res.ok) throw new Error('Failed to fetch price');
  const json: BtcResponse = await res.json();
  return json.data.amount;
};

export function ConsoleLayout({ children }: { children: React.ReactNode }) {
  const [location] = useLocation();
  const { isRunning, toggleRun, generation, engineAvailable } = useSimulation();

  const { data: btcPrice, isLoading: isBtcLoading, refetch } = useQuery({
    queryKey: ['btc-price'],
    queryFn: fetchBtcPrice,
    refetchInterval: 30000, // Every 30s
  });

  const navItems = [
    { href: '/', label: 'Overview', icon: Activity },
    { href: '/strategies', label: 'Strategies', icon: Binary },
    { href: '/market-making', label: 'Market Making', icon: Waves },
    { href: '/safety', label: 'Safety VM', icon: ShieldAlert },
    { href: '/portfolio', label: 'Portfolio', icon: Trophy },
    { href: '/audit', label: 'Audit Trail', icon: History },
  ];

  return (
    <div className="flex h-screen w-full bg-background overflow-hidden selection:bg-primary/20 selection:text-primary">
      {/* Sidebar */}
      <aside className="w-64 bg-sidebar text-sidebar-foreground flex flex-col border-r border-sidebar-border relative z-10">
        <div className="p-6 flex items-center gap-3">
          <TerminalSquare className="w-6 h-6 text-primary" />
          <div>
            <h1 className="font-bold text-sm tracking-widest uppercase">Genesis</h1>
            <p className="text-[10px] text-sidebar-foreground/60 font-mono">Strategy Console v2.4</p>
          </div>
        </div>

        <nav className="flex-1 px-4 py-4 space-y-1">
          {navItems.map((item) => {
            const active = location === item.href;
            const Icon = item.icon;
            return (
              <Link 
                key={item.href} 
                href={item.href}
                className={cn(
                  "flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium transition-all duration-200",
                  active 
                    ? "bg-sidebar-accent text-sidebar-accent-foreground shadow-sm" 
                    : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
                )}
              >
                <Icon className={cn("w-4 h-4", active && "text-primary")} />
                {item.label}
              </Link>
            );
          })}
        </nav>

        {/* Status / Market Context Area in Sidebar */}
        <div className="p-4 border-t border-sidebar-border bg-sidebar/50">
          <div className="flex items-center justify-between mb-4">
            <span className="text-xs text-sidebar-foreground/60 uppercase tracking-wider font-semibold">Live Context</span>
            <button 
              onClick={() => refetch()} 
              disabled={isBtcLoading}
              className="text-sidebar-foreground/40 hover:text-primary transition-colors"
              title="Refresh Market Data"
            >
              <RefreshCw className={cn("w-3 h-3", isBtcLoading && "animate-spin")} />
            </button>
          </div>
          
          <div className="bg-black/20 rounded border border-sidebar-border p-3 font-mono text-sm">
            <div className="flex justify-between items-center text-xs text-sidebar-foreground/50 mb-1">
              <span>BTC-USD</span>
              <span>Coinbase</span>
            </div>
            <div className="text-sidebar-foreground flex items-baseline gap-1">
              <span className="text-lg">
                {isBtcLoading ? '---' : btcPrice ? `$${parseFloat(btcPrice).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}` : 'ERR'}
              </span>
            </div>
          </div>
          
          <div className="mt-4 pt-4 border-t border-sidebar-border/50">
            <p className="text-[10px] text-sidebar-foreground/40 text-center leading-relaxed">
              ACCOUNT ACCESS DISABLED<br/>
              READ-ONLY RESEARCH MODE
            </p>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col min-w-0 bg-background relative">
        {/* Top Header Bar */}
        <header className="h-14 border-b border-border flex items-center justify-between px-6 bg-card z-10">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 font-mono text-sm">
              <span className="text-muted-foreground">Gen:</span>
              <span className="font-bold w-12">{String(generation).padStart(4, '0')}</span>
            </div>
            
            <div className="h-4 w-px bg-border" />
            
            <div className="flex items-center gap-2 font-mono text-sm">
              <span className="text-muted-foreground">Status:</span>
              <div className="flex items-center gap-1.5">
                <span className={cn("w-2 h-2 rounded-full", isRunning ? "bg-primary animate-pulse" : "bg-muted-foreground")} />
                <span className={isRunning ? "text-primary font-bold" : "text-muted-foreground"}>
                  {isRunning ? 'EVOLVING' : 'HALTED'}
                </span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* Engine connectivity indicator */}
            <div className="flex items-center gap-1.5 font-mono text-xs">
              <Cpu className={cn("w-3.5 h-3.5", engineAvailable ? "text-emerald-500" : "text-muted-foreground/40")} />
              <span className={engineAvailable ? "text-emerald-500" : "text-muted-foreground/40"}>
                {engineAvailable ? 'ENGINE LIVE' : 'ENGINE OFFLINE'}
              </span>
            </div>

            <button
              onClick={toggleRun}
              className={cn(
                "flex items-center gap-2 px-4 py-1.5 rounded text-sm font-bold transition-all shadow-sm",
                isRunning 
                  ? "bg-secondary text-secondary-foreground hover:bg-secondary/80 border border-border" 
                  : "bg-primary text-primary-foreground hover:bg-primary/90"
              )}
            >
              {isRunning ? <Square className="w-4 h-4 fill-current" /> : <Play className="w-4 h-4 fill-current" />}
              {isRunning ? 'HALT RUN' : 'START RUN'}
            </button>
          </div>
        </header>

        {/* Page Content */}
        <div className="flex-1 overflow-auto p-6 scroll-smooth">
          <div className="max-w-6xl mx-auto space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-300">
            {children}
          </div>
        </div>
        
        {/* decorative grid background */}
        <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(to_right,#80808012_1px,transparent_1px),linear-gradient(to_bottom,#80808012_1px,transparent_1px)] bg-[size:24px_24px] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_0%,#000_70%,transparent_100%)] opacity-50 z-0"></div>
      </main>
    </div>
  );
}
