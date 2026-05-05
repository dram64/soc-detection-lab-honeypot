import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Dashboard } from './routes/Dashboard';

// Defaults match the backend's CloudFront 30s cache TTL with a small
// buffer; per-hook overrides live in src/api/queries.ts.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 25_000,
      refetchInterval: 30_000,
      refetchOnWindowFocus: true,
      retry: 2,
      retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30_000),
    },
  },
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Dashboard />
    </QueryClientProvider>
  );
}

export default App;
