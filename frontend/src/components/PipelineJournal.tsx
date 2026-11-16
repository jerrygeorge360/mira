import { useEffect, useState } from 'react';
import type { FocusEvent, MouseEvent } from 'react';
import { createPortal } from 'react-dom';
import { AlertTriangle, Check, ChevronDown, CircleDashed } from 'lucide-react';

/* ─────────────────────────────────────────────────────────
 * PIPELINE JOURNAL — one turn's background consolidation
 *
 * The slow-path step journal as compact rows (status icon,
 * step name, a chip with status and duration). Hover a row to
 * reveal its chevron; rows expand to show timing and any stored
 * error. Below, one chip per artifact type the turn produced;
 * hovering or focusing a chip previews the actual artifact ids.
 * Everything comes from /memory/lifecycle — nothing is invented.
 * ───────────────────────────────────────────────────────── */

export type JournalStep = {
  step_name?: unknown;
  status?: unknown;
  last_error?: unknown;
  created_at?: unknown;
  updated_at?: unknown;
};

const PREVIEW_MAX = 12;

function str(value: unknown) {
  return typeof value === 'string' ? value : '';
}

function labelize(value: string) {
  return (value || 'unknown').replaceAll('_', ' ');
}

function stepTone(step: JournalStep) {
  const status = str(step.status);
  if (step.last_error || status.includes('fail') || status === 'dead_letter' || status === 'quarantined') return 'danger';
  if (status === 'completed' || status === 'done') return 'ok';
  return 'pending';
}

function durationMs(step: JournalStep) {
  const start = Date.parse(str(step.created_at));
  const end = Date.parse(str(step.updated_at));
  return Number.isFinite(start) && Number.isFinite(end) && end >= start ? end - start : null;
}

