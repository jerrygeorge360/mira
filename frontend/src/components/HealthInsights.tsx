import { useMemo, useState } from 'react';
import type { PointerEvent, ReactNode } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { api } from '../api/client';
import { useLiveData } from '../api/useLiveData';
import { Num } from './view';

/* ─────────────────────────────────────────────────────────
 * HEALTH INSIGHTS — "Insights N ‹ ›" above Memory Health
 *
 * Small, real visualizations the tier cards don't give you:
 *   · how tracked memory splits across tiers (segmented bar)
 *   · what recent sleep runs kept vs let go (line chart)
 * A card appears only when its data exists. Pages crossfade.
 * ───────────────────────────────────────────────────────── */

type JsonRecord = Record<string, unknown>;

export type TierSummary = { key: string; label: string; count: number; description?: string; capacity?: number; pressure?: number };

const TIER_COLORS: Record<string, string> = {
  hot: '#ef5b55',
  warm: '#e0a13a',
  cold: '#5b8def',
  time_bound: '#3fb27f',
};
const KEPT_COLOR = '#3fb27f';
const LET_GO_COLOR = '#e0a13a';
const MAX_RUNS = 12;

function num(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function pct(part: number, total: number) {
  if (!total) return 0;
  const value = (part / total) * 100;
  return value >= 10 ? Math.round(value) : Math.round(value * 10) / 10;
}

function shortDate(value: unknown) {
  const date = new Date(typeof value === 'string' ? value : '');
  if (Number.isNaN(date.getTime())) return 'Unknown time';
  return date.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

/* Catmull-Rom → cubic bezier path through the points, so the line curves
 * smoothly between runs without overshooting the frame much. */
function smoothPath(points: { x: number; y: number }[]) {
  if (points.length < 2) return '';
  let d = `M ${points[0].x} ${points[0].y}`;
  for (let i = 0; i < points.length - 1; i += 1) {
    const p0 = points[Math.max(0, i - 1)];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[Math.min(points.length - 1, i + 2)];
    const c1 = { x: p1.x + (p2.x - p0.x) / 6, y: p1.y + (p2.y - p0.y) / 6 };
    const c2 = { x: p2.x - (p3.x - p1.x) / 6, y: p2.y - (p3.y - p1.y) / 6 };
    d += ` C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${p2.x} ${p2.y}`;
  }
  return d;
}

/* ── card 1: tier allocation ── */
function TierAllocationCard({ tiers }: { tiers: TierSummary[] }) {
  const total = tiers.reduce((sum, tier) => sum + tier.count, 0);
  const largest = tiers.reduce((a, b) => (b.count > a.count ? b : a), tiers[0]);
  const [selected, setSelected] = useState(largest.key);
  const active = tiers.find((tier) => tier.key === selected) ?? largest;

  return (
    <div className="insight-card">
      <span className="insight-card-title">
        <span className="insight-dot" style={{ background: TIER_COLORS[active.key] }} />
        {active.label}
      </span>
      <span className="insight-hero">
        <Num value={active.count} />
        <small><Num value={pct(active.count, total)} suffix="%" /> of {total.toLocaleString()} tracked</small>
      </span>
      <div className="insight-segments" role="group" aria-label="Memory by tier">
        {tiers.map((tier) => (
          <button
            key={tier.key}
            type="button"
            className="insight-segment"
            aria-pressed={selected === tier.key}
            aria-label={`${tier.label}: ${tier.count} (${pct(tier.count, total)}%)`}
            onClick={() => setSelected(tier.key)}
            // keep empty tiers clickable without distorting the proportions much
            style={{ flexGrow: Math.max(tier.count, total * 0.02), background: TIER_COLORS[tier.key] }}
          >
            <span className="insight-segment-sheen" />
          </button>
        ))}
      </div>
      <div className="insight-legend">
        {tiers.map((tier) => (
          <button
            key={tier.key}
            type="button"
            className="insight-legend-item"
            aria-pressed={selected === tier.key}
            onClick={() => setSelected(tier.key)}
          >
            <span className="insight-dot small" style={{ background: TIER_COLORS[tier.key] }} />
            {tier.label} <span className="insight-num">{pct(tier.count, total)}%</span>
          </button>
        ))}
      </div>
      <div className="insight-detail">
        <span className="insight-detail-title" style={{ color: TIER_COLORS[active.key] }}>{active.label}</span>
        <span>{active.description || 'Persisted memory state.'}</span>
        {typeof active.capacity === 'number' && (
          <span className="insight-num">
            <Num value={active.count} /> / {active.capacity.toLocaleString()} capacity
            {typeof active.pressure === 'number' ? ` · ${Math.round(active.pressure * 100)}% pressure` : ''}
          </span>
        )}
      </div>
    </div>
  );
}

/* ── card 2: sleep activity ── */
type RunPoint = { at: unknown; kept: number; letGo: number; reviewed: number };

function SleepActivityCard({ runs }: { runs: RunPoint[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const keptTotal = runs.reduce((sum, run) => sum + run.kept, 0);
  const letGoTotal = runs.reduce((sum, run) => sum + run.letGo, 0);

  const W = 320;
  const H = 120;
  const PAD = { top: 12, bottom: 12 };
  const max = Math.max(1, ...runs.map((run) => Math.max(run.kept, run.letGo)));
  const x = (i: number) => (runs.length === 1 ? W / 2 : (i / (runs.length - 1)) * W);
  const y = (v: number) => PAD.top + (1 - v / max) * (H - PAD.top - PAD.bottom);
  const keptPath = smoothPath(runs.map((run, i) => ({ x: x(i), y: y(run.kept) })));
  const letGoPath = smoothPath(runs.map((run, i) => ({ x: x(i), y: y(run.letGo) })));

  const onPointer = (event: PointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const t = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
    setHover(Math.round(t * (runs.length - 1)));
  };
  const hovered = hover === null ? null : runs[hover];
  const hoverPct = hover === null ? 0 : (x(hover) / W) * 100;

  return (
    <div className="insight-card">
      <div className="insight-stats">
        <div>
          <span className="insight-card-title"><span className="insight-dot" style={{ background: KEPT_COLOR }} />Reinforced &amp; consolidated</span>
          <span className="insight-hero small" style={{ color: KEPT_COLOR }}>{keptTotal.toLocaleString()}</span>
        </div>
        <div>
          <span className="insight-card-title"><span className="insight-dot" style={{ background: LET_GO_COLOR }} />Archived &amp; forgotten</span>
          <span className="insight-hero small" style={{ color: LET_GO_COLOR }}>{letGoTotal.toLocaleString()}</span>
        </div>
      </div>
      <div className="insight-chart">
        <div className="insight-chart-head">
          <span className="insight-num">
            {hovered ? `${shortDate(hovered.at)} · reviewed ${hovered.reviewed.toLocaleString()}` : `Last ${runs.length} sleep runs`}
          </span>
        </div>
        <div
          className="insight-chart-stage"
          onPointerMove={onPointer}
          onPointerDown={onPointer}
          onPointerLeave={() => setHover(null)}
          role="img"
          aria-label={`Across the last ${runs.length} sleep runs, ${keptTotal} memories were reinforced or consolidated and ${letGoTotal} were archived or forgotten.`}
        >
          <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
            <line x1="0" x2={W} y1={y(0)} y2={y(0)} className="insight-baseline" vectorEffect="non-scaling-stroke" />
            <path d={keptPath} fill="none" stroke={KEPT_COLOR} strokeWidth="2.25" vectorEffect="non-scaling-stroke" strokeLinecap="round" />
            <path d={letGoPath} fill="none" stroke={LET_GO_COLOR} strokeWidth="2.25" vectorEffect="non-scaling-stroke" strokeLinecap="round" />
          </svg>
          {hovered && (
            <>
              <span className="insight-cursor" style={{ left: `${hoverPct}%` }} />
              <span className="insight-tooltip" style={{ left: `${Math.min(Math.max(hoverPct, 22), 78)}%` }}>
                <span><span className="insight-dot small" style={{ background: KEPT_COLOR }} />{hovered.kept} kept</span>
                <span><span className="insight-dot small" style={{ background: LET_GO_COLOR }} />{hovered.letGo} let go</span>
              </span>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── carousel ── */
type Page = { key: string; prose: ReactNode; card: ReactNode };

export default function HealthInsights({ tiers }: { tiers: TierSummary[] }) {
  const { data } = useLiveData(() => api.memorySleepRuns({ limit: 50 }), []);
  const [page, setPage] = useState(0);

  const runs = useMemo<RunPoint[]>(() => {
    const items = (Array.isArray((data as JsonRecord | undefined)?.items) ? (data as JsonRecord).items : []) as JsonRecord[];
    return items
      .filter((run) => run.status === 'completed' || run.status === 'succeeded' || run.completed_at || run.finished_at)
      .slice(0, MAX_RUNS)
      .reverse() // API is newest-first; the chart reads left → right in time
      .map((run) => ({
        at: run.started_at,
        kept: num(run.reinforced_count) + num(run.consolidated_count),
        letGo: num(run.archived_count) + num(run.forgotten_count),
        reviewed: num(run.reviewed_count),
      }));
  }, [data]);

  const pages: Page[] = [];
  const total = tiers.reduce((sum, tier) => sum + tier.count, 0);
  if (total > 0) {
    const largest = tiers.reduce((a, b) => (b.count > a.count ? b : a), tiers[0]);
    pages.push({
      key: 'tiers',
      prose: (
        <>
          Most tracked memory is <b style={{ color: TIER_COLORS[largest.key] }}>{largest.label.toLowerCase()}</b> —{' '}
          <span className="insight-num">{pct(largest.count, total)}%</span> of {total.toLocaleString()} records.
        </>
      ),
      card: <TierAllocationCard tiers={tiers} />,
    });
  }
  if (runs.length >= 2) {
    const kept = runs.reduce((s, r) => s + r.kept, 0);
    const letGo = runs.reduce((s, r) => s + r.letGo, 0);
    pages.push({
      key: 'sleep',
      prose: (
        <>
          Over the last {runs.length} sleep runs, MIRA kept <span className="insight-num">{kept.toLocaleString()}</span>{' '}
          memories strong and let <span className="insight-num">{letGo.toLocaleString()}</span> fade.
        </>
      ),
      card: <SleepActivityCard runs={runs} />,
    });
  }

  if (!pages.length) return null;
  const current = pages[Math.min(page, pages.length - 1)];
  const move = (step: 1 | -1) => setPage((p) => (p + step + pages.length) % pages.length);

  return (
    <section className="insights" aria-roledescription="carousel" aria-label="Memory insights">
      <div className="insights-head">
        <span className="insights-title">
          Insights <span className="insight-num">{pages.length}</span>
        </span>
        {pages.length > 1 && (
          <span className="insights-pager">
            <button type="button" aria-label="Previous insight" onClick={() => move(-1)}><ChevronLeft size={14} /></button>
            <button type="button" aria-label="Next insight" onClick={() => move(1)}><ChevronRight size={14} /></button>
          </span>
        )}
      </div>
      {/* keyed so each page change replays the blurred crossfade */}
      <div key={current.key} className="insights-page" aria-live="polite">
        <p className="insights-prose">{current.prose}</p>
        {current.card}
      </div>
    </section>
  );
}
