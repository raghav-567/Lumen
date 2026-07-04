"""Application configuration via pydantic-settings."""

from __future__ import annotations

from pydantic import model_validator
from pydantic_settings import BaseSettings

# The literal placeholder shipped in .env.example / committed defaults. Never
# acceptable as a live signing key — guarded below.
INSECURE_SECRET_DEFAULT = "dev-secret-change-in-production-use-openssl-rand-hex-32"


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────
    APP_NAME: str = "KnowledgeDrift"
    DEBUG: bool = True

    # ── Database ─────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/knowledgedrift"

    # ── Redis ────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Auth ─────────────────────────────────────────
    # SECRET_KEY must come from the environment in any non-debug deployment.
    # The default below is intentionally the insecure placeholder so a fresh
    # `docker compose up` works locally; the validator forbids it when DEBUG=False.
    SECRET_KEY: str = INSECURE_SECRET_DEFAULT
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1 day (demo access token)
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # retained for compatibility; not used by the demo
    ALGORITHM: str = "HS256"

    # ── CORS ─────────────────────────────────────────
    # Comma-separated list of allowed browser origins for the frontend.
    FRONTEND_ORIGIN: str = "http://localhost:3000"

    # ── Rate limiting (slowapi) ──────────────────────
    # The NLI pipeline is CPU-bound, so the upload + scan endpoints are throttled
    # per client IP to keep an unthrottled caller from saturating the worker.
    UPLOAD_RATE_LIMIT: str = "10/minute"
    SCAN_RATE_LIMIT: str = "20/minute"

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
    # When CHROMA_HOST is set, all processes (API, Celery, scripts) share a
    # single ChromaDB *server* via HttpClient. This is required for correctness:
    # the embedded PersistentClient opens the on-disk SQLite + HNSW segments
    # directly, and multiple processes pointing at the same files corrupt the
    # vector segments (lost writes / "Label not found" / stale segments after
    # deletes). The persist dir below is only used as an embedded fallback for
    # single-process local runs and tests.
    CHROMA_PERSIST_DIR: str = "data/chroma"
    CHROMA_HOST: str = ""
    CHROMA_PORT: int = 8000

    # ── Ingestion ────────────────────────────────────
    UPLOAD_DIR: str = "data/uploads"
    MAX_FILE_SIZE_MB: int = 50
    CHUNK_SIZE: int = 512
    CHUNK_OVERLAP: int = 50

    # ── Contradiction detection ──────────────────────
    SIMILARITY_THRESHOLD: float = 0.6
    CONTRADICTION_CONFIDENCE_THRESHOLD: float = 0.7
    MAX_COMPARISONS_PER_CHUNK: int = 5
    # A genuine contradiction must concern overlapping subject matter, so the two
    # claims must share at least this many salient (non-stopword) terms. Guards
    # against the cross-encoder flagging two same-topic but different-subject
    # sentences (e.g. a PIN definition vs a binding-code rule) as contradictory.
    # Set to 0 to disable.
    MIN_SHARED_CLAIM_TERMS: int = 1
    NLI_CONTRADICTION_THRESHOLD: float = 0.80   # auto-flag as contradiction
    NLI_BORDERLINE_THRESHOLD: float = 0.65      # route to review queue, not auto-alert
    ENTAILMENT_ASYMMETRY_CHECK: bool = True      # bidirectional NLI — doubles NLI calls but catches elaboration
    STRUCTURED_SCAN_THRESHOLD: float = 0.65      # min structure_confidence to use structured scan path

    # ── Pairwise routed scan (Fix A) ─────────────────
    # Candidate shortlist for the routed pairwise scan. Deliberately LOOSE: the
    # NLI stage is the real precision gate, so the shortlist should over-include
    # rather than miss a contradicting partner. Similarity = 1 - cosine distance.
    SHORTLIST_SIM_THRESHOLD: float = 0.30        # loose: any doc sharing this much similarity is a candidate
    RESCAN_MAX_CANDIDATES: int = 25              # cap candidate docs per scan (bounds fan-out)
    RESCAN_TASK_RATE_LIMIT: str = "12/m"         # bound concurrency of queued pairwise scan jobs (Fix B)
    # Cap source claims scanned per document pair. The embedding scan runs one
    # retrieval + NLI per (source claim × candidate doc); an unbounded doc with
    # 1000+ claims makes a single scan take many minutes (NLI is ~CPU-bound).
    # Claims are ranked by importance_weight and the top-N kept, so high-signal
    # claims (where contradictions live) still scan. Lower = faster drift after
    # upload, slightly less exhaustive.
    EMBEDDING_SCAN_MAX_CLAIMS: int = 100
    # Max previously-unscanned doc pairs queued per reconciliation pass (bounds
    # the catch-up fan-out; rerun reconcile to drain a larger backlog).
    RECONCILE_MAX_PAIRS: int = 200

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

    @property
    def cors_origins(self) -> list[str]:
        """Allowed browser origins, parsed from the comma-separated env value."""
        return [o.strip() for o in self.FRONTEND_ORIGIN.split(",") if o.strip()]

    @model_validator(mode="after")
    def _forbid_insecure_secret_in_prod(self):
        if not self.DEBUG and self.SECRET_KEY == INSECURE_SECRET_DEFAULT:
            raise RuntimeError(
                "SECRET_KEY is still the insecure default. Set a real value "
                "(e.g. `openssl rand -hex 32`) via the environment before running "
                "with DEBUG=False."
            )
        return self

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
