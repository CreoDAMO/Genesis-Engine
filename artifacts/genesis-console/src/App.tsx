import { Route, Switch, Router as WouterRouter } from 'wouter';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TooltipProvider } from '@/components/ui/tooltip';
import { Toaster } from '@/components/ui/toaster';

import { SimulationProvider } from '@/lib/store';
import { ConsoleLayout } from '@/components/layout/ConsoleLayout';

import Overview from '@/pages/Overview';
import Strategies from '@/pages/Strategies';
import Safety from '@/pages/Safety';
import Portfolio from '@/pages/Portfolio';
import Audit from '@/pages/Audit';
import NotFound from '@/pages/not-found';

const queryClient = new QueryClient();

function Router() {
  return (
    <ConsoleLayout>
      <Switch>
        <Route path="/" component={Overview} />
        <Route path="/strategies" component={Strategies} />
        <Route path="/safety" component={Safety} />
        <Route path="/portfolio" component={Portfolio} />
        <Route path="/audit" component={Audit} />
        <Route component={NotFound} />
      </Switch>
    </ConsoleLayout>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <SimulationProvider>
        <TooltipProvider>
          <WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, '')}>
            <Router />
          </WouterRouter>
          <Toaster />
        </TooltipProvider>
      </SimulationProvider>
    </QueryClientProvider>
  );
}

export default App;
