# MIRA React memory command center frontend

This represents the new custom React single-page frontend application for the **Memory-Integrated Reasoning Architecture (MIRA)**. It acts as a premium, modern development experience built with Vite, React, TypeScript, and D3.js.

## Key features
- **Aesthetic fidelity**: Replays the aesthetic look and feel of the primary project workspace in light/dark formats.
- **Dynamic 3D memory graph**: An interactive, force-directed node-link graph mapping entities, observations, reflections, communities, and atomic facts.
- **Two-speed control toggle**: Instantly swap between mocked demonstration data schemas and live execution against the FastAPI application backend.
- **Leiden Community clusters**: Highlights graph communities, reflecting temporal and topological structures.
- **Durable evaluation dashboard**: Live scoring dashboard for 10 core behaviors backed by sample test data.

## Getting started

### Prerequisites
- Node.js (v18+)
- npm

### Installation
From the package root, locate the `frontend` folder:
```bash
cd frontend
npm install
```

### Running locally (development)
To spin up the local development web server:
```bash
npm run dev
```

By default, this launches on [http://localhost:5173](http://localhost:5173).

### Environment configuration
The configuration file `.env` controls the destination of backend routing calls:
```env
VITE_API_URL=http://localhost:8000
```
Change this variable to point to any custom deployed endpoint or production container service.

### Running with Docker Compose
From the repository root:

```bash
docker compose up api worker frontend
```

The frontend is served at [http://localhost:5173](http://localhost:5173), and the FastAPI backend
is served at [http://localhost:8000](http://localhost:8000). The Compose setup keeps the API and
worker as separate services so queued memory work remains visible and restartable.

## Application structure
```
frontend/
├── src/
│   ├── api/             # API client targeting MIRA FastAPI backend
│   ├── components/      # Views: Chat, Graph, Leiden Clusters, Timeline, Results
│   ├── context/         # Central Application State Providers
│   ├── data/            # Static / Mocked demonstration schemas
│   ├── App.tsx          # Router and global layouts
│   ├── main.tsx         # Node attachment and React setup
│   └── index.css        # Premium custom stylesheet with variables and styling
```