function formatDuration(ms: number) {
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  return s < 60 ? `${s.toFixed(1)}s` : `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

function formatClock(value: string) {
  const date = new Date(value);
  if (!value || Number.isNaN(date.getTime())) return null;
  return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export default function PipelineJournal({
  steps,
  artifactIds,
  artifactLabels,
}: {
  steps: JournalStep[];
  /** artifact type → ids, as /memory/lifecycle returns it */
  artifactIds: Record<string, unknown>;
  /** display order and names for artifact types */
  artifactLabels: readonly (readonly [string, string, ...unknown[]])[];
}) {
  const [open, setOpen] = useState(false);
  const [openRows, setOpenRows] = useState<Set<number>>(new Set());
  const [preview, setPreview] = useState<{ key: string; x: number; top?: number; bottom?: number } | null>(null);

  // the preview is fixed-position, so any scroll would leave it behind its chip
  useEffect(() => {
    if (!preview) return;
    const close = () => setPreview(null);
    window.addEventListener('scroll', close, { capture: true, passive: true });
    return () => window.removeEventListener('scroll', close, { capture: true });
  }, [preview]);

  const produced = artifactLabels
    .map(([key, label]) => ({ key, label, ids: (Array.isArray(artifactIds[key]) ? artifactIds[key] : []) as string[] }))
    .filter((group) => group.ids.length > 0);
  const totalArtifacts = produced.reduce((sum, group) => sum + group.ids.length, 0);
  const failed = steps.filter((step) => stepTone(step) === 'danger').length;

  const toggleRow = (index: number) =>
    setOpenRows((current) => {
      const next = new Set(current);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });

  const showPreview = (key: string, count: number) => (event: MouseEvent | FocusEvent) => {
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    const height = 40 + Math.min(count, PREVIEW_MAX + 1) * 20;
    const fitsBelow = rect.bottom + 6 + height <= window.innerHeight - 12;
    setPreview({
      key,
      x: Math.max(12, Math.min(rect.left, window.innerWidth - 300)),
      ...(fitsBelow ? { top: rect.bottom + 6 } : { bottom: window.innerHeight - rect.top + 6 }),
    });
  };
  const hidePreview = (key: string) => () => setPreview((current) => (current?.key === key ? null : current));
  const previewGroup = preview ? produced.find((group) => group.key === preview.key) : undefined;

  const summary = [
    `${steps.length} step${steps.length === 1 ? '' : 's'}`,
    `${totalArtifacts} artifact${totalArtifacts === 1 ? '' : 's'}`,
    failed ? `${failed} failed` : null,
  ]
    .filter(Boolean)
    .join(' · ');

  return (
    <div className="journal">
      <button type="button" className="journal-header" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <ChevronDown size={13} className="journal-header-chevron" />
        <span>Step journal</span>
        <span className={`journal-header-summary${failed ? ' danger' : ''}`}>{summary}</span>
      </button>

      <div className={`journal-body${open ? ' open' : ''}`}>
        <div className="journal-inner">
          {steps.length ? (
            <div className="journal-rows">
              {steps.map((step, index) => {
                const tone = stepTone(step);
                const rowOpen = openRows.has(index);
                const ms = durationMs(step);
                const started = formatClock(str(step.created_at));
                const finished = formatClock(str(step.updated_at));
                const error = str(step.last_error);
                const Icon = tone === 'danger' ? AlertTriangle : tone === 'ok' ? Check : CircleDashed;
                return (
                  <div key={`${str(step.step_name)}-${index}`} className="journal-row-wrap">
                    <button
                      type="button"
                      className={`journal-row${rowOpen ? ' open' : ''}`}
                      aria-expanded={rowOpen}
                      onClick={() => toggleRow(index)}
                      tabIndex={open ? 0 : -1}
                    >
                      <span className={`journal-row-icon ${tone}`}>
                        <Icon size={13} strokeWidth={tone === 'ok' ? 2.5 : 2} className="journal-row-glyph" />
                        <ChevronDown size={12} className="journal-row-chevron" />
                      </span>
                      <span className="journal-row-label">{labelize(str(step.step_name))}</span>
                      <span className={`journal-chip ${tone}`}>
                        {labelize(str(step.status))}
                        {ms !== null && <span className="journal-chip-time">{formatDuration(ms)}</span>}
                      </span>
                    </button>
                    <div className={`journal-detail${rowOpen ? ' open' : ''}`}>
                      <div className="journal-inner">
                        <div className="journal-detail-lines">
                          {started && <span>Started {started}</span>}
                          {finished && finished !== started && <span>Last updated {finished}</span>}
                          {error ? <span className="danger">{error}</span> : <span>No stored error</span>}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="journal-empty">No slow-path step journal entries yet.</p>
          )}

          {produced.length > 0 && (
            <div className="journal-artifacts">
              {produced.map((group, i) => (
                <button
                  key={group.key}
                  type="button"
                  className="journal-artifact"
                  style={{ animationDelay: `${i * 60}ms` }}
                  aria-expanded={preview?.key === group.key}
                  aria-label={`${group.ids.length} ${group.label}: show ids`}
                  onMouseEnter={showPreview(group.key, group.ids.length)}
                  onMouseLeave={hidePreview(group.key)}
                  onFocus={showPreview(group.key, group.ids.length)}
                  onBlur={hidePreview(group.key)}
                  tabIndex={open ? 0 : -1}
                >
                  <span>{group.label}</span>
                  <span className="journal-artifact-count">+{group.ids.length}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {preview && previewGroup &&
        createPortal(
          <div
            className="journal-preview"
            role="tooltip"
            style={{
              left: preview.x,
              top: preview.top,
              bottom: preview.bottom,
              transformOrigin: preview.top === undefined ? 'bottom left' : 'top left',
            }}
          >
            <div className="journal-preview-head">
              <span>{previewGroup.label}</span>
              <span className="journal-artifact-count">+{previewGroup.ids.length}</span>
            </div>
            <div className="journal-preview-ids">
              {previewGroup.ids.slice(0, PREVIEW_MAX).map((id) => (
                <code key={id}>{id}</code>
              ))}
              {previewGroup.ids.length > PREVIEW_MAX && (
                <span className="journal-preview-more">+{previewGroup.ids.length - PREVIEW_MAX} more</span>
              )}
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
}
