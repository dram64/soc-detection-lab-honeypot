import { useHealth } from '../api/queries';
import { CounterRow } from '../components/CounterRow/CounterRow';
import { GeoMap } from '../components/GeoMap/GeoMap.lazy';
import { RecentEventsTable } from '../components/RecentEventsTable/RecentEventsTable';
import { TimelineChart } from '../components/TimelineChart/TimelineChart';
import { TopPasswordsChart } from '../components/TopPasswordsChart/TopPasswordsChart';
import { TopUsernamesChart } from '../components/TopUsernamesChart/TopUsernamesChart';

function StatusPill() {
  const health = useHealth();
  let label: string;
  let cls: string;
  if (health.isPending) {
    label = '○ loading';
    cls = 'text-fg-muted';
  } else if (health.isError) {
    label = '● error';
    cls = 'text-danger';
  } else {
    label = '● healthy';
    cls = 'text-ok';
  }
  return (
    <div className="flex items-baseline gap-3">
      <span className={`text-sm font-medium ${cls}`}>{label}</span>
      {health.data?.version ? (
        <span className="font-mono text-xs text-fg-subtle">{health.data.version}</span>
      ) : null}
    </div>
  );
}

export function Dashboard() {
  return (
    <main className="mx-auto max-w-7xl px-6 py-10">
      <header className="flex flex-wrap items-baseline justify-between gap-4 border-b border-bg-border pb-6">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Honeypot Dashboard</h1>
          <p className="mt-1 text-fg-muted">Cowrie SSH honeypot, real-time</p>
        </div>
        <StatusPill />
      </header>

      <div className="mt-8 space-y-6">
        <CounterRow />

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <TopUsernamesChart />
          <TopPasswordsChart />
        </div>

        {/* GeoMap: hide on mobile (< md) — projection is unreadable below
            ~640 px and the data is also surfaced via top/countries text. */}
        <div className="hidden md:block">
          <GeoMap />
        </div>

        <TimelineChart />

        <RecentEventsTable />
      </div>

      <footer className="mt-12 border-t border-bg-border pt-6 text-center text-xs text-fg-subtle">
        <p>
          Passwords shown are dictionary-classified attempts from the bundled attack-dictionary
          list; non-dictionary attempts are length-redacted (
          <a
            href="https://github.com/dram64/soc-detection-lab/blob/main/dashboard/docs/adr/005-password-filtering.md"
            target="_blank"
            rel="noreferrer"
            className="underline decoration-fg-subtle/50 hover:text-fg-muted hover:decoration-accent"
          >
            ADR-005
          </a>
          ).
        </p>
      </footer>
    </main>
  );
}
