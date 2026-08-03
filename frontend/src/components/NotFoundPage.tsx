import { ArrowLeft, GitBranch, SearchX } from 'lucide-react';
import BrandMark from './BrandMark';

export default function NotFoundPage() {
  const requestedPath = window.location.pathname;

  return (
    <main className="not-found-page">
      <a className="not-found-brand" href="/" aria-label="MIRA home">
        <BrandMark className="brand-mark" size={24} />
        <span>MIRA</span>
      </a>

      <section className="not-found-content" aria-labelledby="not-found-title">
        <div className="not-found-code" aria-hidden="true">
          <span>4</span>
          <BrandMark size={76} />
          <span>4</span>
        </div>

        <div className="not-found-kicker">
          <SearchX size={15} />
          Retrieval returned nothing
        </div>
        <h1 id="not-found-title">This page has been forgotten.</h1>
        <p>
          MIRA checked session memory, durable memory, and the graph. The URL still does
          not exist. At least the retrieval trace is honest.
        </p>

        <dl className="not-found-trace" aria-label="404 retrieval trace">
          <div>
            <dt>Query</dt>
            <dd>{requestedPath}</dd>
          </div>
          <div>
            <dt>Retrieval mode</dt>
            <dd>Increasingly concerned</dd>
          </div>
          <div>
            <dt>Evidence</dt>
            <dd>0 records</dd>
          </div>
        </dl>

        <div className="not-found-actions">
          <a className="not-found-primary" href="/">
            <ArrowLeft size={16} />
            Return to remembered territory
          </a>
          <a
            className="not-found-secondary"
            href="https://github.com/jerrygeorge360/mira"
            target="_blank"
            rel="noreferrer"
          >
            <GitBranch size={16} />
            Check the source
          </a>
        </div>
      </section>

      <p className="not-found-footnote">
        No memories were harmed while looking for this page.
      </p>
    </main>
  );
}
