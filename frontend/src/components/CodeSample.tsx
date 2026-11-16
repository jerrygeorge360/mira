import { useState } from 'react';
import { DownloadIcon, FileCodeIcon, TerminalIcon, WrapTextIcon } from 'lucide-react';
import { useHighlightedCode } from '@/hooks/use-highlighted-code';
import { Button } from '@/components/ui/button';
import {
  CodeBlock,
  CodeBlockActions,
  CodeBlockContent,
  CodeBlockCopyButton,
  CodeBlockHeader,
  CodeBlockLine,
  CodeBlockTitle,
} from '@/components/ui/code-block';

/* ─────────────────────────────────────────────────────────
 * CODE SAMPLE — the shadcn CodeBlock, set up for docs
 *
 * One component for every console and snippet in the developer
 * portal: a titled header (a file name, or a method and path),
 * Shiki highlighting that follows the light/dark theme, line
 * numbers, optional highlighted lines, and actions to wrap long
 * lines, download, and copy.
 * ───────────────────────────────────────────────────────── */

function download(value: string, filename: string) {
  const url = URL.createObjectURL(new Blob([value], { type: 'text/plain' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export default function CodeSample({
  code,
  language,
  title,
  filename,
  highlight,
  lineNumbers = true,
  className,
}: {
  code: string;
  /** a Shiki language: bash, json, ts, tsx, python … */
  language: string;
  /** shown in the header; defaults to the filename */
  title?: string;
  /** enables the download action, and is the name it saves as */
  filename?: string;
  /** 1-based line numbers to mark */
  highlight?: number[];
  lineNumbers?: boolean;
  className?: string;
}) {
  const [wrap, setWrap] = useState(false);
  const lines = useHighlightedCode(code, language);
  const shell = language === 'bash' || language === 'sh';
  const label = title ?? filename;

  return (
    <CodeBlock className={className}>
      <CodeBlockHeader>
        {label && (
          <CodeBlockTitle>
            {shell ? <TerminalIcon /> : <FileCodeIcon />}
            {label}
          </CodeBlockTitle>
        )}
        <CodeBlockActions>
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label="Wrap lines"
            aria-pressed={wrap}
            className="aria-pressed:text-foreground"
            onClick={() => setWrap(!wrap)}
          >
            <WrapTextIcon />
          </Button>
          {filename && (
            <Button variant="ghost" size="icon-xs" aria-label={`Download ${filename}`} onClick={() => download(code, filename)}>
              <DownloadIcon />
            </Button>
          )}
          <CodeBlockCopyButton value={code} />
        </CodeBlockActions>
      </CodeBlockHeader>
      <CodeBlockContent wrap={wrap} lineNumbers={lineNumbers}>
        {lines.map((line, index) => (
          <CodeBlockLine key={index} variant={highlight?.includes(index + 1) ? 'highlighted' : 'default'}>
            {line}
          </CodeBlockLine>
        ))}
      </CodeBlockContent>
    </CodeBlock>
  );
}
