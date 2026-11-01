# AI Resume Screening & Job Recommendation Platform

An applicant tracking system (ATS) that parses résumés, scores them against job postings with a hybrid keyword + semantic model, and explains the result to both candidates and recruiters.

> **Status:** deployed (backend on Render, frontend on Vercel). Ongoing work is a hardening and refactoring pass; see `docs/STATUS.md`.

<!-- Add screenshots here -->
| Candidate dashboard | Recruiter pipeline | Analytics |
|---|---|---|
| _screenshot_ | _screenshot_ | _screenshot_ |

## Features

**Candidates**
- Upload a résumé (PDF/DOCX) and have it parsed into structured sections and skills
- Browse jobs and get ranked recommendations based on the active résumé
- See an ATS score with a per-component breakdown and improvement tips
- Apply to jobs and track application status

**Recruiters**
- Post jobs (with smart parsing of the job description into skills and requirements)
- Rank applicants per job with score explanations
- Move candidates through hiring stages
- Analytics: pipeline funnel, score distribution, in-demand skills

**Platform**
- JWT auth with a short-lived access token and an HttpOnly refresh cookie, with rotation
- Role-based access (candidate / recruiter) with ownership checks on every private route
- Rate limiting, private file storage (no public URLs)

## How scoring works

Each résumé–job pair gets a score from 0 to 1, a weighted blend of four signals:

| Signal | Weight | What it measures |
|---|---|---|
| Semantic similarity | 0.40 | MiniLM sentence embeddings, cosine similarity between résumé and job |
| Keyword match | 0.35 | BM25 over job keywords and a skill taxonomy |
| Experience | 0.15 | Years and seniority against the job's requirement |
| Section quality | 0.10 | Completeness and quality of résumé sections |

Scores map to labels (Excellent ≥ 0.80, Good ≥ 0.65, Fair ≥ 0.50, otherwise Poor). Weights and thresholds are configurable in `backend/config/settings.py`.

An optional LLM step (Groq, Llama 3.1) writes summaries and tips. If the LLM call fails, the response falls back to rule-based text and is not marked as LLM-enhanced.

## Architecture

```
frontend/ (Next.js 16)  ──►  Next.js proxy  ──►  backend/ (Flask 3)  ──►  PostgreSQL
                                                    │
                                                    ├── Supabase Storage / local disk (résumé files)
                                                    └── Groq API (summaries, tips)
```

The backend is layered, with each layer depending only on the ones below it:

```
api/  →  services/  →  repositories/  →  models/
```

- **api/** parses input, checks auth and ownership, calls one service, returns JSON
- **services/** holds business logic: parsing, scoring, ranking, recommendations
- **repositories/** holds database queries only
- **models/** holds SQLAlchemy models; schema changes go through Alembic

Storage sits behind a single interface with Supabase and local-disk implementations, picked in one factory.

## Tech stack

| Area | Technology |
|---|---|
| Backend | Flask 3, SQLAlchemy 2, Alembic, Gunicorn |
| Database | PostgreSQL (SQLite for tests) |
| ML / NLP | sentence-transformers (MiniLM), BM25, PyTorch (CPU) |
| LLM | Groq (Llama 3.1) |
| Storage | Supabase Storage or local disk |
| Frontend | Next.js 16 (App Router), TypeScript, TanStack Query, Zustand, Tailwind CSS, Recharts |
| Infra | Docker Compose, Render (backend), Vercel (frontend) |
| Tests | pytest (about 1,100 tests, run on both SQLite and Postgres) |

## Project structure

```
backend/    Flask API, services, repositories, models, migrations, tests
frontend/   Next.js app (candidate and recruiter areas)
docs/       Deployment notes, stack decisions, status
render.yaml Render blueprint
docker-compose.yml
```

## Running locally

The backend lock file targets Linux, so run the backend through Docker or WSL rather than native Windows.

### With Docker

```bash
# 1. Configure the backend
cp backend/.env.example backend/.env
# set SECRET_KEY (any 32+ character string for local use); see the file for other options

# 2. Start Postgres and the Flask API
docker compose up --build

# 3. Start the frontend with hot reload (in another terminal)
docker compose --profile dev up nextjs-dev
```

- API: http://localhost:5000
- Frontend: http://localhost:3000

The first start downloads the embedding model, so it takes a while.

### Without Docker (WSL or Linux)

```bash
# Backend
cd backend
pip install -r requirements.txt
cp .env.example .env        # set SECRET_KEY and DATABASE_URL
alembic upgrade head
python run.py

# Frontend
cd frontend
npm install
echo "API_PROXY_TARGET=http://localhost:5000" > .env.local
npm run dev
```

### Seed data and tests

```bash
cd backend
pip install -r requirements-dev.txt
python seed.py     # sample users, jobs and résumés
pytest -q          # full test suite
```

Frontend checks: `npx tsc --noEmit`, `npm run lint`, `npm run build`.

## Deployment

The repo includes a Render blueprint (`render.yaml`) for the backend and is set up for Vercel for the frontend. Details and measurements are in `docs/deploy_phase3.md`.

## License

MIT License.
