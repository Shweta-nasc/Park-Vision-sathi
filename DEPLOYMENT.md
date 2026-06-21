# ParkVisionSaathi — Deployment Guide

Deploy the **frontend on Vercel** and the **backend on Render (or Railway)**.
This guide has every step, every value to paste, every port, and every
environment variable — with real values from this repo — so you don't have to
look anything up.

---

## 0. Architecture (what goes where)

```
   Browser
      │
      ▼
┌──────────────────────┐        HTTPS         ┌───────────────────────────┐
│  Vercel               │  ───────────────►   │  Render / Railway          │
│  React + Vite (static)│   VITE_API_BASE      │  FastAPI (uvicorn)         │
│  https://<app>.vercel │ ───────────────────►│  serves data/parkvision.db │
└──────────────────────┘                      └───────────────────────────┘
```

- **Frontend**: static build (`dist/`), served by Vercel's CDN. Talks to the
  backend over HTTPS using the `VITE_API_BASE` env var.
- **Backend**: FastAPI served by `uvicorn`. Reads the precomputed SQLite DB
  (`data/parkvision.db`). **No model training at runtime** — so the deploy is
  light and fast.

| Thing | Value |
|---|---|
| Backend framework | FastAPI |
| Backend ASGI entrypoint | `backend.app.main:app` |
| Backend start command | `uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT` |
| Backend local port | `8000` (host uses `$PORT` injected by Render/Railway) |
| Frontend framework | Vite + React + TypeScript |
| Frontend root dir | `frontend/` |
| Frontend build command | `npm run build` |
| Frontend output dir | `dist` |
| Node version | 20.x |
| Python version | 3.11.9 |

---

## 1. The one thing that will break the deploy: the database

`data/parkvision.db` is **153 MB** and is **gitignored** (see `.gitignore`).
That means:

1. It is **not** in your git repo, so a fresh clone on Render/Railway won't have it.
2. It is **larger than GitHub's 100 MB file limit**, so you can't just `git add` it.

The API reads from this DB at runtime, so it **must** be present on the server.
Pick **one** strategy below. **Strategy A is recommended.**

### Strategy A — Upload the DB as a GitHub Release asset, download it at build time (recommended)

1. On GitHub, go to your repo → **Releases** → **Draft a new release**.
2. Tag it `data-v1`, title it `Database`, and **drag `data/parkvision.db`** into
   the "Attach binaries" box. Publish.
3. Copy the asset's download URL. It looks like:
   `https://github.com/<you>/<repo>/releases/download/data-v1/parkvision.db`
4. You'll paste this URL into the backend's `DB_DOWNLOAD_URL` env var (Section 2).
   The build command downloads it automatically:
   ```bash
   curl -L -o data/parkvision.db "$DB_DOWNLOAD_URL"
   ```

> Release assets allow up to 2 GB, so 153 MB is fine, and this needs no Git LFS.

### Strategy B — Git LFS (alternative)

```bash
git lfs install
git lfs track "data/parkvision.db"
git add .gitattributes
git add -f data/parkvision.db        # -f overrides .gitignore
git commit -m "Track DB with Git LFS"
git push
```
Then in `.gitignore` remove the `data/parkvision.db` line, or keep the `-f`.
Render and Railway both support LFS checkout. GitHub free LFS = 1 GB storage /
1 GB monthly bandwidth (enough for a demo).

### Strategy C — Rebuild the DB on the server (slowest, not recommended)

Requires committing the raw CSV (also gitignored, large) and installing the full
ML stack to run `python run_pipeline.py` on deploy. Slow and fragile on free
tiers. Avoid unless A and B are impossible.

---

## 2. Deploy the BACKEND on Render

### 2.1 Prerequisites
- Code pushed to GitHub (the app code; the DB comes from Section 1).
- The DB download URL from Strategy A (or LFS set up via Strategy B).

### 2.2 Files this repo already provides for you
- `requirements-deploy.txt` — slim runtime deps (fastapi, uvicorn, pydantic, python-dotenv). Use this, **not** the root `requirements.txt` (which has heavy ML libs only needed for the offline pipeline).
- `Procfile` — `web: uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT`
- `render.yaml` — a ready Render Blueprint.

