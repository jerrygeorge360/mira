# MIRA Knowledge Bases

Knowledge Bases keep uploaded source documents separate from MIRA's durable human memory. SQLite owns workspace-scoped metadata and chunks, the private S3 bucket owns originals, and Chroma stores rebuildable document-chunk embeddings.

## Configuration

Set these values in the deployment environment:

- `AWS_REGION=eu-north-1`
- `MIRA_DOCUMENTS_S3_BUCKET=mira-knowledge-documents-345736954255-eun1`

The application uses boto3's default credential chain. No AWS credentials belong in the repository. Coolify must provide an AWS role or short-lived environment credentials with least-privilege access to this bucket. The S3 bucket should remain private, block public access, and use server-side encryption.

Default limits are configurable with `MIRA_DOCUMENT_*` variables:

- 10 MB per original
- 100 PDF pages
- 200,000 extracted characters
- 1,200-character chunks with 200-character overlap

Supported types are UTF-8 `.txt`, Markdown `.md`, `.docx`, and text-based `.pdf`. OCR, scanned/image-only PDFs, images, audio, video, spreadsheets, presentations, and archives are intentionally unsupported.

## Storage and lifecycle

Originals use the key format:

`mira/workspaces/<workspace_id>/knowledge-bases/<kb_id>/documents/<document_id>/<safe_filename>`

Documents move through `uploaded`, `processing`, `ready`, `failed`, and `deleted`. Uploads are extracted and indexed synchronously in the MVP. Deleting a document removes its chunks from retrieval, removes its Chroma pointer and S3 object, and keeps the SQLite document row as a deleted audit record. Knowledge Base and workspace deletion apply the same cleanup boundary.

## API

- `POST /knowledge-bases`
- `GET /knowledge-bases`
- `GET /knowledge-bases/{kb_id}`
- `DELETE /knowledge-bases/{kb_id}`
- `POST /knowledge-bases/{kb_id}/documents` with multipart field `file`
- `GET /knowledge-bases/{kb_id}/documents`
- `GET /documents/{document_id}`
- `DELETE /documents/{document_id}`

Every operation is resolved through the authenticated workspace. Document evidence includes the Knowledge Base, document, chunk, page range, and relevance score in the existing retrieval trace; it does not create MIRA memory-lifecycle state.
