# Contributing

PRs are open. If something's broken, open an issue. If you want to add a feature, open an issue first so we're not building the same thing in parallel.

## Setup

**Prerequisites:** Python 3.10+, Node 18+, Docker

```bash
git clone https://github.com/verdictlens/verdictlens.git
cd verdictlens
cp .env.example .env

# Start ClickHouse + Redis (needed for backend)
docker compose up -d clickhouse redis
```

### SDK

```bash
cd sdk
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

You'll also need PostgreSQL running locally, or swap `VERDICTLENS_DATABASE_URL` to point at the bundled container.

### Frontend

```bash
cd frontend
npm install
npm run dev      # runs at http://localhost:5173, proxies /api → localhost:8000
```

---

## Project layout

```
verdictlens/
├── sdk/          # Python SDK (pip install verdictlens)
├── backend/      # FastAPI server
│   └── app/
│       ├── blame_engine.py   ← the interesting bit
│       ├── replay.py
│       ├── routes.py
│       └── clickhouse.py
├── frontend/     # React dashboard
│   └── src/
│       └── pages/
├── examples/     # Demo scripts
└── docker-compose.yml
```

The blame engine (`backend/app/blame_engine.py`) is the core of the project. If you're touching that, write tests — it's easy to accidentally break the role classification logic.

---

## Making a PR

1. Fork and branch off `main`:
   ```bash
   git checkout -b feat/my-thing
   ```

2. Keep the change focused. A PR that does one thing is much easier to review than one that does five.

3. Run the tests before opening:
   ```bash
   cd sdk && pytest
   cd backend && pytest
   cd frontend && npm run build
   ```

4. Write a clear description of what changed and why — not just what the diff says.

---

## Code style

**Python:** PEP 8, type hints on public functions, docstrings on anything non-obvious.

**TypeScript:** Strict mode must pass (`tsc -b`). Functional components, Tailwind for styles.

---

## Things worth contributing

- New framework integrations (Haystack, DSPy, Smolagents, etc.)
- More LLM provider patchers or cost tables
- Dashboard improvements — better filters, export, visualizations
- More evaluation scorers
- Tests — especially frontend tests, we're light there

Check [Issues](../../issues) for open bugs and feature requests. `good first issue` label is the best place to start.

---

## Bugs

Open an issue with what you expected, what happened, steps to reproduce, and your environment (OS, Python version, Docker version). The more specific the better.

---

## License

By contributing, you agree your work will be licensed under [Apache 2.0](LICENSE).
