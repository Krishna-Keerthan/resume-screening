# ATS Platform — AI Resume Intelligence Frontend

Next.js 14 frontend for the AI Resume Intelligence Platform.

## Quick Start

```bash
# 1. Install dependencies
npm install

# 2. Configure backend URL (edit .env.local)
NEXT_PUBLIC_API_URL=http://localhost:5000   # ← point to your Flask backend

# 3. Run development server
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

## Tech Stack

- **Next.js 14** App Router + TypeScript
- **TanStack Query v5** — all data fetching (no useEffect for API calls)
- **Zustand** with persist — auth store (key: `ats-auth-v1`)
- **React Hook Form + Zod** — all forms + validation
- **Recharts** — pipeline funnel, score distribution, skills demand charts
- **Framer Motion** — score gauge animation, stage transitions
- **react-dropzone** — resume upload with client-side validation
- **sonner** — toast notifications
- **Tailwind CSS** — custom dark theme

## Project Structure

```
app/
  login/                    → Role selector + email search/create flow
  (candidate)/
    dashboard/              → Job matches + recent applications + resume status
    jobs/                   → Job board with filters + Preview Match
    jobs/[id]/              → Full job detail + score preview + apply form
    resumes/                → Resume list + upload
    resumes/upload/         → Dedicated upload page with drag-drop
    applications/           → Applications list with stage filter tabs
    applications/[id]/      → Full ATS score card + skill gap breakdown
    profile/                → Edit profile + preferred roles/locations
  (recruiter)/
    dashboard/              → KPIs + pipeline funnel + score pie + top jobs
    jobs/                   → Job postings with status filters + AI enhance
    jobs/new/               → Create job form + post-create AI enhance offer
    jobs/[id]/              → Job detail + edit form + AI enhance panel
    jobs/[id]/applicants/   → Kanban board + right drawer + stage modal
    analytics/              → Full analytics with 5 separate API calls

lib/
  api/client.ts             → All 50 API endpoints + axios interceptor
  types/index.ts            → All TypeScript interfaces
  store/authStore.ts        → Zustand auth (no JWT — email identity only)
  utils/scoreColors.ts      → Score color utility (never hardcode colors)
  utils/formatters.ts       → Date, salary, score formatters

components/
  shared/AtsScoreCard.tsx   → Score gauge (Framer Motion) + tips accordion
  shared/index.tsx          → PaginationBar, EmptyState, SkillBadge, ScoreBadge, StageBadge, Skeleton
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:5000` | Flask backend base URL |
| `NEXT_PUBLIC_AUTH_STORAGE_KEY` | `ats-auth-v1` | localStorage key for auth |

## Auth Flow

No passwords or JWT. Pure identity selection:
1. Pick role (Candidate / Recruiter)
2. Enter email → `GET /candidates/?search=email` or `GET /recruiters/?search=email`
3. Found → `setAuth(role, id, name)` → redirect to dashboard
4. Not found → show create form → `POST /candidates/` or `POST /recruiters/` → `setAuth`

## Key API Notes

- All 50 endpoints under `/api/v1`
- Response envelope: `{ success, message, data, meta? }`
- File upload field name MUST be `"file"` — backend checks `request.files["file"]`
- Score preview (`GET /resumes/<id>/score-preview?job_id=<id>`) does NOT save to DB (`saved: false`)
- Analytics endpoints ALL require `?recruiter_id=<id>` param
- `DELETE /applications/<id>` sets stage=withdrawn (not hard delete)
- Terminal stages (hired/rejected/withdrawn) cannot be advanced
