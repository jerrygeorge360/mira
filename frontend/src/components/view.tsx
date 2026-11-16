import type { ReactNode } from 'react';
import NumberFlow, { type Format } from '@number-flow/react';
import { cn } from '@/lib/utils';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

/* ─────────────────────────────────────────────────────────
 * VIEW PRIMITIVES — the shared skeleton of every data view
 *
 * The memory and admin views all have the same bones: a page
 * header, a strip of headline numbers, titled panels, and rows
 * of label → value. These wrap the shadcn Card so each view
 * composes the same parts instead of styling its own.
 *
 * "Instrument" rules they encode:
 *   - headline numbers are one bordered strip split by hairlines,
 *     not a grid of separate cards
 *   - labels are mono and uppercase, values are mono and tabular
 *   - no icon tiles; an icon may sit inline before a panel title
 * ───────────────────────────────────────────────────────── */

/**
 * A number that rolls to its new value when it changes (NumberFlow).
 *
 * Use it for values the user can watch change: counts that move when a filter
 * is applied, a different run is selected, or the data refreshes. It does not
 * animate on first render, and it stays still under reduced motion. Leave
 * static numbers and fast tickers (the chat timer) as plain text.
 */
export function Num({
  value,
  format,
  prefix,
  suffix,
  className,
}: {
  value: number;
  format?: Format;
  prefix?: string;
  suffix?: string;
  className?: string;
}) {
  return (
    <NumberFlow
      value={value}
      format={format}
      prefix={prefix}
      suffix={suffix}
      // digits keep one width so neighbours do not shift while a digit rolls
      className={cn('tabular-nums', className)}
    />
  );
}

/** `Num` presets: 0.71 → "0.71", and 0.62 → "62%". */
export const SCORE_FORMAT: Format = { minimumFractionDigits: 2, maximumFractionDigits: 2 };
export const PERCENT_FORMAT: Format = { style: 'percent', maximumFractionDigits: 0 };

/** Root of a data view. `tw` opts the subtree into the scoped Tailwind reset. */
export function ViewPage({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn('tw mx-auto flex w-full max-w-6xl flex-col gap-6', className)}>{children}</div>;
}

export function ViewHeader({
  title,
  description,
  children,
}: {
  title: string;
  description?: ReactNode;
  /** right-hand side: a status badge, a control, a readout */
  children?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
      <div className="flex min-w-0 flex-col gap-1.5">
        <h2 className="text-2xl font-medium tracking-tight">{title}</h2>
        {description && <p className="max-w-2xl text-sm text-pretty text-muted-foreground">{description}</p>}
      </div>
      {children && <div className="flex shrink-0 flex-wrap items-center gap-2">{children}</div>}
    </header>
  );
}

/** A strip of headline numbers. Children are `Stat`s. */
export function StatStrip({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <dl
      className={cn(
        'grid grid-cols-2 overflow-hidden rounded-xl border bg-card sm:grid-flow-col sm:auto-cols-fr sm:grid-cols-none',
        // hairlines between cells without doubling at the edges
        '*:border-b *:border-r sm:*:border-b-0 sm:*:last:border-r-0',
        className,
      )}
    >
      {children}
    </dl>
  );
}

export function Stat({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  /** `signal` for the live/healthy number, `destructive` for one that needs attention */
  tone?: 'signal' | 'destructive';
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1 p-4">
      <dt className="truncate font-mono text-[11px] tracking-wider text-faint uppercase">{label}</dt>
      <dd
        className={cn(
          'font-mono text-2xl font-medium tabular-nums',
          tone === 'signal' && 'text-signal',
          tone === 'destructive' && 'text-destructive',
        )}
      >
        {typeof value === 'number' ? <Num value={value} /> : value}
      </dd>
      {detail && <dd className="text-xs text-muted-foreground">{detail}</dd>}
    </div>
  );
}

/** A titled panel: shadcn Card with the header wired up. */
export function Panel({
  title,
  description,
  icon,
  action,
  className,
  contentClassName,
  children,
  ...props
}: {
  title: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  /** top-right of the header: a count badge, a button */
  action?: ReactNode;
  className?: string;
  contentClassName?: string;
  children: ReactNode;
} & Omit<React.ComponentProps<typeof Card>, 'title'>) {
  return (
    <Card className={className} {...props}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-muted-foreground">
          {icon}
          {title}
        </CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
        {action && <CardAction>{action}</CardAction>}
      </CardHeader>
      <CardContent className={contentClassName}>{children}</CardContent>
    </Card>
  );
}

/** Rows of label → value inside a panel. Children are `KeyValue`s. */
export function KeyValueList({ className, children }: { className?: string; children: ReactNode }) {
  return <dl className={cn('flex flex-col *:border-b *:last:border-b-0', className)}>{children}</dl>;
}

export function KeyValue({ label, children, mono = true }: { label: ReactNode; children: ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-2">
      <dt className="min-w-0 text-xs text-muted-foreground">{label}</dt>
      <dd className={cn('min-w-0 text-right text-xs font-medium wrap-break-word', mono && 'font-mono tabular-nums')}>
        {typeof children === 'number' ? <Num value={children} /> : children}
      </dd>
    </div>
  );
}

/** Small mono uppercase label for a sub-section inside a panel. */
export function Eyebrow({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn('font-mono text-[11px] tracking-wider text-faint uppercase', className)}>{children}</div>;
}
