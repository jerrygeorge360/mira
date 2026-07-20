import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import {
  api,
  type AblationRow,
  type EvalCase,
  type EvaluationSummary,
} from '../api/client';
import { ViewStatus } from './ViewStatus';

type CountMap = Record<string, { passed: number; total: number }>;

// The paper's baseline comparison points, in presentation order (strongest to
// weakest architecture). These read as themselves rather than "without_X" and are
// shown as a dedicated head-to-head, separate from the per-component ablation list.
const BASELINE_ORDER = ['full_system', 'vector_only_baseline', 'full_transcript'] as const;
// Baselines other than full_system are pulled out of the component-ablation list
// (full_system stays there as the reference row).
const BASELINE_ONLY = new Set<string>(['vector_only_baseline', 'full_transcript', 'flat_memory']);

const BASELINE_LABELS: Record<string, string> = {
  full_system: 'Full MIRA',
  vector_only_baseline: 'Vector-only',
  full_transcript: 'Full transcript',
};
const BASELINE_BLURBS: Record<string, string> = {
  full_system: 'Complete architecture: structured memory, tiering, and routed retrieval.',
  vector_only_baseline: 'Quick semantic retrieval alone — every higher memory layer disabled.',
  full_transcript: 'No derived or retrieved memory; the model answers from the raw conversation.',
};

export default function ResultsView() {
  const [summary, setSummary] = useState<EvaluationSummary | null>(null);
  const [status, setStatus] = useState<'loading' | 'live' | 'offline'>('loading');

  useEffect(() => {
    let active = true;
    api
      .evaluationSummary()
      .then((s) => {
        if (!active) return;
        setSummary(s);
        setStatus('live');
      })
      .catch(() => {
        if (active) setStatus('offline');
      });
    return () => {
      active = false;
    };
  }, []);

  const localEval = summary?.local_eval ?? null;
  const live = status === 'live' && localEval != null;

  return (
    <div>
      <div className="view-header">
        <h2>Evaluation</h2>
        <p>
          Local memory suite and component ablation, backed by the latest saved result files.
        </p>
      </div>

      {live ? (
        <LiveResults localEval={localEval} ablation={summary?.ablation ?? null} />
      ) : (
        <ViewStatus
          status={status}
          emptyLabel="No evaluation results yet."
          hint="Run the local eval or ablation, then reload."
        />
      )}
    </div>
  );
}

