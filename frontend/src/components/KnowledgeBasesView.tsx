import { useEffect, useMemo, useRef, useState } from 'react';
import type { ChangeEvent, FormEvent } from 'react';
import {
  AlertCircle,
  BookOpen,
  ChevronRight,
  FileText,
  FolderPlus,
  Info,
  LoaderCircle,
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

const MAX_FILE_BYTES = 10 * 1024 * 1024;
const MAX_FILE_LABEL = '10 MB';
const ACCEPTED_EXTENSIONS = ['.txt', '.md', '.docx', '.pdf'];

type LoadState = 'loading' | 'ready' | 'error';

export default function KnowledgeBasesView() {
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
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
    const confirmed = window.confirm(
      `Delete “${knowledgeBase.name}” and its documents? This removes it from retrieval.`,
    );
    if (!confirmed) return;
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
    const confirmed = window.confirm(`Delete “${document.filename}” from this knowledge base?`);
    if (!confirmed) return;
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
    <div className="knowledge-bases-view">
      <header className="knowledge-bases-header">
        <div>
          <div className="knowledge-bases-kicker"><BookOpen size={14} /> Source shelf</div>
          <h2>Knowledge Bases</h2>
          <p>Keep source documents close to the answers they support. Documents stay separate from MIRA’s personal memory.</p>
        </div>
        <div className="knowledge-bases-limit-note">TXT · MD · DOCX · text-based PDF<br />Up to {MAX_FILE_LABEL} per file · PDF up to 100 pages</div>
      </header>

      {(error || notice) && (
        <div className={`knowledge-bases-notice${notice && !error ? ' success' : ''}`} role="status" aria-live="polite">
          {error ? <AlertCircle size={15} /> : <Info size={15} />}
          <span>{error ?? notice}</span>
        </div>
      )}

      <div className="knowledge-bases-layout">
        <aside className="knowledge-bases-panel" aria-label="Knowledge base list">
          <div className="knowledge-bases-panel-head">
            <h3>Your libraries</h3>
            <span>{knowledgeBases.length}</span>
          </div>
          {basesState === 'loading' ? (
            <div className="knowledge-bases-loading">Loading libraries…</div>
          ) : knowledgeBases.length === 0 ? (
            <div className="knowledge-bases-empty">
              <FolderPlus size={22} />
              <strong>No knowledge bases yet</strong>
              <p>Create one below, then add a source document.</p>
            </div>
          ) : (
            <div className="knowledge-bases-list">
              {knowledgeBases.map((knowledgeBase) => (
                <button
                  key={knowledgeBase.id}
                  type="button"
                  className={`knowledge-base-card${selectedId === knowledgeBase.id ? ' active' : ''}`}
                  onClick={() => {
                    setSelectedId(knowledgeBase.id);
                    setError(null);
                    setNotice(null);
                  }}
                  disabled={deletingBaseId === knowledgeBase.id}
                >
                  <span className="knowledge-base-icon"><BookOpen size={15} /></span>
                  <span className="knowledge-base-card-copy">
                    <strong>{knowledgeBase.name}</strong>
                    <small>{documentCount(knowledgeBase)} document{documentCount(knowledgeBase) === 1 ? '' : 's'}</small>
                  </span>
                  <ChevronRight className="knowledge-base-chevron" size={15} />
                </button>
              ))}
            </div>
          )}
          <form className="knowledge-base-create" onSubmit={createKnowledgeBase}>
            <label htmlFor="knowledge-base-name">New knowledge base</label>
            <input
              id="knowledge-base-name"
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
              placeholder="e.g. Product notes"
              maxLength={120}
              required
            />
            <textarea
              value={newDescription}
              onChange={(event) => setNewDescription(event.target.value)}
              placeholder="Optional description"
              maxLength={300}
              rows={2}
            />
            <button className="knowledge-base-action primary" type="submit" disabled={creating || !newName.trim()}>
              {creating ? <LoaderCircle size={14} className="spin" /> : <FolderPlus size={14} />}
              {creating ? 'Creating…' : 'Create knowledge base'}
            </button>
          </form>
        </aside>

        <section className="knowledge-bases-panel knowledge-bases-main" aria-labelledby="knowledge-base-detail-title">
          {!selectedBase ? (
            <div className="knowledge-bases-empty">
              <BookOpen size={26} />
              <strong>Select a knowledge base</strong>
              <p>Create a library or choose one from the list to manage its source documents.</p>
            </div>
          ) : (
            <>
              <div className="knowledge-bases-main-head">
                <div>
                  <h3 id="knowledge-base-detail-title">{selectedBase.name}</h3>
                  <p>{selectedBase.description || 'Source documents for grounded answers.'}</p>
                </div>
                <div className="knowledge-bases-main-actions">
                  <button
                    className="knowledge-base-action danger"
                    type="button"
                    onClick={() => void deleteKnowledgeBase(selectedBase)}
                    disabled={deletingBaseId === selectedBase.id}
                  >
                    {deletingBaseId === selectedBase.id ? <LoaderCircle size={14} className="spin" /> : <Trash2 size={14} />}
                    Delete
                  </button>
                </div>
              </div>

              <div className="knowledge-bases-upload">
                <div className="knowledge-bases-upload-copy">
                  <strong>Add a source document</strong>
                  <p>Only text can be indexed. Scanned or image-only PDFs are rejected.</p>
                  <label className="knowledge-upload-label" htmlFor="knowledge-document-file">Choose a file</label>
                  <input
                    ref={fileInputRef}
                    id="knowledge-document-file"
                    className="knowledge-upload-file"
                    type="file"
                    accept=".txt,.md,.docx,.pdf,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    onChange={selectFile}
                    disabled={uploading}
                  />
                </div>
                <button className="knowledge-base-action primary" type="button" onClick={() => void uploadDocument()} disabled={!selectedFile || uploading}>
                  {uploading ? <LoaderCircle size={14} className="spin" /> : <Upload size={14} />}
                  {uploading ? 'Uploading…' : 'Upload document'}
                </button>
              </div>

              {fileError && (
                <div className="knowledge-bases-notice" role="alert">
                  <AlertCircle size={15} />
                  <span>{fileError}</span>
                </div>
              )}

              <div className="knowledge-documents">
                <div className="knowledge-documents-head">
                  <h4>Documents</h4>
                  <span>{documents.length} total</span>
                </div>
                {documentsState === 'loading' ? (
                  <div className="knowledge-bases-loading">Loading documents…</div>
                ) : documentsState === 'error' ? null : documents.length === 0 ? (
                  <div className="knowledge-bases-empty">
                    <FileText size={22} />
                    <strong>This library is empty</strong>
                    <p>Upload a text document to make it available as evidence.</p>
                  </div>
                ) : (
                  <div className="knowledge-document-list">
                    {documents.map((document) => (
                      <article className="knowledge-document-row" key={document.id}>
                        <span className="knowledge-document-icon"><FileText size={15} /></span>
                        <div className="knowledge-document-copy">
                          <strong title={document.filename}>{document.filename}</strong>
                          <small>{documentMeta(document)}</small>
                          {document.error && <small className="knowledge-document-error">{document.error}</small>}
                        </div>
                        <div className="knowledge-document-actions">
                          <span className={`knowledge-document-status ${statusClass(document.status)}`}>{formatStatus(document.status)}</span>
                          <button
                            className="knowledge-document-delete"
                            type="button"
                            onClick={() => void deleteDocument(document)}
                            title={`Delete ${document.filename}`}
                            aria-label={`Delete ${document.filename}`}
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </article>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
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

function statusClass(status: string): string {
  return ['ready', 'processing', 'uploaded', 'failed'].includes(status) ? status : '';
}
