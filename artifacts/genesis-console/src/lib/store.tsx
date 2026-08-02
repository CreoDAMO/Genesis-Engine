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
  engineAvailable: boolean;
  toggleRun: () => void;
  updateSetting: (key: keyof SimulationSettings, value: number) => void;
  resetRun: () => void;
  addAudit: (action: string, details: string) => void;
  saveToHallOfFame: (entry: Omit<HallOfFameEntry, 'id' | 'dateAdded'>) => void;
}

const SimulationContext = createContext<SimulationState | null>(null);

// Base URL for genesis API — routes through the Express proxy at /api/genesis
const GENESIS_API = `${import.meta.env.BASE_URL.replace(/\/$/, '')}/api/genesis`.replace('//', '/');

const DEFAULT_SETTINGS: SimulationSettings = {
  mutationRate: 0.05,
  populationSize: 100,
  maxFuelPerEval: 5000,
  crossoverRate: 0.7,
};

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function apiGet<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${GENESIS_API}${path}`);
    if (!res.ok) return null;
    return await res.json() as T;
  } catch {
    return null;
  }
}

async function apiPost(path: string, body?: unknown): Promise<boolean> {
  try {
    const res = await fetch(`${GENESIS_API}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    return res.ok;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function SimulationProvider({ children }: { children: React.ReactNode }) {
  const [isRunning, setIsRunning] = useState(false);
  const [generation, setGeneration] = useState(0);
  const [history, setHistory] = useState<GenerationData[]>([]);
  const [auditTrail, setAuditTrail] = useState<AuditLog[]>([]);
  const [hallOfFame, setHallOfFame] = useState<HallOfFameEntry[]>([]);
  const [engineAvailable, setEngineAvailable] = useState(false);
  const [settings, setSettings] = useState<SimulationSettings>(() => {
    try {
      const saved = localStorage.getItem('genesis-settings');
      return saved ? JSON.parse(saved) : DEFAULT_SETTINGS;
    } catch {
      return DEFAULT_SETTINGS;
    }
  });

  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Persist settings locally for fast UI reload
  useEffect(() => {
    localStorage.setItem('genesis-settings', JSON.stringify(settings));
  }, [settings]);

  // -------------------------------------------------------------------------
  // Polling: sync state from the Python engine
  // -------------------------------------------------------------------------
  const syncFromEngine = useCallback(async () => {
    const [status, hist, hof, audit] = await Promise.all([
      apiGet<{ isRunning: boolean; generation: number; settings: SimulationSettings }>('/status'),
      apiGet<GenerationData[]>('/history'),
      apiGet<HallOfFameEntry[]>('/hall-of-fame'),
      apiGet<AuditLog[]>('/audit'),
    ]);

    if (status === null) {
      setEngineAvailable(false);
      return;
    }

    setEngineAvailable(true);
    setIsRunning(status.isRunning);
    setGeneration(status.generation);
    // Merge engine settings into local state (engine is source of truth)
    setSettings(prev => ({ ...prev, ...status.settings }));

    if (hist) setHistory(hist);
    if (hof) setHallOfFame(hof);
    if (audit) setAuditTrail(audit);
  }, []);

  // Start polling on mount; keep polling every second
  useEffect(() => {
    syncFromEngine(); // initial fetch

    pollingRef.current = setInterval(() => {
      syncFromEngine();
    }, 1000);

    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [syncFromEngine]);

  // -------------------------------------------------------------------------
  // Local-only audit (for actions that don't yet have a round-trip)
  // -------------------------------------------------------------------------
  const addAudit = useCallback((action: string, details: string) => {
    setAuditTrail(prev => [{
      id: Math.random().toString(36).substring(7),
      timestamp: new Date().toISOString(),
      action,
      details,
    }, ...prev].slice(0, 200));
  }, []);

  // -------------------------------------------------------------------------
  // Controls — call the Python engine, then resync immediately
  // -------------------------------------------------------------------------
  const toggleRun = useCallback(async () => {
    if (isRunning) {
      await apiPost('/stop');
    } else {
      await apiPost('/start');
    }
    await syncFromEngine();
  }, [isRunning, syncFromEngine]);

  const updateSetting = useCallback(async (key: keyof SimulationSettings, value: number) => {
    // Optimistic local update for responsive sliders
    setSettings(prev => ({ ...prev, [key]: value }));
    await apiPost('/settings', { [key]: value });
  }, []);

  const resetRun = useCallback(async () => {
    await apiPost('/reset');
    setIsRunning(false);
    setGeneration(0);
    setHistory([]);
    await syncFromEngine();
  }, [syncFromEngine]);

  const saveToHallOfFame = useCallback(async (entry: Omit<HallOfFameEntry, 'id' | 'dateAdded'>) => {
    await apiPost('/hall-of-fame', entry);
    await syncFromEngine();
  }, [syncFromEngine]);

  return (
    <SimulationContext.Provider value={{
      isRunning,
      generation,
      history,
      auditTrail,
      hallOfFame,
      settings,
      engineAvailable,
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