### 2.3 Option 1 — Blueprint (fastest)
1. Render Dashboard → **New +** → **Blueprint**.
2. Select your repo. Render reads `render.yaml`.
3. When prompted for env vars, set:
   - `DB_DOWNLOAD_URL` = your GitHub Release asset URL (Strategy A).
   - `GEMINI_API_KEY` = leave blank (optional — `/explain` works without it).
4. **Apply** → wait for build + deploy.

### 2.4 Option 2 — Manual Web Service
1. Render → **New +** → **Web Service** → connect repo.
2. Fill the form exactly:

   | Field | Value |
   |---|---|
   | **Language / Runtime** | `Python 3` |
   | **Region** | `Singapore` (closest to India) |
   | **Branch** | `main` (or your branch) |
   | **Root Directory** | *(leave blank — repo root)* |
   | **Build Command** | `pip install -r requirements-deploy.txt && mkdir -p data && curl -L -o data/parkvision.db "$DB_DOWNLOAD_URL"` |
   | **Start Command** | `uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT` |
   | **Instance Type** | `Free` |
   | **Health Check Path** | `/health` |

3. **Environment variables** (Advanced → Add Environment Variable):

   | Key | Value | Required |
   |---|---|---|
   | `PYTHON_VERSION` | `3.11.9` | Yes |
   | `DB_DOWNLOAD_URL` | your GitHub Release URL for `parkvision.db` | Yes (Strategy A) |
   | `GEMINI_API_KEY` | *(blank)* | No — `/explain` falls back to DB-driven text |

   > Do **not** set `PORT` yourself — Render injects it. The start command reads `$PORT`.

4. **Create Web Service**. First build takes ~2–4 min (mostly the 153 MB DB download).

### 2.5 Verify the backend
Your backend URL will be like `https://parkvision-api.onrender.com`. Test:
```bash
curl https://parkvision-api.onrender.com/health
# → {"status":"ok","tables":{...}}

curl https://parkvision-api.onrender.com/stations | head -c 200
# → [{"name":"Upparpet","zone_count":9,...}]
```
If `/health` shows tables as `true` and `/stations` returns 54 stations, the DB
loaded correctly. **Copy this backend URL — you need it for the frontend.**

> Free Render services sleep after 15 min idle and cold-start in ~30–50 s. For a
> live demo, hit `/health` a minute before presenting to wake it.

---

## 2-ALT. Deploy the BACKEND on Railway (instead of Render)

