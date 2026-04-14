# Knowledge Drift Detection System

AI-powered system for detecting contradictions, outdated information, and semantic inconsistencies across document collections.

## Architecture

- **Backend**: FastAPI + SQLAlchemy + PostgreSQL + Celery + Redis
- **AI**: NLI (DeBERTa) contradiction detection + Google Gemini for entity extraction
- **Frontend**: Next.js 14 + Lucide icons + Canvas-based knowledge graph
- **Infra**: Docker Compose for local development

## Quick Start

```bash
docker compose up --build
```

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs

## Features

- Document upload & processing (PDF, DOCX, TXT, MD)
- Semantic chunking with embedding-based indexing (ChromaDB)
- NLI-based contradiction detection (DeBERTa-v3)
- Dual drift scoring (Factual + Semantic)
- Real-time alert system with webhook support
- Interactive knowledge graph visualization
- Hybrid search (semantic + BM25)
