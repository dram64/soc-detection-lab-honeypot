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
      className={`scan-lines border border-bg-border border-l-4 border-l-accent bg-bg-elevated p-5 ${className}`}
    >
      {(title || rightSlot) && (
        <header className="mb-4 flex items-end justify-between border-b border-bg-border pb-3">
          {title ? (
            // The » prefix is a CSS ::before pseudo-element so it shows
            // visually but isn't in the DOM textContent — keeps existing
            // tests' getByText('Title') matchers working unchanged.
            <h2 className="font-display text-2xl uppercase leading-none tracking-widest text-fg before:mr-3 before:text-accent before:content-['»']">
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
