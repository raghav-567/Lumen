"""Application configuration via pydantic-settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────
    APP_NAME: str = "KnowledgeDrift"
    DEBUG: bool = True

    # ── Database ─────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/knowledgedrift"

    # ── Redis ────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Auth ─────────────────────────────────────────
    SECRET_KEY: str = "dev-secret-change-in-production-use-openssl-rand-hex-32"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1 day
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    ALGORITHM: str = "HS256"

    # ── Gemini ───────────────────────────────────────
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"

    # ── Groq (free tier — Llama 3.3 70B) ─────────────
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # ── Embedding ────────────────────────────────────
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIMENSION: int = 384

    # ── ChromaDB ─────────────────────────────────────
    CHROMA_PERSIST_DIR: str = "data/chroma"

    # ── Ingestion ────────────────────────────────────
    UPLOAD_DIR: str = "data/uploads"
    MAX_FILE_SIZE_MB: int = 50
    CHUNK_SIZE: int = 512
    CHUNK_OVERLAP: int = 50

    # ── Contradiction detection ──────────────────────
    SIMILARITY_THRESHOLD: float = 0.6
    CONTRADICTION_CONFIDENCE_THRESHOLD: float = 0.7
    MAX_COMPARISONS_PER_CHUNK: int = 5
    NLI_CONTRADICTION_THRESHOLD: float = 0.80   # auto-flag as contradiction
    NLI_BORDERLINE_THRESHOLD: float = 0.65      # route to review queue, not auto-alert
    ENTAILMENT_ASYMMETRY_CHECK: bool = True      # bidirectional NLI — doubles NLI calls but catches elaboration
    STRUCTURED_SCAN_THRESHOLD: float = 0.65      # min structure_confidence to use structured scan path

    # ── Pipeline optimization ────────────────────────
    NOISE_FILTER_ENABLED: bool = True
    DEDUP_ENABLED: bool = True
    DEDUP_THRESHOLD: float = 0.93
    CLUSTER_ROUTING_ENABLED: bool = True
    CLUSTER_COUNT: int = 20
    SIMILARITY_GATE_THRESHOLD: float = 0.75   # skip candidates below this
    GATE_SAMPLE_RATE: float = 0.05            # randomly retain 5% of gated candidates for calibration
    LAZY_EXPLANATIONS: bool = True             # generate on-demand, not during scan
    DYNAMIC_RETRIEVAL: bool = True             # adaptive top-K based on similarity

    # ── Reranking (Phase A7) ─────────────────────────
    RERANK_ENABLED: bool = False               # disabled by default — CPU too expensive
    RERANK_RETRIEVE_K: int = 10                # reduced from 20
    RERANK_FINAL_K: int = 5
    RERANK_THRESHOLD: float = 0.0

    # ── Ollama (local LLM for claim extraction) ──────
    OLLAMA_URL: str = "http://ollama:11434"
    EXTRACTION_MODEL: str = "qwen2.5:1.5b"
    EXTRACTION_TIMEOUT: int = 120
    EXTRACTION_MAX_RETRIES: int = 3
    EXTRACTION_ENABLED: bool = False  # Set True when Ollama has GPU or fast CPU

    # ── Celery ───────────────────────────────────────
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "db+postgresql://postgres:postgres@localhost:5432/knowledgedrift"

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
