import React, { createContext, useContext, useEffect, useState, useCallback, useRef } from 'react';

export interface GenerationData {
  generation: number;
  maxFitness: number;
  avgFitness: number;
  bestExpression: string;
  regime: 'BULL' | 'BEAR' | 'VOLATILE';
  fuelUsed: number;
}

export interface AuditLog {
  id: string;
  timestamp: string;
  action: string;
  details: string;
}

interface HallOfFameEntry {
  id: string;
  name: string;
  expression: string;
  outOfSampleSharpe: number;
  maxDrawdown: number;
  complexityScore: number;
  dateAdded: string;
}

interface SimulationSettings {
  mutationRate: number;
  populationSize: number;
  maxFuelPerEval: number;
  crossoverRate: number;
}

interface SimulationState {
  isRunning: boolean;
  generation: number;
  history: GenerationData[];
  auditTrail: AuditLog[];
  hallOfFame: HallOfFameEntry[];
  settings: SimulationSettings;
  toggleRun: () => void;
  updateSetting: (key: keyof SimulationSettings, value: number) => void;
  resetRun: () => void;
  addAudit: (action: string, details: string) => void;
  saveToHallOfFame: (entry: Omit<HallOfFameEntry, 'id' | 'dateAdded'>) => void;
}

const SimulationContext = createContext<SimulationState | null>(null);

const generateExpression = (depth: number = 3): string => {
  const ops = ['ADD', 'SUB', 'MUL', 'DIV', 'SIN', 'COS', 'MAX', 'MIN'];
  const terms = ['price', 'vol', 'ma_fast', 'ma_slow', 'rsi', 'macd', '0.5', '1.0', '-1.0'];
  
  if (depth <= 1 || Math.random() > 0.7) {
    return terms[Math.floor(Math.random() * terms.length)];
  }
  
  const op = ops[Math.floor(Math.random() * ops.length)];
  return `${op}(\n  ${generateExpression(depth - 1).split('\n').join('\n  ')},\n  ${generateExpression(depth - 1).split('\n').join('\n  ')}\n)`;
};

const DEFAULT_SETTINGS: SimulationSettings = {
  mutationRate: 0.05,
  populationSize: 1000,
  maxFuelPerEval: 5000,
  crossoverRate: 0.7,
};

const INITIAL_HOF: HallOfFameEntry[] = [
  {
    id: 'hof-1',
    name: 'Momentum Reversion Alpha',
    expression: 'IF(GT(rsi, 70), SUB(0, ma_fast), MUL(price, 1.2))',
    outOfSampleSharpe: 2.14,
    maxDrawdown: -12.4,
    complexityScore: 15,
    dateAdded: new Date(Date.now() - 86400000 * 2).toISOString(),
  },
  {
    id: 'hof-2',
    name: 'Vol-Adjusted Carry',
    expression: 'DIV(SUB(ma_fast, ma_slow), MAX(vol, 0.01))',
    outOfSampleSharpe: 1.85,
    maxDrawdown: -8.2,
    complexityScore: 9,
    dateAdded: new Date(Date.now() - 86400000 * 5).toISOString(),
  }
];

export function SimulationProvider({ children }: { children: React.ReactNode }) {
  const [isRunning, setIsRunning] = useState(false);
  const [generation, setGeneration] = useState(0);
  const [history, setHistory] = useState<GenerationData[]>([]);
  const [auditTrail, setAuditTrail] = useState<AuditLog[]>([]);
  const [hallOfFame, setHallOfFame] = useState<HallOfFameEntry[]>(INITIAL_HOF);
  const [settings, setSettings] = useState<SimulationSettings>(() => {
    try {
      const saved = localStorage.getItem('genesis-settings');
      return saved ? JSON.parse(saved) : DEFAULT_SETTINGS;
    } catch {
      return DEFAULT_SETTINGS;
    }
  });

  const lastFitness = useRef(1.0);

  const addAudit = useCallback((action: string, details: string) => {
    setAuditTrail(prev => [{
      id: Math.random().toString(36).substring(7),
      timestamp: new Date().toISOString(),
      action,
      details
    }, ...prev].slice(0, 100));
  }, []);

  useEffect(() => {
    localStorage.setItem('genesis-settings', JSON.stringify(settings));
  }, [settings]);

  const toggleRun = useCallback(() => {
    setIsRunning(prev => {
      const next = !prev;
      addAudit(next ? 'RUN_STARTED' : 'RUN_PAUSED', `Generation ${generation}`);
      return next;
    });
  }, [generation, addAudit]);

  const updateSetting = useCallback((key: keyof SimulationSettings, value: number) => {
    setSettings(prev => ({ ...prev, [key]: value }));
    addAudit('SETTING_CHANGED', `${key} updated to ${value}`);
  }, [addAudit]);

  const resetRun = useCallback(() => {
    setIsRunning(false);
    setGeneration(0);
    setHistory([]);
    lastFitness.current = 1.0;
    addAudit('RUN_RESET', 'Evolution environment cleared');
  }, [addAudit]);

  const saveToHallOfFame = useCallback((entry: Omit<HallOfFameEntry, 'id' | 'dateAdded'>) => {
    setHallOfFame(prev => [{
      ...entry,
      id: `hof-${Math.random().toString(36).substring(7)}`,
      dateAdded: new Date().toISOString(),
    }, ...prev]);
    addAudit('SAVED_TO_PORTFOLIO', `Strategy "${entry.name}" added to Hall of Fame`);
  }, [addAudit]);

  useEffect(() => {
    if (!isRunning) return;

    const timer = setInterval(() => {
      setGeneration(g => {
        const nextGen = g + 1;
        
        // Simulate fitness progression with diminishing returns and noise
        const improvement = Math.random() * 0.05 * (settings.mutationRate / 0.05);
        const noise = (Math.random() - 0.5) * 0.02;
        let nextMax = lastFitness.current + improvement + noise;
        
        // Occasional breakthrough
        if (Math.random() > 0.95) nextMax += 0.15;
        
        lastFitness.current = nextMax;
        
        const avg = nextMax * (0.6 + Math.random() * 0.2);
        
        const regimes: ('BULL' | 'BEAR' | 'VOLATILE')[] = ['BULL', 'BEAR', 'VOLATILE'];
        
        setHistory(prev => {
          const newData = {
            generation: nextGen,
            maxFitness: Number(nextMax.toFixed(4)),
            avgFitness: Number(avg.toFixed(4)),
            bestExpression: generateExpression(Math.floor(Math.random() * 3) + 2),
            regime: regimes[Math.floor(Math.random() * regimes.length)],
            fuelUsed: Math.floor(Math.random() * settings.maxFuelPerEval * 0.8 + settings.maxFuelPerEval * 0.2),
          };
          return [...prev, newData].slice(-100); // Keep last 100 generations in memory for chart
        });
        
        return nextGen;
      });
    }, 1000); // 1 tick per second

    return () => clearInterval(timer);
  }, [isRunning, settings]);

  return (
    <SimulationContext.Provider value={{
      isRunning,
      generation,
      history,
      auditTrail,
      hallOfFame,
      settings,
      toggleRun,
      updateSetting,
      resetRun,
      addAudit,
      saveToHallOfFame,
    }}>
      {children}
    </SimulationContext.Provider>
  );
}

export function useSimulation() {
  const context = useContext(SimulationContext);
  if (!context) throw new Error('useSimulation must be used within SimulationProvider');
  return context;
}