1. [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**.
2. Railway auto-detects Python via Nixpacks and uses the `Procfile`.
3. **Settings → Variables**:

   | Key | Value |
   |---|---|
   | `NIXPACKS_PYTHON_VERSION` | `3.11` |
   | `DB_DOWNLOAD_URL` | your GitHub Release URL for `parkvision.db` |
   | `GEMINI_API_KEY` | *(blank, optional)* |

4. **Settings → Build → Custom Build Command**:
   ```
   pip install -r requirements-deploy.txt && mkdir -p data && curl -L -o data/parkvision.db "$DB_DOWNLOAD_URL"
   ```
5. **Settings → Deploy → Custom Start Command** (if not using Procfile):
   ```
   uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT
   ```
6. **Settings → Networking → Generate Domain** to get a public HTTPS URL.
   Railway injects `$PORT` automatically — the start command already uses it.

---

## 3. Deploy the FRONTEND on Vercel

The repo already includes `frontend/vercel.json` (framework, build, SPA rewrites).

### 3.1 Steps
1. [vercel.com](https://vercel.com) → **Add New** → **Project** → import your repo.
2. Configure:

   | Field | Value |
   |---|---|
   | **Framework Preset** | `Vite` |
   | **Root Directory** | `frontend` |
   | **Build Command** | `npm run build` (default) |
   | **Output Directory** | `dist` (default) |
   | **Install Command** | `npm install` (default) |
   | **Node.js Version** | `20.x` (Project Settings → General) |

3. **Environment Variables** — add these (Settings → Environment Variables),
   for the **Production** (and Preview) environment:

   | Key | Value | Notes |
   |---|---|---|
   | `VITE_API_BASE` | `https://parkvision-api.onrender.com` | **Your backend URL from Section 2.5. No trailing slash. No `/api`.** |
   | `VITE_MAPPLS_KEY` | `5ce9c86c5b8c3a5cda1c9055fdde17f8` | Mappls map SDK key (from `frontend/.env`) |

   > `VITE_*` vars are baked in at **build time**. If you change `VITE_API_BASE`
   > later, you must **redeploy** for it to take effect.

4. **Deploy**. Your site goes live at `https://<project>.vercel.app`.

### 3.2 Verify the frontend
Open `https://<project>.vercel.app`:
- Station list loads (proves it reached the backend).
- Select a station → map renders, heatmap shows, layer toggle works.

If the station list fails, open the browser console — a CORS or wrong
`VITE_API_BASE` error will show there. See Troubleshooting.

---

## 4. Connect the two (CORS)

The backend currently allows all origins (`backend/app/main.py`):
```python
app.add_middleware(CORSMiddleware, allow_origins=["*"], ...)
```
So it works with any Vercel URL out of the box — **no change needed for the demo.**

**To lock it down (optional, recommended for anything beyond a demo):** edit
`backend/app/main.py` and replace `["*"]` with your Vercel domain:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://<your-project>.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```
Then redeploy the backend.

---

## 5. Complete environment variable reference

### Backend (Render / Railway)
| Key | Real value to use | Required | Purpose |
|---|---|---|---|
| `PORT` | *(auto-injected — do not set)* | — | Port uvicorn binds to |
| `PYTHON_VERSION` (Render) / `NIXPACKS_PYTHON_VERSION` (Railway) | `3.11.9` / `3.11` | Yes | Pin Python |
| `DB_DOWNLOAD_URL` | `https://github.com/<you>/<repo>/releases/download/data-v1/parkvision.db` | Yes (Strategy A) | Where build fetches the DB |
| `GEMINI_API_KEY` | *(blank)* | No | LLM explanations; falls back to DB text if unset |

### Frontend (Vercel)
| Key | Real value to use | Required | Purpose |
|---|---|---|---|
| `VITE_API_BASE` | `https://parkvision-api.onrender.com` | Yes | Backend base URL (no trailing slash, no `/api`) |
| `VITE_MAPPLS_KEY` | `5ce9c86c5b8c3a5cda1c9055fdde17f8` | Yes | Mappls map SDK key |

---

## 6. Pre-flight commands (run locally before deploying)

```bash
# Backend imports cleanly with ONLY the slim deps
pip install -r requirements-deploy.txt
python -c "from backend.app.main import app; print('backend OK')"

# Frontend builds exactly as Vercel will build it
cd frontend && npm install && npm run build      # must finish with "built in ..."
```

---

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Backend logs: `Directory 'frontend' does not exist` at startup | The `/dashboard` static mount needs the `frontend/` folder | It exists via git clone — no action. If you deploy backend code only, keep `frontend/` in the repo. |
| `/health` works but `/stations` is empty / errors | DB didn't download | Check `DB_DOWNLOAD_URL` is correct & public; re-run deploy; confirm build log shows the `curl` downloading ~153 MB |
| Build fails compiling `lightgbm`/`scipy` | You used the root `requirements.txt` | Use **`requirements-deploy.txt`** in the build command |
| Frontend: "Could not load stations" / CORS error in console | `VITE_API_BASE` wrong, or backend asleep | Verify the env var (no trailing slash, no `/api`); hit `/health` to wake Render free tier; redeploy frontend after changing the var |
| Map doesn't render | `VITE_MAPPLS_KEY` missing | The app falls back to MapLibre automatically, but set the key for Mappls tiles |
| First request after idle is very slow | Render/Railway free tier cold start | Ping `/health` ~1 min before the demo |
| GitHub rejects push: "file exceeds 100 MB" | Tried to commit `parkvision.db` | Don't commit it — use Strategy A (release asset) or B (LFS) |

---

## 8. Final go-live checklist

- [ ] `data/parkvision.db` uploaded as a GitHub Release asset (Strategy A)
- [ ] Backend deployed on Render/Railway; `DB_DOWNLOAD_URL` set
- [ ] `curl https://<backend>/health` → `status: ok`, tables `true`
- [ ] `curl https://<backend>/stations` → 54 stations
- [ ] Vercel project: Root Directory = `frontend`, Node 20
- [ ] Vercel env: `VITE_API_BASE` = backend URL, `VITE_MAPPLS_KEY` set
- [ ] Frontend redeployed after setting env vars
- [ ] Open the Vercel URL → station list loads → map + heatmap + simulation work
- [ ] (Optional) Lock CORS to the Vercel domain and redeploy backend
- [ ] Ping `/health` to warm the backend right before presenting
