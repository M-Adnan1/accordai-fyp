# AccordAI Frontend

React + Vite dashboard for the AccordAI Voice Agent.

## Setup

```bash
npm install
npm run dev
```

Opens at http://localhost:3000

## Backend CORS

Add this to your FastAPI `main.py`:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## Project Structure

```
src/
├── components/
│   ├── layout/         # Sidebar, Layout
│   ├── dashboard/      # StatCard
│   └── calls/          # TranscriptModal
├── pages/
│   ├── Dashboard.jsx   # Analytics & charts
│   ├── Calls.jsx       # Call history table
│   └── Knowledge.jsx   # Document upload/management
├── services/
│   └── api.js          # All backend API calls
└── index.css           # Global design tokens
```

## Pages

- **/** — Dashboard with stat cards, area chart, pie chart
- **/calls** — Paginated call history, click any row to see transcript
- **/knowledge** — Drag & drop file upload, document list, delete
