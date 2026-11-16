import { useEffect, useMemo, useRef, useState } from 'react';
import type { ChangeEvent, FormEvent } from 'react';
import {
  AlertCircle,
  BookOpen,
  ChevronRight,
  FileText,
  FolderPlus,
  Info,
  Trash2,
  Upload,
} from 'lucide-react';
import {
  api,
  type KnowledgeBase,
  type KnowledgeBaseDocument,
  type KnowledgeBaseDocumentsResponse,
  type KnowledgeBaseListResponse,
} from '../api/client';
import { useApp } from '../context/AppContext';
import LoadingState from './LoadingState';
import { Num } from './view';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Separator } from '@/components/ui/separator';
import { Spinner } from '@/components/ui/spinner';
import { Textarea } from '@/components/ui/textarea';

/** A delete that is waiting for the user to confirm it in the dialog. */
type PendingDelete = { kind: 'base'; base: KnowledgeBase } | { kind: 'document'; document: KnowledgeBaseDocument };

const MAX_FILE_BYTES = 10 * 1024 * 1024;
const MAX_FILE_LABEL = '10 MB';
const ACCEPTED_EXTENSIONS = ['.txt', '.md', '.docx', '.pdf'];

type LoadState = 'loading' | 'ready' | 'error';

export default function KnowledgeBasesView() {
  const { sessionId } = useApp();
  const [confirming, setConfirming] = useState<PendingDelete | null>(null);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [attachedKnowledgeBaseIds, setAttachedKnowledgeBaseIds] = useState<string[]>([]);
  const [documentRetrievalEnabled, setDocumentRetrievalEnabled] = useState(false);
  const [savingAttachment, setSavingAttachment] = useState(false);
  const [documents, setDocuments] = useState<KnowledgeBaseDocument[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [basesState, setBasesState] = useState<LoadState>('loading');
  const [documentsState, setDocumentsState] = useState<LoadState>('ready');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [newName, setNewName] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [creating, setCreating] = useState(false);
  const [deletingBaseId, setDeletingBaseId] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const selectedBase = useMemo(
    () => knowledgeBases.find((knowledgeBase) => knowledgeBase.id === selectedId) ?? null,
    [knowledgeBases, selectedId],
  );

  async function loadKnowledgeBases(preferredId?: string | null) {
    setBasesState('loading');
    setError(null);
    try {
      const response = await api.knowledgeBases();
      const nextBases = normalizeKnowledgeBases(response);
      setKnowledgeBases(nextBases);
      setSelectedId((currentId) => {
        const candidate = preferredId ?? currentId;
        return candidate && nextBases.some((base) => base.id === candidate)
          ? candidate
          : nextBases[0]?.id ?? null;
      });
      setBasesState('ready');
    } catch (loadError) {
      setBasesState('error');
      setError(errorMessage(loadError, 'Knowledge bases could not be loaded.'));
    }
  }

  async function loadDocuments(knowledgeBaseId: string) {
    setDocumentsState('loading');
    setError(null);
    try {
      const response = await api.knowledgeBaseDocuments(knowledgeBaseId);
      setDocuments(normalizeDocuments(response));
      setDocumentsState('ready');
    } catch (loadError) {
      setDocuments([]);
      setDocumentsState('error');
      setError(errorMessage(loadError, 'Documents could not be loaded.'));
    }
  }

  useEffect(() => {
    void loadKnowledgeBases();
  }, []);

  useEffect(() => {
    let active = true;
    if (!sessionId) {
      setAttachedKnowledgeBaseIds([]);
      setDocumentRetrievalEnabled(false);
      return () => { active = false; };
    }
    api.sessionKnowledgeBases(sessionId)
      .then((response) => {
        if (!active) return;
        setDocumentRetrievalEnabled(response.retrieval_enabled);
        setAttachedKnowledgeBaseIds(
          response.knowledge_bases.filter((base) => base.attached).map((base) => base.id),
        );
      })
      .catch((loadError) => {
        if (active) setError(errorMessage(loadError, 'Chat library access could not be loaded.'));
      });
    return () => { active = false; };
  }, [sessionId]);

  useEffect(() => {
    if (selectedId) {
      void loadDocuments(selectedId);
    } else {
      setDocuments([]);
      setDocumentsState('ready');
    }
  }, [selectedId]);

  async function createKnowledgeBase(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = newName.trim();
    if (!name) return;
    setCreating(true);
    setError(null);
    setNotice(null);
    try {
      const response = await api.createKnowledgeBase({
        name,
        ...(newDescription.trim() ? { description: newDescription.trim() } : {}),
      });
      const created = normalizeKnowledgeBase(response);
      setNewName('');
      setNewDescription('');
      setNotice(`“${created.name}” is ready.`);
      await loadKnowledgeBases(created.id);
    } catch (createError) {
      setError(errorMessage(createError, 'Knowledge base could not be created.'));
    } finally {
      setCreating(false);
    }
  }

  async function deleteKnowledgeBase(knowledgeBase: KnowledgeBase) {
    setDeletingBaseId(knowledgeBase.id);
    setError(null);
    setNotice(null);
    try {
      await api.deleteKnowledgeBase(knowledgeBase.id);
      setNotice(`“${knowledgeBase.name}” was deleted.`);
      await loadKnowledgeBases(selectedId === knowledgeBase.id ? null : selectedId);
    } catch (deleteError) {
      setError(errorMessage(deleteError, 'Knowledge base could not be deleted.'));
    } finally {
      setDeletingBaseId(null);
    }
  }

  async function toggleSessionAttachment(knowledgeBase: KnowledgeBase) {
    if (!sessionId) return;
    const isAttached = attachedKnowledgeBaseIds.includes(knowledgeBase.id);
    const nextIds = isAttached
      ? attachedKnowledgeBaseIds.filter((id) => id !== knowledgeBase.id)
      : [...attachedKnowledgeBaseIds, knowledgeBase.id];
    setSavingAttachment(true);
    setError(null);
    setNotice(null);
    try {
      const response = await api.updateSessionKnowledgeBases(sessionId, nextIds);
      setDocumentRetrievalEnabled(response.retrieval_enabled);
      setAttachedKnowledgeBaseIds(
        response.knowledge_bases.filter((base) => base.attached).map((base) => base.id),
      );
      setNotice(isAttached
        ? `“${knowledgeBase.name}” was removed from this chat.`
        : `“${knowledgeBase.name}” was attached to this chat.`);
    } catch (saveError) {
      setError(errorMessage(saveError, 'Chat library access could not be updated.'));
    } finally {
      setSavingAttachment(false);
    }
  }

  function selectFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    setSelectedFile(null);
    setFileError(null);
    setNotice(null);
    if (!file) return;

    const extension = getExtension(file.name);
    if (!ACCEPTED_EXTENSIONS.includes(extension)) {
      setFileError('Use a .txt, .md, .docx, or text-based .pdf file.');
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      setFileError(`This file is larger than ${MAX_FILE_LABEL}.`);
      return;
    }
    setSelectedFile(file);
  }

  async function uploadDocument() {
    if (!selectedId || !selectedFile) return;
    setUploading(true);
    setError(null);
    setNotice(null);
    try {
      const uploaded = await api.uploadKnowledgeBaseDocument(selectedId, selectedFile);
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
      setNotice(`${uploaded.filename || selectedFile.name} was added.`);
      await Promise.all([loadDocuments(selectedId), loadKnowledgeBases(selectedId)]);
    } catch (uploadError) {
      setError(errorMessage(uploadError, 'The document could not be uploaded.'));
    } finally {
      setUploading(false);
    }
  }

  async function deleteDocument(document: KnowledgeBaseDocument) {
    setError(null);
    setNotice(null);
    try {
      await api.deleteKnowledgeBaseDocument(document.id);
      setNotice(`“${document.filename}” was deleted.`);
      if (selectedId) await Promise.all([loadDocuments(selectedId), loadKnowledgeBases(selectedId)]);
    } catch (deleteError) {
      setError(errorMessage(deleteError, 'The document could not be deleted.'));
    }
  }

  return (
    <div className="tw mx-auto flex w-full max-w-6xl flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1.5">
          <h2 className="text-2xl font-medium tracking-tight">Knowledge Bases</h2>
          <p className="max-w-xl text-sm text-muted-foreground">
            Keep source documents close to the answers they support. Documents stay separate from MIRA’s personal memory.
          </p>
        </div>
        <p className="font-mono text-xs leading-relaxed text-faint sm:text-right">
          TXT · MD · DOCX · text-based PDF
          <br />
          Up to {MAX_FILE_LABEL} per file · PDF up to 100 pages
        </p>
      </header>

      {(error || notice) && (
        <Alert variant={error ? 'destructive' : 'default'} role="status" aria-live="polite">
          {error ? <AlertCircle /> : <Info />}
          <AlertDescription>{error ?? notice}</AlertDescription>
        </Alert>
      )}

      <div className="grid items-start gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
        <Card aria-label="Knowledge base list">
          <CardHeader>
            <CardTitle>Your libraries</CardTitle>
            <CardAction>
              <Badge variant="outline" className="font-mono"><Num value={knowledgeBases.length} /></Badge>
            </CardAction>
          </CardHeader>
          <CardContent>
            <p className="mb-3 rounded-md border px-3 py-2 text-xs text-muted-foreground" aria-live="polite">
              {sessionId
                ? documentRetrievalEnabled
                  ? `${attachedKnowledgeBaseIds.length} librar${attachedKnowledgeBaseIds.length === 1 ? 'y' : 'ies'} attached to this chat`
                  : 'Library access is saved, but document retrieval is disabled for this workspace.'
                : 'Start or open a chat to choose which libraries MIRA can use.'}
            </p>
            {basesState === 'loading' ? (
              <LoadingState label="Loading libraries" />
            ) : knowledgeBases.length === 0 ? (
              <Empty className="border">
                <EmptyHeader>
                  <EmptyMedia variant="icon">
                    <FolderPlus />
                  </EmptyMedia>
                  <EmptyTitle>No knowledge bases yet</EmptyTitle>
                  <EmptyDescription>Create one below, then add a source document.</EmptyDescription>
                </EmptyHeader>
              </Empty>
            ) : (
              <div className="flex flex-col gap-1">
                {knowledgeBases.map((knowledgeBase) => (
                  <Button
                    key={knowledgeBase.id}
                    variant={selectedId === knowledgeBase.id ? 'secondary' : 'ghost'}
                    className="h-auto justify-start gap-2.5 py-2 text-left"
                    aria-pressed={selectedId === knowledgeBase.id}
                    onClick={() => {
                      setSelectedId(knowledgeBase.id);
                      setError(null);
                      setNotice(null);
                    }}
                    disabled={deletingBaseId === knowledgeBase.id}
                  >
                    <BookOpen data-icon="inline-start" />
                    <span className="flex min-w-0 flex-1 flex-col">
                      <span className="truncate">{knowledgeBase.name}</span>
                      <span className="font-mono font-normal text-muted-foreground">
                        {documentCount(knowledgeBase)} document{documentCount(knowledgeBase) === 1 ? '' : 's'}
                      </span>
                    </span>
                    <ChevronRight data-icon="inline-end" />
                  </Button>
                ))}
              </div>
            )}
          </CardContent>
          <CardFooter>
            <form className="w-full" onSubmit={createKnowledgeBase}>
              <FieldGroup>
                <Field>
                  <FieldLabel htmlFor="knowledge-base-name">New knowledge base</FieldLabel>
                  <Input
                    id="knowledge-base-name"
                    value={newName}
                    onChange={(event) => setNewName(event.target.value)}
                    placeholder="e.g. Product notes"
                    maxLength={120}
                    required
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="knowledge-base-description" className="sr-only">
                    Description
                  </FieldLabel>
                  <Textarea
                    id="knowledge-base-description"
                    value={newDescription}
                    onChange={(event) => setNewDescription(event.target.value)}
                    placeholder="Optional description"
                    maxLength={300}
                    rows={2}
                  />
                </Field>
                <Button type="submit" disabled={creating || !newName.trim()}>
                  {creating ? <Spinner data-icon="inline-start" /> : <FolderPlus data-icon="inline-start" />}
                  {creating ? 'Creating…' : 'Create knowledge base'}
                </Button>
              </FieldGroup>
            </form>
          </CardFooter>
        </Card>

        <Card aria-labelledby={selectedBase ? 'knowledge-base-detail-title' : undefined}>
          {!selectedBase ? (
            <CardContent>
              <Empty>
                <EmptyHeader>
                  <EmptyMedia variant="icon">
                    <BookOpen />
                  </EmptyMedia>
                  <EmptyTitle>Select a knowledge base</EmptyTitle>
                  <EmptyDescription>
                    Create a library or choose one from the list to manage its source documents.
                  </EmptyDescription>
                </EmptyHeader>
              </Empty>
            </CardContent>
          ) : (
            <>
              <CardHeader>
                <CardTitle id="knowledge-base-detail-title">{selectedBase.name}</CardTitle>
                <CardDescription>{selectedBase.description || 'Source documents for grounded answers.'}</CardDescription>
                <CardAction className="flex flex-wrap gap-2">
                  <Button
                    variant={attachedKnowledgeBaseIds.includes(selectedBase.id) ? 'secondary' : 'outline'}
                    size="sm"
                    onClick={() => void toggleSessionAttachment(selectedBase)}
                    disabled={!sessionId || savingAttachment}
                    title={sessionId ? undefined : 'Open a chat first'}
                  >
                    {savingAttachment ? <Spinner data-icon="inline-start" /> : <BookOpen data-icon="inline-start" />}
                    {attachedKnowledgeBaseIds.includes(selectedBase.id) ? 'Remove from chat' : 'Use in this chat'}
                  </Button>
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => setConfirming({ kind: 'base', base: selectedBase })}
                    disabled={deletingBaseId === selectedBase.id}
                  >
                    {deletingBaseId === selectedBase.id ? <Spinner data-icon="inline-start" /> : <Trash2 data-icon="inline-start" />}
                    Delete
                  </Button>
                </CardAction>
              </CardHeader>

              <CardContent className="flex flex-col gap-4">
                <FieldGroup>
                  <Field data-invalid={fileError ? true : undefined}>
                    <FieldLabel htmlFor="knowledge-document-file">Add a source document</FieldLabel>
                    <div className="flex flex-wrap items-center gap-2">
                      <Input
                        ref={fileInputRef}
                        id="knowledge-document-file"
                        className="min-w-0 flex-1"
                        type="file"
                        accept=".txt,.md,.docx,.pdf,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                        onChange={selectFile}
                        disabled={uploading}
                        aria-invalid={fileError ? true : undefined}
                      />
                      <Button onClick={() => void uploadDocument()} disabled={!selectedFile || uploading}>
                        {uploading ? <Spinner data-icon="inline-start" /> : <Upload data-icon="inline-start" />}
                        {uploading ? 'Uploading…' : 'Upload document'}
                      </Button>
                    </div>
                    {fileError ? (
                      <FieldError>{fileError}</FieldError>
                    ) : (
                      <FieldDescription>Only text can be indexed. Scanned or image-only PDFs are rejected.</FieldDescription>
                    )}
                  </Field>
                </FieldGroup>

                <Separator />

                <div className="flex items-center justify-between gap-3">
                  <h4 className="text-sm font-medium">Documents</h4>
                  <span className="font-mono text-xs text-muted-foreground"><Num value={documents.length} /> total</span>
                </div>

                {documentsState === 'loading' ? (
                  <LoadingState label="Loading documents" />
                ) : documentsState === 'error' ? null : documents.length === 0 ? (
                  <Empty className="border">
                    <EmptyHeader>
                      <EmptyMedia variant="icon">
                        <FileText />
                      </EmptyMedia>
                      <EmptyTitle>This library is empty</EmptyTitle>
                      <EmptyDescription>Upload a text document to make it available as evidence.</EmptyDescription>
                    </EmptyHeader>
                  </Empty>
                ) : (
                  <ul className="flex flex-col">
                    {documents.map((document) => (
                      <li key={document.id} className="flex items-center gap-3 border-t py-2.5 first:border-t-0">
                        <FileText className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                        <div className="flex min-w-0 flex-1 flex-col">
                          <span className="truncate text-sm font-medium" title={document.filename}>
                            {document.filename}
                          </span>
                          <span className="font-mono text-xs text-muted-foreground">{documentMeta(document)}</span>
                          {document.error && <span className="text-xs text-destructive">{document.error}</span>}
                        </div>
                        <Badge variant={statusVariant(document.status)} className="font-mono">
                          {formatStatus(document.status)}
                        </Badge>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          onClick={() => setConfirming({ kind: 'document', document })}
                          title={`Delete ${document.filename}`}
                          aria-label={`Delete ${document.filename}`}
                        >
                          <Trash2 />
                        </Button>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </>
          )}
        </Card>
      </div>

      <AlertDialog open={confirming !== null} onOpenChange={(open) => !open && setConfirming(null)}>
        <AlertDialogContent size="sm">
          <AlertDialogHeader>
            <AlertDialogTitle>
              Delete “{confirming?.kind === 'base' ? confirming.base.name : confirming?.document.filename}”?
            </AlertDialogTitle>
            <AlertDialogDescription>
              {confirming?.kind === 'base'
                ? 'Its documents are deleted with it, and it is removed from retrieval.'
                : 'The document is removed from this knowledge base.'}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                const target = confirming;
                setConfirming(null);
                if (target?.kind === 'base') void deleteKnowledgeBase(target.base);
                if (target?.kind === 'document') void deleteDocument(target.document);
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function statusVariant(status: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (status === 'failed') return 'destructive';
  if (status === 'ready') return 'outline';
  return 'secondary';
}

function normalizeKnowledgeBases(response: KnowledgeBaseListResponse): KnowledgeBase[] {
  const value = response as unknown as { knowledge_bases?: unknown; items?: unknown };
  const candidates = Array.isArray(value.knowledge_bases) ? value.knowledge_bases : value.items;
  return Array.isArray(candidates) ? candidates.map(normalizeKnowledgeBase) : [];
}

function normalizeKnowledgeBase(value: unknown): KnowledgeBase {
  const record = isRecord(value) && isRecord(value.knowledge_base) ? value.knowledge_base : value;
  const source = isRecord(record) ? record : {};
  return {
    id: String(source.id ?? ''),
    name: String(source.name ?? 'Untitled knowledge base'),
    description: typeof source.description === 'string' ? source.description : null,
    document_count: typeof source.document_count === 'number' ? source.document_count : undefined,
    created_at: typeof source.created_at === 'string' ? source.created_at : null,
    updated_at: typeof source.updated_at === 'string' ? source.updated_at : null,
  };
}

function normalizeDocuments(response: KnowledgeBaseDocumentsResponse): KnowledgeBaseDocument[] {
  const value = response as unknown as { documents?: unknown; items?: unknown };
  const candidates = Array.isArray(value.documents) ? value.documents : value.items;
  return Array.isArray(candidates) ? candidates.map(normalizeDocument) : [];
}

function normalizeDocument(value: unknown): KnowledgeBaseDocument {
  const record = isRecord(value) && isRecord(value.document) ? value.document : value;
  const source = isRecord(record) ? record : {};
  return {
    id: String(source.id ?? ''),
    knowledge_base_id: typeof source.knowledge_base_id === 'string' ? source.knowledge_base_id : undefined,
    filename: String(source.filename ?? 'Unnamed document'),
    mime_type: typeof source.mime_type === 'string' ? source.mime_type : null,
    size_bytes: typeof source.size_bytes === 'number' ? source.size_bytes : null,
    status: String(source.status ?? 'uploaded'),
    page_count: typeof source.page_count === 'number' ? source.page_count : null,
    character_count: typeof source.character_count === 'number' ? source.character_count : null,
    error: typeof source.error === 'string' ? source.error : null,
    created_at: typeof source.created_at === 'string' ? source.created_at : null,
    processed_at: typeof source.processed_at === 'string' ? source.processed_at : null,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message.replace(/^API \d+:\s*/, '') : fallback;
}

function getExtension(filename: string): string {
  const dot = filename.lastIndexOf('.');
  return dot >= 0 ? filename.slice(dot).toLowerCase() : '';
}

function documentCount(knowledgeBase: KnowledgeBase): number {
  return typeof knowledgeBase.document_count === 'number' ? knowledgeBase.document_count : 0;
}

function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes)) return 'Size unknown';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function documentMeta(document: KnowledgeBaseDocument): string {
  const parts = [formatBytes(document.size_bytes)];
  if (document.page_count) parts.push(`${document.page_count} page${document.page_count === 1 ? '' : 's'}`);
  if (document.character_count) parts.push(`${document.character_count.toLocaleString()} chars`);
  return parts.join(' · ');
}

function formatStatus(status: string): string {
  return status.replaceAll('_', ' ');
}
