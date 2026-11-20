# India Economic Dashboard

**India's latest available official economic indicators, powered by MoSPI data.**

[![Next.js](https://img.shields.io/badge/Next.js-15-black?logo=next.js)](https://nextjs.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.7-blue?logo=typescript)](https://www.typescriptlang.org/)
[![MoSPI MCP](https://img.shields.io/badge/Data-MoSPI%20MCP-orange)](https://mcp.mospi.gov.in/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Live Demo](https://img.shields.io/badge/Live_Demo-▶_Vercel-black?logo=vercel)](https://india-economic-dashboard.vercel.app)

🔗 **Live Demo:** [india-economic-dashboard.vercel.app](https://india-economic-dashboard.vercel.app)

![Dashboard Preview](screenshot.png)

## What is this?

A dashboard that fetches official data from the Government of India's Ministry of Statistics and Programme Implementation (MoSPI) via its [Model Context Protocol (MCP)](https://github.com/nso-india/esankhyiki-mcp) server. Status reflects successful source fetches; observations themselves are published periodically, not streamed in real time.

Track GDP growth, retail inflation (CPI), wholesale inflation (WPI), and industrial production (IIP). The dashboard selects the latest available periods independently for each series.

## Features

- **Official government data** - Pulls from MoSPI's MCP server at `mcp.mospi.gov.in` (no API keys needed)
- **GDP Growth** - Quarterly GDP and GVA growth rates from National Accounts Statistics (NAS)
- **CPI Inflation** - Monthly all-India combined general CPI index and inflation
- **WPI Inflation** - Overall wholesale price index and year-on-year inflation matched to the same calendar month in the prior year
- **Industrial Production** - Index of Industrial Production (IIP) for mining, manufacturing, and electricity
- **Interactive charts** - Zoom, hover, and explore trends with Recharts
- **Skeleton loading states** - Shimmer animations while data loads from MoSPI
- **Glassmorphism UI** - Dark mode interface with blur effects and smooth Framer Motion animations
- **Server-side caching** - In-memory cache with 6-hour TTL (data updates monthly/quarterly, so this is plenty)
- **Honest freshness states** - LIVE, UPDATING, STALE, or OFFLINE, with the last successful fetch time
- **Refresh controls** - Manual refresh and configurable 15-minute, hourly, or 6-hour automatic refresh
- **AI Economic Research Assistant** - Cited answers grounded in persisted official data, analysis, forecasts, anomalies, and versioned government reports

## Data Source

India's National Statistical Office (NSO) launched an MCP server at [`mcp.mospi.gov.in`](https://mcp.mospi.gov.in/), making official government statistics available via the [Model Context Protocol](https://modelcontextprotocol.io/). This dashboard is a client for that server.

The MCP server exposes datasets including National Accounts (GDP/GVA), Consumer Price Index, Wholesale Price Index, and Index of Industrial Production - the same data used in government reports and RBI policy decisions.

Source: [nso-india/esankhyiki-mcp](https://github.com/nso-india/esankhyiki-mcp)

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | [Next.js 15](https://nextjs.org/) (App Router, Turbopack) |
| Language | [TypeScript 5.7](https://www.typescriptlang.org/) |
| UI | [React 19](https://react.dev/), [Tailwind CSS](https://tailwindcss.com/) |
| Charts | [Recharts](https://recharts.org/) |
| Animations | [Framer Motion](https://www.framer.com/motion/) |
| Data Protocol | [MCP](https://modelcontextprotocol.io/) (SSE transport, JSON-RPC 2.0) |
| Linting | [Biome](https://biomejs.dev/) |
| Package Manager | [Bun](https://bun.sh/) |

## How It Works

```
Browser  -->  Next.js API Routes  -->  MoSPI MCP Server
                (server-side)          (mcp.mospi.gov.in)
                    |
                    +--> optional authenticated ingestion --> FastAPI --> PostgreSQL
```

1. Next.js API routes (`/api/gdp`, `/api/cpi`, `/api/wpi`, `/api/iip`) act as MCP clients
2. Each dataset fetch follows MoSPI's workflow:
   - `initialize` - Establish an MCP session
   - `list_datasets` / `get_indicators` - Discover available datasets and indicators
   - `get_metadata` - Resolve available periods and exact filter codes
   - `get_data` - Fetch observations using the metadata filter codes
3. Responses are cached server-side (6-hour default TTL); failed refreshes can use cached official observations and are marked STALE
4. The client fetches from these API routes and renders interactive charts

All MCP communication happens server-side - no direct browser-to-MoSPI calls.

## Optional historical storage service

The dashboard remains fully usable without this service or a database. To archive validated observations from all four official dashboard endpoints:

1. Copy `.env.example` to the Next.js server's `.env.local`; configure `INTELLIGENCE_API_TOKEN` and `INTELLIGENCE_SERVICE_URL`.
2. Configure `DATABASE_URL` and the same `INTELLIGENCE_API_TOKEN` in the Python service environment.
3. Install and start the service from the repository root:

   ```powershell
   py -3.11 -m venv python-service\.venv
   python-service\.venv\Scripts\python.exe -m pip install -r python-service\requirements-dev.txt
   Set-Location python-service
   $env:DATABASE_URL = "postgresql://USER:PASSWORD@HOST:5432/DATABASE"
   $env:INTELLIGENCE_API_TOKEN = "use-the-same-long-random-secret-as-the-next-app"
   .\.venv\Scripts\python.exe -m app.migrate
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

4. Send a `POST` to `/api/intelligence/ingest` on the Next.js server with `Authorization: Bearer <INTELLIGENCE_API_TOKEN>`. The route refreshes the four MoSPI datasets and archives only observations present in those responses; failed datasets are recorded as partial ingestion, never replaced with mock data.

The Python API also provides `/health` and authenticated `/v1/history/{metric_code}`. PostgreSQL migrations are versioned and ingestion uses unique metric/period keys with upserts. Fetch timestamps are stored separately from optional official publication dates. Run the schema and endpoint tests with `Set-Location python-service; .\.venv\Scripts\python.exe -m pytest tests`.

## Forecasting service

The optional FastAPI service provides validated forecasting for `gdp_real_growth`, `cpi_inflation`, `wpi_inflation`, and `iip_growth`.

- Models: naive, seasonal-naive, ARIMA, SARIMA, Random Forest Regressor and XGBoost Regressor.
- Validation: chronological rolling-origin, one-step retraining, MAE, RMSE, sMAPE and directional accuracy.
- Intervals: ARIMA/SARIMA confidence intervals or empirical residual intervals only when enough residuals exist.
- Monthly horizons: 1, 3, 6 or 12; GDP horizons: 1, 2 or 4 quarters.
- Insufficient data is returned honestly and is not replaced by fabricated predictions.

Authenticated endpoints:

- `POST /v1/forecasts/generate`
- `GET /v1/forecasts/{indicator_code}`
- `GET /v1/forecasts/{indicator_code}/compare`
- `GET /v1/forecasts/{indicator_code}/history-versus-forecast`

The Next.js `/api/forecasts` route keeps service bearer credentials server-side. Forecast runs and metrics use the existing `model_registry`, `model_training_runs`, `forecast_metrics` and `forecasts` PostgreSQL tables.

## Economic Trend Analysis

The optional intelligence service also provides persisted-observation trend analysis:

- Period change and year-on-year change.
- Quarter-on-quarter and index-level movement where applicable.
- 3, 6 and 12-period moving averages.
- Rolling standard-deviation volatility and historical ranges.
- Percentage deviation from moving averages.
- Transparent upward, downward, stable, accelerating and decelerating rules.
- Pearson correlations with exact calendar-month or documented quarterly aggregation.
- Data-grounded economic insights with source, period, comparison, magnitude and evidence strength.
- Sector summaries only for persisted GVA Agriculture, Industry and Services observations.

Authenticated endpoints:

- `GET /v1/analysis/trends/{indicator_code}`
- `GET /v1/analysis/growth/{indicator_code}`
- `GET /v1/analysis/volatility/{indicator_code}`
- `GET /v1/analysis/correlations`
- `GET /v1/analysis/insights`
- `GET /v1/analysis/sectors`

These endpoints accept `start` and `end` ISO dates where applicable. Volatility accepts a `window` parameter. Correlation does not imply causation and reports aligned sample size. Monthly and quarterly series are not mixed without fiscal-quarter aggregation.

## Economic Anomaly Detection

The intelligence service includes anomaly detection on persisted official observations:

- Historical and rolling Z-score detection with configurable thresholds.
- Isolation Forest using lag, rolling mean and rolling volatility features.
- Additive seasonal-residual detection for sufficiently long monthly or quarterly series.
- Low, medium and high severity thresholds based on documented Z-score or Isolation Forest score rules.
- Idempotent PostgreSQL persistence in `anomaly_detections`, with source provenance and model parameters.

Authenticated endpoints:

- `POST /v1/anomalies/detect`
- `GET /v1/anomalies`
- `GET /v1/anomalies/{indicator_code}`
- `GET /v1/anomalies/summary`
- `GET /v1/anomalies/methods`

The Next.js `/api/anomalies` route keeps bearer credentials server-side. Statistical anomalies are not verified economic events and do not imply causation or misconduct.

## AI Economic Research Assistant

The research assistant retrieves persisted PostgreSQL observations, saved forecasts and evaluation metrics, persisted analysis/anomalies, and versioned official reports. It combines database-backed structured evidence with semantic and keyword-ranked document chunks, then requests a cited answer from a configurable OpenAI-compatible provider. It does not substitute generated text or web search for missing observations.

Features:

- PDF and UTF-8 text extraction, bounded uploads, overlapping chunks, SHA-256 provenance, source metadata, publication dates and explicit document versions.
- Idempotent ingestion for the same document content/version; a different content hash/version creates a separate record instead of overwriting history.
- Official-source HTTPS validation for `.gov.in`, `.nic.in` and RBI domains.
- Embeddings are stored as PostgreSQL JSONB and cosine-ranked in the Python service. pgvector is not required, avoiding an unverified PostgreSQL extension dependency. Retrieval is bounded to 5,000 candidate chunks per request.
- Hybrid retrieval combines embedding similarity with keyword overlap. Structured economic observations, forecasts, forecast metrics, analysis and anomaly records are queried from their existing tables.
- Answers distinguish observed values, forecasts, analyses and statistical anomalies. Each sentence must cite retrieved evidence, citations must map to returned evidence, and numeric tokens are checked against cited context; unverifiable output is rejected.
- Conversations are scoped to a random HttpOnly browser-session cookie. The current dashboard has no account/login system, so this provides per-browser isolation, not authenticated cross-device user accounts. Clearing cookies/site data starts a new conversation namespace.

Configure these values in the Python service environment (never in browser-exposed `NEXT_PUBLIC_*` variables):

- `OPENAI_API_KEY` — provider credential.
- `OPENAI_BASE_URL` — OpenAI-compatible API base URL (default `https://api.openai.com/v1`).
- `OPENAI_CHAT_MODEL` — chat model supporting JSON response mode.
- `OPENAI_EMBEDDING_MODEL` — embedding model (default `text-embedding-3-small`).
- `RESEARCH_INGEST_TOKEN` — separate high-entropy secret required in addition to the service bearer token for document ingestion.
- Existing `DATABASE_URL` and `INTELLIGENCE_API_TOKEN`.

Apply migrations through the existing `python -m app.migrate` command; migration `005_research_assistant.sql` adds documents, chunks, conversations and messages without changing observation, forecast or anomaly storage.

Authenticated service endpoints:

- `POST /v1/research/chat` — requires `X-Research-Owner` UUID in addition to the service bearer token.
- `GET /v1/research/history` — owner-scoped; also requires `X-Research-Owner`.
- `POST /v1/research/retrieve` — semantic/hybrid evidence retrieval with indicator, source, date and result-count filters.
- `POST /v1/research/documents/ingest` — multipart PDF/text ingestion; requires both the service bearer token and `X-Research-Ingest-Token`.
- `GET /v1/research/documents`
- `GET /v1/research/sources`

The Next.js server proxies chat/history/retrieval/list endpoints and keeps service credentials server-side. Use the FastAPI ingestion endpoint from a trusted administrative process; it is intentionally not exposed as an unauthenticated browser upload. Provider errors return explicit service errors; no fallback is represented as an LLM-generated answer.

Example trusted-operator upload from PowerShell (the file path and values below are examples):

```powershell
curl.exe -X POST "http://127.0.0.1:8000/v1/research/documents/ingest" `
  -H "Authorization: Bearer $env:INTELLIGENCE_API_TOKEN" `
  -H "X-Research-Ingest-Token: $env:RESEARCH_INGEST_TOKEN" `
  -F "title=MoSPI economic report" `
  -F "source_name=MoSPI" `
  -F "source_url=https://mospi.gov.in/" `
  -F "version=2026-10" `
  -F "publication_date=2026-10-01" `
  -F "file=@C:\reports\economic-report.pdf;type=application/pdf"
```

Limitations: semantic search and chat require a configured compatible provider. Scanned PDFs without an extractable text layer are rejected (OCR is not implemented). Document authority is validated by HTTPS domain, while the trusted ingestion operator remains responsible for confirming the uploaded file and its publication metadata. Browser session IDs are pseudonymous and are not an identity provider. No pgvector, full-text-search index, or external website crawler is introduced.

Research-assistant tests cover PDF/text extraction, chunking, official URL validation, provider configuration failures, hybrid retrieval, grounding/citation validation, authentication, and—when `TEST_DATABASE_URL` is configured—document versioning and conversation ownership isolation.

### PostgreSQL setup

The historical service requires a PostgreSQL 18-compatible database. It does not start or authenticate to PostgreSQL automatically.

1. Create a dedicated application database and least-privilege login. Example with `psql`:

   ```sql
   CREATE ROLE arthasense_app LOGIN PASSWORD 'use-a-secret-generated-by-your-password-manager';
   CREATE DATABASE arthasense OWNER arthasense_app;
   GRANT ALL PRIVILEGES ON DATABASE arthasense TO arthasense_app;
   ```

2. Set `DATABASE_URL` in the environment used to start the Python service:

   ```powershell
   $env:DATABASE_URL = "postgresql://arthasense_app:YOUR_PASSWORD@127.0.0.1:5432/arthasense"
   $env:DATABASE_CONNECT_TIMEOUT_SECONDS = "5"
   $env:INTELLIGENCE_API_TOKEN = "use-the-same-long-random-secret-as-the-next-app"
   ```

3. Apply the versioned migration and verify a second run is a no-op:

   ```powershell
   Set-Location python-service
   py -3.11 -m app.migrate
   py -3.11 -m app.migrate
   ```

4. Start the service, then use the authenticated Next.js route:

   ```powershell
   py -3.11 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

   Set `INTELLIGENCE_API_TOKEN` and `INTELLIGENCE_SERVICE_URL=http://127.0.0.1:8000` in the Next.js `.env.local`, start Next.js, and send `POST /api/intelligence/ingest` with `Authorization: Bearer <INTELLIGENCE_API_TOKEN>`.

For disposable local verification, Docker can provide an isolated database:

```powershell
docker run --detach --name arthasense-postgres-test --publish 55432:5432 `
  --env POSTGRES_DB=arthasense_test --env POSTGRES_USER=arthasense `
  --env POSTGRES_PASSWORD='use-a-local-test-only-password' postgres:18-alpine
$env:DATABASE_URL = "postgresql://arthasense:use-a-local-test-only-password@127.0.0.1:55432/arthasense_test"
$env:TEST_DATABASE_URL = $env:DATABASE_URL
Set-Location python-service
py -3.11 -m pytest tests
docker rm --force arthasense-postgres-test
```

## Observation periods and calculations

Monthly API observations preserve the source calendar year and include a separate fiscal year; chart labels use calendar periods such as `Oct 2026`, while summary cards also show the corresponding fiscal year. GDP periods are labeled by quarter and fiscal year, for example `Q2 FY 2025-26`. These are observation periods, not publication dates.

CPI index and inflation are separate values. Official CPI inflation is used when supplied; otherwise it is calculated only when the same-series index for the same month in the prior year is available. WPI inflation is calculated from comparable overall-index observations in the same calendar month one year apart. Missing comparison observations remain unavailable rather than being represented as zero.

## Getting Started

### Prerequisites

- [Bun](https://bun.sh/) (v1.0+)
- [Node.js](https://nodejs.org/) (v18+)

### Run locally

```bash
git clone https://github.com/adhishthite/india-economic-dashboard.git
cd india-economic-dashboard
bun install
bun run dev
```

Open [http://localhost:3000](http://localhost:3000).

No API keys are required. The server-side cache TTL can be configured with `MOSPI_CACHE_TTL_MS` (milliseconds; default `21600000`).

### Other commands

```bash
bun run build          # Production build
bun run start          # Start production server
make check             # Format + lint (Biome)
make typecheck         # TypeScript type checking
make validate          # Full validation (format + lint + typecheck)
```

## Project Structure

```
src/
  app/
    page.tsx                   # Main dashboard (client component)
    layout.tsx                 # Root layout with theme provider
    api/
      gdp/route.ts            # GDP data endpoint
      cpi/route.ts            # CPI data endpoint
      wpi/route.ts            # WPI data endpoint
      iip/route.ts            # IIP data endpoint
      summary/route.ts        # Summary statistics endpoint
      intelligence/ingest/route.ts # Authenticated optional history ingestion
  components/
    header.tsx                 # Navigation header with tab switching
    summary-cards.tsx          # Overview stat cards
    skeletons.tsx              # Skeleton loading states
    charts/
      gdp-chart.tsx            # GDP growth rate chart
      cpi-chart.tsx            # CPI inflation chart
      wpi-chart.tsx            # WPI inflation chart
      iip-chart.tsx            # IIP production chart
    ui/
      card.tsx                 # Glass-effect card component
      chart-tooltip.tsx        # Custom chart tooltip
      skeleton.tsx             # Base skeleton component
  lib/
    mcp-client.ts              # Generic MCP protocol client (SSE + JSON-RPC)
    mcp-cache.ts               # In-memory cache with TTL
    date-utils.ts              # Calendar-month and April-March fiscal-year helpers
    data-fetchers.ts           # Dataset-specific fetchers
    types.ts                   # TypeScript type definitions
    api-route.ts               # Shared official-data response/status handling
    summary-stats.ts           # Summary cards derived from validated API observations
    intelligence-ingest.ts    # Validated MoSPI observation normalization
python-service/
  app/
    main.py                   # Optional FastAPI ingestion/history service
    database.py               # PostgreSQL migrations and idempotent persistence
    schemas.py                # Strict payload and period validation
    migrations/               # Versioned intelligence schema
```

## Author

**Adhish Thite**

- GitHub: [@adhishthite](https://github.com/adhishthite)
- LinkedIn: [adhish-thite](https://linkedin.com/in/adhish-thite)
- Twitter: [@xadhish](https://x.com/xadhish)

## License

MIT License - see [LICENSE](LICENSE) for details.
