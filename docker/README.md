# Docker Compose — Fase 2

This folder will contain Docker configurations for the Financial Pipeline infrastructure.

## Phase 2 Plan

- **PostgreSQL 16**: Database for storing financial data, analysis results, and agent state
- **pgvector extension**: Vector storage for embeddings (news articles, reports, embeddings from LLM analysis)
- **docker-compose.yml**: Orchestration file with services for PostgreSQL + pgvector

## Coming Soon

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16-latest
    environment:
      POSTGRES_DB: financial_db
      POSTGRES_USER: admin
      POSTGRES_PASSWORD: password
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

Phase 2 deliverables: `agents/processors.py`, `tools/data_processing.py` and the `docker-compose.yml` above.