function LiveResults({
  localEval,
  ablation,
}: {
  localEval: NonNullable<EvaluationSummary['local_eval']>;
  ablation: EvaluationSummary['ablation'];
}) {
  const [selectedCaseId, setSelectedCaseId] = useState(localEval.cases[0]?.id ?? '');
  const [selectedAblation, setSelectedAblation] = useState(
    ablation?.rows.find((row) => row.name === 'full_system')?.name ?? ablation?.rows[0]?.name ?? '',
  );
  const selectedCase = localEval.cases.find((caseRow) => caseRow.id === selectedCaseId)
    ?? localEval.cases[0];
  const selectedAblationRow = ablation?.rows.find((row) => row.name === selectedAblation)
    ?? ablation?.rows[0]
    ?? null;
  const full = ablation?.rows.find((row) => row.name === 'full_system');
  const vectorOnly = ablation?.rows.find((row) => row.name === 'vector_only_baseline');
  const transcript = ablation?.rows.find((row) => row.name === 'full_transcript');

  // Baselines are the paper's head-to-head comparison points (full MIRA vs naive
  // retrieval strategies). They read as themselves, not "without_X", so they get
  // their own section and are kept out of the per-component ablation list below.
  const baselineRows = BASELINE_ORDER
    .map((name) => ablation?.rows.find((row) => row.name === name))
    .filter(Boolean) as AblationRow[];
  const componentRows = (ablation?.rows ?? []).filter((row) => !BASELINE_ONLY.has(row.name));

  const stats = [
    { label: 'Local suite', value: `${localEval.passed}/${localEval.total}` },
    { label: 'Local pass rate', value: pct(localEval.pass_rate) },
    full ? { label: 'Full ablation stack', value: `${full.passed}/${full.total}` } : null,
    vectorOnly ? { label: 'Vector-only baseline', value: pct(vectorOnly.pass_rate) } : null,
    transcript ? { label: 'Transcript baseline', value: pct(transcript.pass_rate) } : null,
  ].filter(Boolean) as { label: string; value: string }[];

  return (
    <>
      <section className="results-abstract">
        <strong>Readout.</strong> The local suite checks final answers and mechanisms:
        routing mode, session items, retrieved sources, graph evidence, and whether general
        knowledge bypasses memory. Ablation shows which component each behavior depends on.
      </section>

      <div className="results-stats">
        {stats.map((stat) => (
          <div key={stat.label} className="result-stat-card">
            <div className="val">{stat.value}</div>
            <div className="lbl">{stat.label}</div>
          </div>
        ))}
      </div>

      <div className="results-breakdown-grid">
        <BreakdownTable title="Local suite by behavior" counts={localEval.by_category ?? {}} />
        <BreakdownTable title="Local suite by retrieval mode" counts={localEval.by_retrieval_mode ?? {}} />
      </div>

      <h3 className="results-section-title">Local eval — inspect each case</h3>
      <p className="results-note">
        Click a case to see the input interactions, expected behavior, final answer, and
        mechanism checks stored by the run.
      </p>
      <div className="results-inspector">
        <div className="eval-case-list">
          {localEval.cases.map((caseRow) => (
            <button
              key={caseRow.id}
              className={`eval-case-row ${caseRow.passed ? 'ok' : 'fail'}${caseRow.id === selectedCase?.id ? ' active' : ''}`}
              onClick={() => setSelectedCaseId(caseRow.id)}
              type="button"
            >
              <span className="eval-case-mark">{caseRow.passed ? '✓' : '✗'}</span>
              <span className="eval-case-id">{caseRow.id}</span>
              <span className="eval-case-mode">{caseRow.retrieval_mode ?? 'unknown'}</span>
            </button>
          ))}
        </div>
        {selectedCase && <LocalCaseDetail caseRow={selectedCase} />}
      </div>

      {baselineRows.length > 0 && (
        <>
          <h3 className="results-section-title">Baseline comparison — architecture vs. naive memory</h3>
          <p className="results-note">
            The same cases answered by the full architecture versus two naive baselines:
            vector-only retrieval (Quick alone, every higher layer stripped) and the full
            raw transcript (no derived or retrieved memory). This is the head-to-head that
            shows what the memory architecture buys over dumping context at the model.
          </p>
          <div className="baseline-compare">
            {baselineRows.map((row) => (
              <div
                key={row.name}
                className={`baseline-card ${row.name === 'full_system' ? 'is-full' : ''}`}
              >
                <div className="baseline-card-head">
                  <span className="baseline-card-name">{BASELINE_LABELS[row.name] ?? pretty(row.name)}</span>
                  <span className="baseline-card-rate">{row.passed}/{row.total}</span>
                </div>
                <div className="ablation-bar-track">
                  <div
                    className="ablation-bar-fill"
                    style={{ width: `${Math.round(row.pass_rate * 100)}%` }}
                  />
                </div>
                <div className="baseline-card-sub">{pct(row.pass_rate)}</div>
                <p className="baseline-card-blurb">{BASELINE_BLURBS[row.name] ?? ''}</p>
              </div>
            ))}
          </div>
        </>
      )}

      {componentRows.length > 0 && (
        <>
          <h3 className="results-section-title">Component ablation — architecture value</h3>
          <p className="results-note">
            Each row reruns the same targeted cases with one subsystem disabled. The useful signal
            is not only the score; it is which behavior disappears.
          </p>
          <div className="ablation-table rich">
            {componentRows.map((row) => (
              <button
                type="button"
                key={row.name}
                className={`ablation-row ${row.name === 'full_system' ? 'baseline' : ''}${row.name === selectedAblationRow?.name ? ' active' : ''}`}
                onClick={() => setSelectedAblation(row.name)}
              >
                <div className="ablation-name">{pretty(row.name)}</div>
                <div className="ablation-bar-track">
                  <div
                    className="ablation-bar-fill"
                    style={{ width: `${Math.round(row.pass_rate * 100)}%` }}
                  />
                </div>
                <div className="ablation-rate">{row.passed}/{row.total}</div>
                <div className="ablation-lost">
                  {row.lost.length > 0 ? (
                    row.lost.map((caseId) => (
                      <span key={caseId} className="chip chip-lost">-{caseId}</span>
                    ))
                  ) : row.name === 'full_system' ? (
                    <span className="ablation-lost-none">passes all</span>
                  ) : (
                    <span className="ablation-lost-none">no additional loss</span>
                  )}
                </div>
              </button>
            ))}
          </div>
          {selectedAblationRow && <AblationDetail row={selectedAblationRow} />}
        </>
      )}
    </>
  );
}

