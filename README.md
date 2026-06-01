# Asset AI — Property-Specific Multifamily Assistant

Asset AI is a property-specific AI assistant for multifamily real estate operations. It answers questions for one active property at a time by combining structured rent-roll analytics, property website retrieval, OpenAI tool calling, and Angular-rendered response components.

The main design goal was to keep the LLM flexible for natural language questions while keeping property metrics grounded in backend calculations.

---

## Hosted Demo

I deployed the application to make the review process easier without requiring a full local setup.

**Hosted App:** https://assetprojectai.netlify.app/

The deployed version uses:

- **Frontend:** Netlify
- **Backend:** Google Cloud Run
- **Database:** Google Cloud SQL for MySQL
- **Secrets:** Google Secret Manager
- **Container build/deployment:** Cloud Build and Artifact Registry

The reviewer can use the hosted app to select a property, ask questions, switch models, and view rendered response components.

---

## What the App Supports

The assistant can answer structured rent-roll questions such as:

- current occupancy
- vacant units
- occupancy and balance trends
- unit type mix
- vacancy loss by unit type
- lease expirations
- high-balance residents
- charge breakdowns
- rent and non-rent charge trends
- future residents/applicants
- unit lookup and unit history
- executive property summaries

It can also answer website-based questions from scraped property pages, such as:

- amenities
- floor plans
- neighborhood details
- contact information

The assistant is scoped to the selected property. If the user asks about another property, it should ask them to switch the active property instead of mixing data.

---

## Architecture

```text
Angular Frontend
  - property selector
  - model selector
  - chat UI
  - KPI cards, tables, charts, source cards

        |
        v

FastAPI Backend
  - validates active property
  - manages chat requests
  - exposes allow-listed tools

        |
        v

OpenAI Tool Calling
  - selects the appropriate backend tool

        |
        v

Backend Tool Registry
  - injects active property_code
  - strips model-supplied property_code
  - executes scoped analytics/retrieval tools

        |
        +--> MySQL rent-roll analytics
        +--> Chroma website retrieval

        |
        v

Grounded Response
  - concise answer
  - structured UI components
  - sources when available
```

---

## Key Design Decisions

### LLM as orchestrator, not calculator

The LLM selects tools and explains results, but structured metrics are calculated by backend services using MySQL data. This avoids relying on the model to invent or calculate important property numbers.

### Backend-enforced property scoping

The frontend sends the active `property_code`, and the backend injects it into every tool call. The LLM cannot choose or override the property code. SQL analytics and Chroma retrieval are both filtered by the active property.

### Separate structured and unstructured data paths

Rent-roll data is stored in MySQL for deterministic analytics. Website content is scraped, embedded, and stored in Chroma for retrieval-based answers about amenities, floor plans, neighborhood, and contact details.

### Backend-generated UI components

The backend returns structured component payloads such as KPI cards, tables, bar charts, and line charts. The frontend renders those components safely instead of relying on the LLM to generate UI code.

### Runtime model switching

The frontend includes a model selector so the user can switch between supported LLMs during the demo.

---

## Local Setup

The app is already deployed, but it can also be run locally.

### Prerequisites

- Python 3.11+
- Node 20+
- Docker Desktop
- OpenAI API key

### Start MySQL

```bash
docker compose up -d mysql
```

The local Docker MySQL database uses:

```text
database: las_assets
user: las_assets_user
password: las_assets_password
host port: 3306
container port: 3306
```

### Backend

```bash
cd backend
python -m venv .venv
```

On Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create `.env`:

```powershell
Copy-Item .env.example .env
```

Set the required values:

```env
OPENAI_API_KEY=your_openai_api_key_here
DATABASE_URL=mysql+pymysql://las_assets_user:las_assets_password@localhost:3306/las_assets
ENABLE_INGEST_ENDPOINT=true
```

Run the backend:

```bash
uvicorn app.main:app --reload
```

Load the demo data:

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/ingest
```

### Frontend

```bash
cd frontend
npm install
npm run start
```

Open:

```text
http://localhost:4200
```

---

## Useful Demo Questions

```text
What is the current occupancy?
Show occupancy trend across months.
Show vacant units.
Show vacancy loss by unit type.
Show unit type mix.
Show high balance residents.
Separate outstanding balances from credits.
Show balance trend across months.
Which leases expire in the next 90 days?
Group lease expirations by month.
Show charge breakdown.
Which non-rent fees are largest?
Show rent charge trend.
Show future residents and applicants.
Look up unit A123 with history in Canfield Park.
Show the rent-roll summary groups.
What amenities does this property advertise?
What floor plans are listed on the website?
What does the website say about the neighborhood?
What is the current occupancy, and what amenities does the website advertise?
```

---

## Assumptions and Tradeoffs

- The rent-roll Excel files are treated as the source of truth for structured metrics.
- Website scraping is a representative sample, not a full production crawler.
- Some property/accounting codes may share the same public website.
- The LLM only orchestrates tools and explains results; it does not directly calculate rent-roll metrics.
- The current project focuses on property analytics and website retrieval, not authentication, admin workflows, or scheduled ingestion.

---

## Current Limitations

- More analytics tools could be added with more data for renewal conversion, delinquency aging, leasing velocity, traffic sources, concessions, maintenance, and renovation ROI.
- Tool descriptions and routing guidance can be improved further so the LLM maps more user phrasings to the correct existing tool.
- More response components could be added, such as comparison cards, stacked charts and property health scorecards.
- Website retrieval depends on scrape quality and may miss JavaScript-rendered content.
- The current project does not include authentication or role-based property access.
- Ingestion is manual for the project; a production version would use scheduled jobs, validation checks, and monitoring.
- Evaluation coverage can be expanded for tool selection, retrieval quality, property scoping, and numeric consistency.

---

## Future Improvements

With more time, I would add more operational tools, improve prompt/tool routing, add richer frontend components, strengthen evaluation tests, add authentication, and build a scheduled ingestion pipeline.

I would also improve source traceability for SQL-derived answers and add better observability around tool calls, retrieval results, and model behavior.


## Screenshots

### Application UI

![Asset AI chat interface](docs/UI_image.png)

### LangSmith Trace

![LangSmith trace for a chat request](docs/Langsmith.png)


### Cloud Run Backend Deployment

![Cloud Run backend service](docs/cloud-run-backend.png)

### Cloud SQL MySQL Database

![Cloud SQL MySQL database tables](docs/cloud-sql-mysql.png)