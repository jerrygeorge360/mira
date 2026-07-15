# Checkpoint — Auth + Product UI (for the next session / Codex)

Cold-start handoff. Read this first. Branch: **`docs-readme-evaluation-story`** (has everything:
the eval/benchmark work, Claude's UI wiring, and Codex's auth + Docker).

---

## 0. The headline: your "next plan" is already done

You planned to add **GitHub OAuth** and a **demo account (no OAuth)**. **Codex already built both,
end-to-end** — backend, workspace multi-tenancy, *and* a frontend auth page. Do **not** rebuild it.
The remaining work is **verifying / finishing the integration and committing the frontend**, not
implementing auth from scratch. Details below.

---

## 1. What Codex built (committed)

Commits on top of Claude's work: `515c543` (dockerize), `f31e026` (workspace auth + product
frontend), `5083e97` (CI align), `1a43cfd`/`68c57d3` (docs).

### Auth backend — `api/auth.py` + `api/routes/auth.py`
- **GitHub OAuth**: `GET /auth/github/start` → GitHub authorize; `GET /auth/github/callback` →
  exchanges the code (`GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET`), provisions a user + workspace,
  sets a server-session cookie (`mira_session`) and a CSRF cookie (`mira_csrf`).
- **Demo account (no OAuth)**: `POST /auth/demo` → `core.demo.issue_demo_workspace`: an isolated,
  **expiring** demo workspace with rate limits (`MIRA_DEMO_TTL_MINUTES` 60, `MIRA_DEMO_MAX_ACTIVE` 10,
  `MIRA_DEMO_MAX_PER_WINDOW` 3, `MIRA_DEMO_ISSUANCE_WINDOW_MINUTES` 60).
- `GET /auth/me` (current identity + `auth_mode`), `POST /auth/logout`.
- **`MIRA_AUTH_MODE`**: `github` (default, real OAuth) | `development` (binds a fixed dev workspace,
  no login — for local work).

### Multi-tenant workspace model — `core/db/schema.py`, `core/db/repositories.py`
- New tables: `users`, `workspaces`, `workspace_members`, `auth_sessions`, `oauth_states`,
  `demo_issuances`.
- **Memory is now workspace-isolated.** `_WORKSPACE_OWNED_TABLES` lists the scoped tables;
  `bind_workspace(context)` returns a repository whose reads/writes are filtered to that workspace.
- Every data route follows one pattern:
  ```python
  def handler(..., auth: WorkspaceAuth):        # Depends(require_authenticated_workspace)
      require_csrf(request, auth)                # on mutating routes
      repo = bind_workspace(auth.context)        # workspace-scoped repository
      ... repo.<method>() ...
  ```
  `WorkspaceAuth = Annotated[AuthenticatedWorkspace, Depends(require_authenticated_workspace)]`.
- **Confirmed wired**: `chat`, `retrieval`, `sessions` (incl. Claude's new `/sessions` and
  `/sessions/{id}/messages`), `memory`. So all data is auth-gated + workspace-scoped.

### Frontend auth (uncommitted, in the `frontend/` working tree)
- `components/AuthPage.tsx` — GitHub-login + demo buttons.
- `App.tsx` gates the app: `if (!authReady) return <AuthPage/>; if (!authUser) return <AuthPage/>`.
- `api/client.ts` — `credentials: 'include'` (sends the session cookie on every call),
  `githubAuthUrl()`, `authMe()`, demo, `logout()`, and an `AuthResponse` type
  (`auth_mode: 'github' | 'demo' | 'development'`).

### Config — `.env` already has `MIRA_AUTH_MODE`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`.
Also: Docker for api/worker/frontend (`515c543`).

---

## 2. What Claude built (this session)

- **Eval/benchmark**: local eval 12/13, ablation full_system 7/7 (every layer load-bearing),
  benchmark parallel + isolation + DeepSeek pricing, hybrid-routing hardening. All committed.
  See `docs/session-checkpoint.md`, `docs/evaluation-story.md`, `docs/paper-reconciliation.md`.
