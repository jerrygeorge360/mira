import { useEffect, useState } from 'react';
import {
  api,
  type AblationRow,
  type EvalCase,
  type EvaluationSummary,
} from '../api/client';
import { ViewStatus } from './ViewStatus';

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

  const le = summary?.local_eval ?? null;
  const live = status === 'live' && le != null;

  return (
    <div>
      <div className="view-header">
        <h2>Evaluation Results</h2>
        <p>
          Local memory suite · component ablation · LongMemEval benchmark
          {live && ' · live from the latest run'}
        </p>
      </div>

      {live ? (
        <LiveResults
          le={le}
          ablation={summary?.ablation ?? null}
          benchmark={summary?.benchmark ?? null}
        />
      ) : (
        <ViewStatus
          status={status}
          emptyLabel="No evaluation results yet."
          hint="Run the local eval or ablation (make ablation-live), then reload."
        />
      )}
    </div>
  );
}

function LiveResults({
  le,
  ablation,
  benchmark,
}: {
  le: NonNullable<EvaluationSummary['local_eval']>;
  ablation: EvaluationSummary['ablation'];
  benchmark: EvaluationSummary['benchmark'];
}) {
  const full = ablation?.rows.find((r) => r.name === 'full_system');
  const floor = ablation?.rows.find((r) => r.name === 'full_transcript');

  const stats = [
    { label: 'Local memory suite', value: `${le.passed} / ${le.total}` },
    full ? { label: 'Ablation · full system', value: `${full.passed} / ${full.total}` } : null,
    floor ? { label: 'Naive baseline floor', value: pct(floor.pass_rate) } : null,
    benchmark
      ? { label: `Benchmark · ${benchmark.suite}`, value: pct(benchmark.llm_pass_rate) }
      : null,
  ].filter(Boolean) as { label: string; value: string }[];

  return (
    <>
      <div className="results-stats">
        {stats.map((s, i) => (
          <div key={i} className="result-stat-card">
            <div className="val">{s.value}</div>
            <div className="lbl">{s.label}</div>
          </div>
        ))}
      </div>

      <h3 className="results-section-title">Local eval — case by case</h3>
      <div className="eval-case-grid">
        {le.cases.map((c: EvalCase) => (
          <div key={c.id} className={`eval-case-chip ${c.passed ? 'ok' : 'fail'}`}>
            <span className="eval-case-mark">{c.passed ? '✓' : '✗'}</span>
            <span className="eval-case-id">{c.id}</span>
            {c.retrieval_mode && <span className="eval-case-mode">{c.retrieval_mode}</span>}
          </div>
        ))}
      </div>

      {ablation && ablation.rows.length > 0 && (
        <>
          <h3 className="results-section-title">
            Component ablation — each layer’s contribution
          </h3>
          <p className="results-note">
            Every config re-runs the suite with one layer disabled. A drop from the full
            system, and the case it loses, is that layer earning its place.
          </p>
          <div className="ablation-table">
            {ablation.rows.map((r: AblationRow) => (
              <div
                key={r.name}
                className={`ablation-row${r.name === 'full_system' ? ' baseline' : ''}`}
              >
                <div className="ablation-name">{r.name}</div>
                <div className="ablation-bar-track">
                  <div
                    className="ablation-bar-fill"
                    style={{ width: `${Math.round(r.pass_rate * 100)}%` }}
                  />
                </div>
                <div className="ablation-rate">
                  {r.passed}/{r.total}
                </div>
                <div className="ablation-lost">
                  {r.lost.length > 0 ? (
                    r.lost.map((c) => (
                      <span key={c} className="chip chip-lost">
                        −{c}
                      </span>
                    ))
                  ) : r.name === 'full_system' ? (
                    <span className="ablation-lost-none">passes all</span>
                  ) : (
                    <span className="ablation-lost-none">—</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {benchmark && (
        <>
          <h3 className="results-section-title">LongMemEval benchmark</h3>
          <div className="results-stats">
            <div className="result-stat-card">
              <div className="val">{pct(benchmark.llm_pass_rate)}</div>
              <div className="lbl">LLM-judge pass rate</div>
            </div>
            <div className="result-stat-card">
              <div className="val">{benchmark.total_examples}</div>
              <div className="lbl">Examples ({benchmark.llm_mode})</div>
            </div>
            <div className="result-stat-card">
              <div className="val">${benchmark.estimated_cost}</div>
              <div className="lbl">Estimated cost</div>
            </div>
          </div>
        </>
      )}
    </>
  );
}

function pct(value: number | null | undefined): string {
  if (value == null) return '—';
  return `${Math.round(value * 100)}%`;
}