function LocalCaseDetail({ caseRow }: { caseRow: EvalCase }) {
  return (
    <article className={`eval-detail-card ${caseRow.passed ? 'ok' : 'fail'}`}>
      <div className="eval-detail-top">
        <div>
          <div className="eval-detail-kicker">{caseRow.category.replaceAll('_', ' ')}</div>
          <h4>{caseRow.id}</h4>
        </div>
        <span className={`eval-outcome ${caseRow.passed ? 'ok' : 'fail'}`}>
          {caseRow.passed ? 'Passed' : 'Failed'}
        </span>
      </div>
      <div className="eval-detail-grid">
        <Field label="Retrieval mode" value={caseRow.retrieval_mode ?? 'unknown'} />
        <Field label="Score" value={caseRow.score == null ? '—' : String(caseRow.score)} />
        <Field
          label="Checks"
          value={`${caseRow.checks?.filter((check) => Boolean(check.passed)).length ?? 0}/${caseRow.checks?.length ?? 0}`}
        />
      </div>
      <DetailBlock title="Input interactions">
        <ol className="eval-interactions">
          {(caseRow.interactions ?? []).map((interaction, index) => (
            <li key={index}>
              {Boolean(interaction.reset_session) && <span>new session</span>}
              <p>{String(interaction.message ?? '')}</p>
            </li>
          ))}
        </ol>
      </DetailBlock>
      <DetailBlock title="Expected behavior">
        <pre>{JSON.stringify(caseRow.expect ?? {}, null, 2)}</pre>
      </DetailBlock>
      <DetailBlock title="Actual answer">
        <p>{caseRow.answer || 'No answer stored.'}</p>
      </DetailBlock>
      <DetailBlock title="Mechanism checks">
        <div className="eval-check-list">
          {(caseRow.checks ?? []).map((check, index) => (
            <div key={index} className={`eval-check ${check.passed ? 'ok' : 'fail'}`}>
              <span>{check.passed ? '✓' : '✗'}</span>
              <strong>{String(check.name ?? 'check')}</strong>
              {check.observed != null && <code>{JSON.stringify(check.observed)}</code>}
            </div>
          ))}
        </div>
      </DetailBlock>
      {caseRow.error && <p className="results-error">{caseRow.error}</p>}
    </article>
  );
}

function AblationDetail({ row }: { row: AblationRow }) {
  const failed = (row.results ?? []).filter((result) => !result.passed);
  return (
    <article className="ablation-detail-card">
      <div className="eval-detail-top">
        <div>
          <div className="eval-detail-kicker">selected configuration</div>
          <h4>{pretty(row.name)}</h4>
        </div>
        <span className="eval-outcome">{pct(row.pass_rate)}</span>
      </div>
      <div className="eval-detail-grid">
        <Field label="Disabled" value={row.disabled.length ? row.disabled.join(', ') : 'none'} />
        <Field label="Passed" value={`${row.passed}/${row.total}`} />
        <Field
          label="Drop from full"
          value={row.drop_from_full == null ? '—' : `${Math.round(row.drop_from_full * 100)} pts`}
        />
      </div>
      <div className="ablation-case-grid">
        {(row.results ?? []).map((result) => (
          <div key={String(result.id)} className={`ablation-case-chip ${result.passed ? 'ok' : 'fail'}`}>
            <span>{result.passed ? '✓' : '✗'}</span>
            <strong>{String(result.id).replace('abl-', '')}</strong>
            <small>{String(result.category ?? '')}</small>
          </div>
        ))}
      </div>
      {failed.length > 0 && (
        <DetailBlock title="Failed cases">
          <pre>{JSON.stringify(failed, null, 2)}</pre>
        </DetailBlock>
      )}
    </article>
  );
}

function BreakdownTable({ title, counts }: { title: string; counts: CountMap }) {
  const rows = useMemo(() => Object.entries(counts).sort(([a], [b]) => a.localeCompare(b)), [counts]);
  if (rows.length === 0) return null;
  return (
    <section className="results-breakdown-card">
      <h3>{title}</h3>
      {rows.map(([label, count]) => (
        <div key={label} className="results-breakdown-row">
          <span>{label.replaceAll('_', ' ')}</span>
          <strong>{count.passed}/{count.total}</strong>
          <em>{pct(count.total ? count.passed / count.total : null)}</em>
        </div>
      ))}
    </section>
  );
}

function DetailBlock({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details className="eval-detail-block" open={title !== 'Mechanism checks'}>
      <summary>{title}</summary>
      <div>{children}</div>
    </details>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function pct(value: number | null | undefined): string {
  if (value == null) return '—';
  return `${Math.round(value * 100)}%`;
}

function pretty(value: string): string {
  return value.replaceAll('_', ' ');
}
