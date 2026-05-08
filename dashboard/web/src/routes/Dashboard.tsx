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
    label = 'LOADING';
    cls = 'text-fg-muted';
  } else if (health.isError) {
    label = 'ERROR';
    cls = 'text-danger';
  } else {
    label = 'ONLINE';
    cls = 'text-ok';
  }
  return (
    <div className="flex items-baseline gap-3">
      <span
        className={`font-mono text-xs font-bold uppercase tracking-widest ${cls}`}
      >
        [ {label} ]
      </span>
      {health.data?.version ? (
        <span className="font-mono text-xs text-fg-subtle">
          {health.data.version.slice(0, 7)}
        </span>
      ) : null}
    </div>
  );
}

export function Dashboard() {
  return (
    <main className="mx-auto max-w-7xl px-6 py-10">
      <header className="flex flex-wrap items-baseline justify-between gap-4 border-b-2 border-bg-edge pb-6">
        <div>
          {/* // prefix is via ::before so it's purely visual — keeps
              getByText('Honeypot Dashboard') test assertions matching. */}
          <h1 className="font-display text-7xl uppercase leading-none tracking-widest text-fg before:mr-3 before:text-accent before:drop-shadow-[0_0_24px_rgba(245,209,31,0.55)] before:content-['//']">
            Honeypot Dashboard
          </h1>
          <p className="mt-3 font-mono text-sm uppercase tracking-widest text-fg-muted">
            Cowrie SSH honeypot · live capture
          </p>
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
