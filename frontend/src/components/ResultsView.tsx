import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { Check, X } from 'lucide-react';
import {
  api,
  type AblationRow,
  type EvalCase,
  type EvaluationSummary,
} from '../api/client';
import { ViewStatus } from './ViewStatus';
import { Eyebrow, KeyValue, KeyValueList, Panel, Stat, StatStrip, ViewHeader, ViewPage } from './view';
import { cn } from '@/lib/utils';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Progress } from '@/components/ui/progress';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

type CountMap = Record<string, { passed: number; total: number }>;

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
    <ViewPage>
      <ViewHeader
        title="Evaluation"
        description="Local memory suite and component ablation, backed by the latest saved result files. The suite checks final answers and mechanisms: routing mode, session items, retrieved sources, graph evidence, and whether general knowledge bypasses memory."
      />

      {live ? (
        <LiveResults localEval={localEval} ablation={summary?.ablation ?? null} />
      ) : (
        <ViewStatus
          status={status}
          emptyLabel="No evaluation results yet."
          hint="Run the local eval or ablation, then reload."
        />
      )}
    </ViewPage>
  );
}

/** A pass/fail glyph that does not rely on colour alone. */
function Outcome({ passed }: { passed: boolean }) {
  return passed ? (
    <Check className="size-3.5 shrink-0 text-signal" aria-label="Passed" />
  ) : (
    <X className="size-3.5 shrink-0 text-destructive" aria-label="Failed" />
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

  const stats = [
    { label: 'Local suite', value: `${localEval.passed}/${localEval.total}` },
    { label: 'Local pass rate', value: pct(localEval.pass_rate) },
    full ? { label: 'Full ablation stack', value: `${full.passed}/${full.total}` } : null,
    vectorOnly ? { label: 'Vector-only baseline', value: pct(vectorOnly.pass_rate) } : null,
    transcript ? { label: 'Transcript baseline', value: pct(transcript.pass_rate) } : null,
  ].filter(Boolean) as { label: string; value: string }[];

  return (
    <>
      <StatStrip>
        {stats.map((stat) => (
          <Stat key={stat.label} label={stat.label} value={stat.value} />
        ))}
      </StatStrip>

      <div className="grid items-start gap-4 md:grid-cols-2">
        <BreakdownTable title="Local suite by behavior" counts={localEval.by_category ?? {}} />
        <BreakdownTable title="Local suite by retrieval mode" counts={localEval.by_retrieval_mode ?? {}} />
      </div>

      <section className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <h3 className="text-sm font-medium">Local eval: inspect each case</h3>
          <p className="max-w-2xl text-xs text-pretty text-muted-foreground">
            Pick a case to see the input interactions, expected behavior, final answer, and mechanism
            checks stored by the run.
          </p>
        </div>
        <div className="grid items-start gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
          <Card size="sm">
            <CardContent>
              <ul className="-mx-1 flex max-h-[32rem] flex-col gap-0.5 overflow-y-auto">
                {localEval.cases.map((caseRow) => (
                  <li key={caseRow.id}>
                    <Button
                      variant={caseRow.id === selectedCase?.id ? 'secondary' : 'ghost'}
                      size="sm"
                      className="w-full justify-start gap-2 font-mono font-normal"
                      aria-pressed={caseRow.id === selectedCase?.id}
                      onClick={() => setSelectedCaseId(caseRow.id)}
                    >
                      <Outcome passed={caseRow.passed} />
                      <span className="min-w-0 flex-1 truncate text-left">{caseRow.id}</span>
                      <span className="text-muted-foreground">{caseRow.retrieval_mode ?? 'unknown'}</span>
                    </Button>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
          {selectedCase && <LocalCaseDetail caseRow={selectedCase} />}
        </div>
      </section>

      {ablation && ablation.rows.length > 0 && (
        <section className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <h3 className="text-sm font-medium">Component ablation: architecture value</h3>
            <p className="max-w-2xl text-xs text-pretty text-muted-foreground">
              Each row reruns the same targeted cases with one subsystem disabled. The useful signal is
              not only the score; it is which behavior disappears.
            </p>
          </div>
          <Card size="sm">
            <CardContent>
              <ul className="-mx-1 flex flex-col gap-0.5">
                {ablation.rows.map((row) => (
                  <li key={row.name}>
                    <Button
                      variant={row.name === selectedAblationRow?.name ? 'secondary' : 'ghost'}
                      className="grid h-auto w-full grid-cols-[minmax(0,14rem)_minmax(0,1fr)_3rem] items-center gap-3 py-2 text-left font-normal md:grid-cols-[14rem_minmax(0,1fr)_3rem_minmax(0,16rem)]"
                      aria-pressed={row.name === selectedAblationRow?.name}
                      onClick={() => setSelectedAblation(row.name)}
                    >
                      <span className={cn('truncate font-mono', row.name === 'full_system' && 'font-medium')}>
                        {pretty(row.name)}
                      </span>
                      <Progress value={Math.round(row.pass_rate * 100)} aria-label={`${pretty(row.name)} pass rate`} />
                      <span className="text-right font-mono tabular-nums">{row.passed}/{row.total}</span>
                      <span className="hidden flex-wrap gap-1 md:flex">
                        {row.lost.length > 0 ? (
                          row.lost.map((caseId) => (
                            <Badge key={caseId} variant="destructive" className="font-mono">-{caseId}</Badge>
                          ))
                        ) : (
                          <span className="text-muted-foreground">
                            {row.name === 'full_system' ? 'passes all' : 'no additional loss'}
                          </span>
                        )}
                      </span>
                    </Button>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
          {selectedAblationRow && <AblationDetail row={selectedAblationRow} />}
        </section>
      )}
    </>
  );
}

function LocalCaseDetail({ caseRow }: { caseRow: EvalCase }) {
  const checks = caseRow.checks ?? [];
  return (
    <Card>
      <CardHeader>
        <Eyebrow>{caseRow.category.replaceAll('_', ' ')}</Eyebrow>
        <CardTitle className="font-mono">{caseRow.id}</CardTitle>
        <CardAction>
          <Badge variant={caseRow.passed ? 'outline' : 'destructive'} className={caseRow.passed ? 'text-signal' : undefined}>
            {caseRow.passed ? <Check data-icon="inline-start" /> : <X data-icon="inline-start" />}
            {caseRow.passed ? 'Passed' : 'Failed'}
          </Badge>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <KeyValueList>
          <KeyValue label="Retrieval mode">{caseRow.retrieval_mode ?? 'unknown'}</KeyValue>
          <KeyValue label="Score">{caseRow.score == null ? '—' : String(caseRow.score)}</KeyValue>
          <KeyValue label="Checks">
            {checks.filter((check) => Boolean(check.passed)).length}/{checks.length}
          </KeyValue>
        </KeyValueList>

        <DetailBlock title="Input interactions">
          <ol className="flex flex-col gap-2">
            {(caseRow.interactions ?? []).map((interaction, index) => (
              <li key={index} className="flex flex-col gap-1 border-l pl-3">
                {Boolean(interaction.reset_session) && <Eyebrow>new session</Eyebrow>}
                <p className="text-pretty">{String(interaction.message ?? '')}</p>
              </li>
            ))}
          </ol>
        </DetailBlock>
        <DetailBlock title="Expected behavior">
          <Pre>{JSON.stringify(caseRow.expect ?? {}, null, 2)}</Pre>
        </DetailBlock>
        <DetailBlock title="Actual answer">
          <p className="text-pretty">{caseRow.answer || 'No answer stored.'}</p>
        </DetailBlock>
        <DetailBlock title="Mechanism checks" defaultOpen={false}>
          <ul className="flex flex-col *:border-b *:last:border-b-0">
            {checks.map((check, index) => (
              <li key={index} className="flex flex-wrap items-center gap-2 py-1.5">
                <Outcome passed={Boolean(check.passed)} />
                <span className="font-medium">{String(check.name ?? 'check')}</span>
                {check.observed != null && (
                  <code className="min-w-0 font-mono wrap-break-word text-muted-foreground">
                    {JSON.stringify(check.observed)}
                  </code>
                )}
              </li>
            ))}
          </ul>
        </DetailBlock>
        {caseRow.error && (
          <Alert variant="destructive">
            <AlertDescription>{caseRow.error}</AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  );
}

function AblationDetail({ row }: { row: AblationRow }) {
  const failed = (row.results ?? []).filter((result) => !result.passed);
  return (
    <Card>
      <CardHeader>
        <Eyebrow>Selected configuration</Eyebrow>
        <CardTitle className="font-mono">{pretty(row.name)}</CardTitle>
        <CardAction>
          <span className="font-mono text-2xl font-medium tabular-nums">{pct(row.pass_rate)}</span>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <KeyValueList>
          <KeyValue label="Disabled">{row.disabled.length ? row.disabled.join(', ') : 'none'}</KeyValue>
          <KeyValue label="Passed">{row.passed}/{row.total}</KeyValue>
          <KeyValue label="Drop from full">
            {row.drop_from_full == null ? '—' : `${Math.round(row.drop_from_full * 100)} pts`}
          </KeyValue>
        </KeyValueList>
        <ul className="grid grid-cols-2 gap-x-6 sm:grid-cols-3 lg:grid-cols-4">
          {(row.results ?? []).map((result) => (
            <li key={String(result.id)} className="flex items-center gap-2 border-b py-1.5">
              <Outcome passed={Boolean(result.passed)} />
              <span className="min-w-0 truncate font-mono">{String(result.id).replace('abl-', '')}</span>
              <span className="ml-auto truncate text-muted-foreground">{String(result.category ?? '').replaceAll('_', ' ')}</span>
            </li>
          ))}
        </ul>
        {failed.length > 0 && (
          <DetailBlock title="Failed cases">
            <Pre>{JSON.stringify(failed, null, 2)}</Pre>
          </DetailBlock>
        )}
      </CardContent>
    </Card>
  );
}

function BreakdownTable({ title, counts }: { title: string; counts: CountMap }) {
  const rows = useMemo(() => Object.entries(counts).sort(([a], [b]) => a.localeCompare(b)), [counts]);
  if (rows.length === 0) return null;
  return (
    <Panel title={title}>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Group</TableHead>
            <TableHead className="text-right">Passed</TableHead>
            <TableHead className="text-right">Rate</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map(([label, count]) => (
            <TableRow key={label}>
              <TableCell>{label.replaceAll('_', ' ')}</TableCell>
              <TableCell className="text-right font-mono tabular-nums">{count.passed}/{count.total}</TableCell>
              <TableCell className="text-right font-mono tabular-nums">
                {pct(count.total ? count.passed / count.total : null)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Panel>
  );
}

function DetailBlock({ title, children, defaultOpen = true }: { title: string; children: ReactNode; defaultOpen?: boolean }) {
  return (
    <Collapsible defaultOpen={defaultOpen} className="flex flex-col gap-2">
      <CollapsibleTrigger render={<Button variant="ghost" size="sm" className="-ml-2.5 self-start" />}>
        {title}
      </CollapsibleTrigger>
      <CollapsibleContent>{children}</CollapsibleContent>
    </Collapsible>
  );
}

function Pre({ children }: { children: ReactNode }) {
  return (
    <pre className="max-h-72 overflow-auto rounded-lg border bg-background p-3 font-mono text-xs text-muted-foreground">
      {children}
    </pre>
  );
}

function pct(value: number | null | undefined): string {
  if (value == null) return '—';
  return `${Math.round(value * 100)}%`;
}

function pretty(value: string): string {
  return value.replaceAll('_', ' ');
}
