import type { ReactNode } from 'react';

/**
 * Container with the dashboard's panel chrome. Used by every visualization
 * to give the page a consistent rhythm.
 */
export interface CardProps {
  /** Optional header label shown in muted-color uppercase. */
  title?: string;
  /** Optional header right-side content (e.g. a window selector). */
  rightSlot?: ReactNode;
  className?: string;
  children: ReactNode;
}

export function Card({ title, rightSlot, className = '', children }: CardProps) {
  return (
    <section
      className={`rounded-lg border border-bg-border bg-bg-elevated p-5 ${className}`}
    >
      {(title || rightSlot) && (
        <header className="mb-4 flex items-baseline justify-between">
          {title ? (
            <h2 className="text-xs font-semibold uppercase tracking-wider text-fg-subtle">
              {title}
            </h2>
          ) : (
            <span />
          )}
          {rightSlot}
        </header>
      )}
      {children}
    </section>
  );
}