- **Product UI wiring (frontend, UNCOMMITTED)**: replaced mock data in all views with live API
  data + honest empty/offline states (no more fake "10/10"); real chat-history sidebar backed by
  the new `/sessions` + `/sessions/{id}/messages` endpoints; `useLiveData` hook; `ViewStatus`
  component. Streamlit chat got a real-agent toggle (`ui/app.py`, committed).

---

## 3. Integration state — what to VERIFY / FINISH

Auth is implemented; these are the loose ends to close before it's production-real:

1. **Commit the frontend.** `frontend/` is untracked (both Claude's live-data wiring *and* Codex's
   `AuthPage`/gating live there together). Build it and commit in the frontend project:
   `cd frontend && npm run build` (Claude did not get a final build confirmation — the Bash
   sandbox was flaky at the end; **run tsc/build first** and fix any type errors from the two
   parallel edit streams touching `App.tsx`, `Rail.tsx`, `ChatView.tsx`, `client.ts`,
   `context/AppContext.tsx`).
2. **End-to-end OAuth smoke test.** Register a GitHub OAuth app; set the callback to
   `{API}/auth/github/callback`; verify start→callback→cookie→`/auth/me` works and that a
   real workspace + memory isolation results.
3. **Demo flow.** `POST /auth/demo` → confirm the workspace expires and the rate limits trip.
4. **Cross-origin cookies.** Frontend (vite :5173) and API (:8000) are different origins →
   confirm CORS `allow_credentials=True` + the cookie `SameSite`/`Secure` settings let the
   `mira_session` cookie flow (this is the usual gotcha). Check `api/main.py` CORS config.
5. **CSRF.** `require_csrf` runs on mutating routes — confirm the frontend sends the `mira_csrf`
   value (header) on POSTs (chat, demo, logout).
6. **Local dev without GitHub.** Set `MIRA_AUTH_MODE=development` to bypass login and bind a fixed
   dev workspace — use this for UI work so you don't need OAuth every run.
7. **Tests.** Run the suite (`make test`); Codex added CI-alignment fixes. Check for auth tests
   under `tests/` and that the workspace-scoping didn't break eval/UI tests.

---

## 4. How to run it

```bash
# local UI work, no GitHub needed:
MIRA_AUTH_MODE=development make api            # terminal 1
make frontend-dev                              # terminal 2  (AuthPage will pass through in dev mode)

# real GitHub OAuth:
MIRA_AUTH_MODE=github make api                 # needs GITHUB_CLIENT_ID/SECRET + a registered OAuth app
# demo account: click "Try demo" in AuthPage, or POST /auth/demo
```

---

## 5. File map (where to look)

- Auth core: `api/auth.py` (session/CSRF/OAuth/workspace resolution), `api/routes/auth.py` (endpoints),
  `core/demo.py` (demo issuance).
- Workspace model: `core/db/schema.py` (tables), `core/db/repositories.py`
  (`bind_workspace`, `_WORKSPACE_OWNED_TABLES`, `require_active_workspace`, `WorkspaceContext`).
- Route pattern: any of `api/routes/{chat,sessions,memory,retrieval}.py`.
- Frontend auth: `frontend/src/components/AuthPage.tsx`, `frontend/src/App.tsx`,
  `frontend/src/api/client.ts`.
- Frontend data views (Claude): `frontend/src/api/useLiveData.ts`,
  `frontend/src/components/{ViewStatus,ReflectionsView,CommunitiesView,MemoryGraphView,WorkingSetView,RetrievalView,TimelineView,Rail,ChatView}.tsx`.

---

## 6. Bottom line for the next session

- **Auth (OAuth + demo + workspaces) is built and wired.** Don't rebuild it.
- **Do**: run `cd frontend && npm run build`, fix any type errors, commit the frontend; smoke-test
  the OAuth + demo flows; verify cross-origin cookies/CSRF; use `MIRA_AUTH_MODE=development` for UI work.
- Everything else (eval, ablation, benchmark, product UI data-wiring) is done and documented.
