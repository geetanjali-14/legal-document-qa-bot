# PRODUCTION MIGRATION GUIDE: LEGAL QA CHATBOT

```text
Status: Development → Production Migration Guide
Last verified: 2026-10-08
Development architecture: Local-First / Hybrid Legal RAG (FastAPI + Embedded Qdrant + BM25/RRF + Gemini 3.8 Flash / Gemini Embedding 2 / SQLite)
Production target: Scalable Cloud Architecture / Managed Services (Containerized FastAPI on ECS/K8s/Cloud Run + Managed PostgreSQL + S3/GCS Object Storage + Managed Vector DB / Managed xAI RAG + Production LLM)
```

---

## 1. Development vs. Production Architecture

This section documents the transition path from the current development setup implemented in this repository to a hardened, enterprise-ready production deployment.

### 1.1 Development Architecture (Current Implementation)

The development environment is designed to be self-contained, low-friction, and local-first, utilizing local embedded storage, deterministic legal structural parsing, local keyword search, embedded vector search, and direct LLM calls:

```text
               +--------------------------------------------------+
               |          Vanilla JS Browser Client (SPA)         |
               | (Static Files served via FastAPI / UI Dashboard) |
               +--------------------------------------------------+
                                        │
                                        ▼ HTTP / REST (/api/v1/...)
               +--------------------------------------------------+
               |               Local FastAPI Server               |
               |        (Uvicorn ASGI single process :8000)       |
               +--------------------------------------------------+
                                        │
                   ┌────────────────────┼────────────────────┐
                   ▼                    ▼                    ▼
         [routes_documents.py]   [routes_chat.py]  [routes_conversations.py]
                   │                    │                    │
                   │                    ▼                    ▼
                   │          [AgentOrchestrator]    [ConversationRepository]
                   │         (Intent Router + Tools)         │
                   │                    │                    ▼
                   │                    │            [SQLAlchemy ORM]
                   │                    │                    │
                   │                    │                    ▼
                   │                    │            [Local SQLite DB]
                   │                    │           (data/legal_qa.db)
                   │                    │               (WAL mode)
                   │                    │
                   ▼                    ▼
        [DocumentService]       [RetrievalService]
        ┌───────────────────────┴───────────────────────┐
        │                                               │
        ▼ (Ingestion Pipeline)                          ▼ (Query Pipeline)
 1. PDF Parser (PyMuPDF)                        1. Query Normalization &
    + Image OCR (RapidOCR ONNX)                    Pronoun Resolution
 2. Structure Parser                            2. Dense Embedding:
    (Articles, Sections, Clauses)                  - Gemini Embedding 2
 3. Structure-Aware Chunking                       - or TF-IDF / FastEmbed
    (app/services/chunking_service.py)          3. Dense Vector Search:
 4. Dual Indexing:                                 - Local Embedded Qdrant
    a. Qdrant Embedded Vectors                     - or Cosine Sim Fallback
       (data/vector_store/qdrant_db)            4. Lexical Search:
    b. BM25 In-Memory Indices                      - BM25Okapi over chunks
       (rank-bm25 Okapi per doc)                5. Reciprocal Rank Fusion:
 5. Local Storage:                                 - RRF(dense, bm25; k=60)
    - data/uploads/ (*.pdf, images)             6. Relevance Confidence Gate
    - data/uploads/documents_meta.json          7. Structured Context Window
        │                                               │
        └───────────────────────┬───────────────────────┘
                                │
                                ▼
                       [LLMService Dispatch]
                                │
                                ├── Gemini 3.8 Flash (Active Development)
                                ├── Mock LLM (Zero-dependency Unit Tests)
                                ├── Grok / xAI (`grok-beta`)
                                ├── OpenAI (`gpt-4o-mini`)
                                └── Mistral (`mistral-large-latest`)
```

---

### 1.2 Production Architecture (Target Implementation)

The production architecture separates stateless compute from persistent state, replacing local disk storage and embedded engines with managed, scalable cloud services.

```text
               +--------------------------------------------------+
               |              CloudFront / Cloudflare CDN         |
               |             (TLS Termination + Edge WAF)         |
               +--------------------------------------------------+
                                        │
                        ┌───────────────┴───────────────┐
                        ▼                               ▼
         [Frontend Static Assets]             [Production API Gateway]
           (S3 / GCS Bucket)                      (ALB / Ingress NGINX)
                                                        │
                                                        ▼
                                       +----------------------------------+
                                       |      Production API Cluster      |
                                       | (Stateless FastAPI Containers)   |
                                       | (ECS Fargate / EKS / Cloud Run)  |
                                       +----------------------------------+
                                                        │
             ┌───────────────────────────┬──────────────┴───────────────────────────┐
             ▼                           ▼                                          ▼
   [Relational DB]              [Object Storage]                           [Document Ingestion Queue]
Managed AWS RDS Aurora         AWS S3 / Google GCS                         Celery / AWS SQS Worker Pool
   PostgreSQL 16+               Bucket with SSE                            (Background PDF/OCR Jobs)
(Connection Pooling / PgBouncer) (Raw PDFs & images)                                │
             │                           │                                          │
             └───────────────────────────┼──────────────────────────────────────────┘
                                         ▼
                               [Search & Retrieval Layer]
```

#### Search & Retrieval Architectural Options

Depending on organizational requirements, infrastructure preferences, and vendor lock-in risk, two primary production targets are supported:

##### Option A: Self-Managed Hybrid Retrieval (Current Production Recommendation)
Maintains full ownership of indexing, proprietary chunking, legal structure parsing, and retrieval scoring:
```text
Stateless API / Workers
        │
        ├── Document Parser: In-process PyMuPDF / Dedicated OCR microservice
        ├── Legal Structure Parser & Chunking: Retains app/services/chunking_service.py
        ├── Managed Embeddings: Google Gemini Embedding 2 / OpenAI text-embedding-3-small
        ├── Managed Vector Engine: Qdrant Cloud Cluster / AWS OpenSearch Serverless
        ├── Managed Lexical Engine: OpenSearch BM25 or Qdrant Sparse-Dense Hybrid
        └── Answer Synthesis: Gemini 3.8 Flash / OpenAI GPT-4o / xAI Grok
```

##### Option B: Fully Managed xAI Production RAG (Alternative Recommendation)
Delegates document parsing, chunking, storage, vector management, and hybrid retrieval to xAI's managed infrastructure:
```text
Stateless API / Ingestion Service
        │
        ▼
   [xAI Management API]
        ├── Upload document to xAI Files API (`POST https://api.x.ai/v1/files`)
        └── Ingest into xAI Collections (`POST https://api.x.ai/v1/collections/{id}/documents`)
        │
        ▼ (Query Phase)
   [xAI Chat Completions with Search / RAG Tools]
        ├── Endpoint: `https://api.x.ai/v1/chat/completions`
        ├── Model: `grok-beta` or `grok-2`
        └── Server-Side Hybrid Retrieval over xAI Collections
        │
        ▼
   Synthesized Grounded Answer & Server-Side Document Citations
```

---

## 2. Component Migration Matrix

The following matrix maps every component from its development implementation to its production equivalent:

| Area | Development / Local Setup | Production / Scaling Setup | Migration Required? | Implementation & Architectural Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Frontend** | Vanilla JS / CSS served from FastAPI `frontend/static` | Static Hosting on AWS S3/CloudFront or Cloudflare Pages | **Yes** | Decouple static asset delivery from backend CPU cycles. Set `window.API_BASE_URL` to point to the production API gateway. |
| **API Server** | Single-process Uvicorn on `localhost:8000` | Multi-replica containerized Uvicorn behind Gunicorn on ECS Fargate, EKS, or Cloud Run | **Yes** | Use multi-stage Docker build (`Dockerfile`). Run with `--workers 4` per pod, managed autoscaling based on CPU/Request count. |
| **Document Storage** | Local directory `data/uploads/` | AWS S3 or Google Cloud Storage (GCS) with SSE-KMS | **Yes** | Abstract local disk I/O in `DocumentService` to S3-compatible client (`boto3` / `google-cloud-storage`). Presigned URLs for secure viewing. |
| **Database** | SQLite WAL file (`data/legal_qa.db`) | Managed PostgreSQL 15+ (AWS RDS Aurora / Cloud SQL) | **Yes** | Application already uses SQLAlchemy with PostgreSQL connection pool support (`DATABASE_URL`). Schema migration needed (Alembic). |
| **Document Parser** | In-process PyMuPDF (`fitz`) | In-process PyMuPDF or asynchronous worker pool (Celery/SQS) | **Maybe** | Lightweight PDFs parse in-process (<500ms). For heavy legal bundles (>50 pages), offload parsing to background worker queue to avoid blocking ASGI loop. |
| **OCR Engine** | Local RapidOCR (`rapidocr_onnxruntime`) | Celery background workers with GPU or cloud OCR API (AWS Textract / Mistral OCR) | **Yes** | ONNX runtime is CPU-intensive. Running high-volume OCR on the web API tier degrades chat responsiveness. |
| **Chunking** | Structure-aware regex chunker (`chunking_service.py`) | Same structure-aware chunker running in background worker | **No** | Legal structural chunking (Articles, Sections, Clauses) is domain-specific and remains unchanged for Option A. (Bypassed if Option B xAI Collections is used). |
| **Embeddings** | Gemini Embedding 2 via `google-genai` (or local TF-IDF) | Google Gemini Embedding 2 or OpenAI `text-embedding-3-small` | **Yes/No** | Keep `gemini-embedding-2` for semantic quality, or switch via `EMBEDDING_PROVIDER`. Must provision dedicated enterprise quotas and API keys. |
| **Vector Search** | Embedded Qdrant (`data/vector_store/qdrant_db`) + NumPy fallback | Managed Qdrant Cloud cluster or AWS OpenSearch | **Yes** | Point `QdrantClient(url=settings.QDRANT_URL, api_key=...)` to cloud cluster. Embedded filesystem mode is incompatible with multi-container scaling. |
| **Keyword Search** | In-memory `BM25Okapi` per doc (`retrieval_service.py`) | Qdrant Sparse Vectors (BM25/SPLADE) or OpenSearch | **Yes** | In-memory BM25 indices cannot be shared across multiple stateless API container replicas. Move lexical search to centralized cluster. |
| **RAG Orchestrator** | `AgentOrchestrator` with RRF fusion (`app/services/agent_orchestrator.py`) | Same `AgentOrchestrator` (Option A) OR xAI Managed Collections (Option B) | **Yes** | Option A preserves the code as-is with cloud vector backend. Option B routes queries through xAI's managed document collection API. |
| **LLM Provider** | Gemini 3.8 Flash (`gemini-3.8-flash`) / Mock | Gemini 3.8 Flash, xAI Grok (`grok-beta`), or OpenAI GPT-4o | **Yes** | Transition from personal API key to enterprise billing account with pre-provisioned throughput and strict timeout/retry circuit breakers. |
| **Secrets Management**| Plaintext `.env` file | AWS Secrets Manager, HashiCorp Vault, or GCP Secret Manager | **Yes** | Inject secrets as environment variables into containers at runtime via IAM task execution roles. |
| **Authentication** | None (Local multi-user sessions not isolated) | JWT / OAuth2 / OIDC (Auth0, AWS Cognito, or Supabase) | **Yes** | Add FastAPI security dependency (`HTTPBearer`) on `/api/*`. Bind `user_id` to document metadata and conversation models. |
| **Logging** | Console logging with local timestamps (`logging.py`) | Structured JSON logging to Datadog, AWS CloudWatch, or Grafana Loki | **Yes** | Format standard logging stream as JSON with request IDs and user IDs for distributed tracing. |
| **Monitoring** | In-memory latency & token telemetry (`telemetry.py`) | Prometheus + OpenTelemetry + Grafana / Datadog APM | **Yes** | Export telemetry metrics via `/metrics` endpoint; track P95 latency, embedding cost, and LLM token usage. |
| **CI/CD** | Manual execution (`pytest`, local scripts) | GitHub Actions / GitLab CI pipeline | **Yes** | Automated linting, pytest suite, security scanning (Trivy), container build, and staging/prod CD deployment. |
| **Domain & DNS** | `localhost:8000` | Custom domain (e.g., `legal-qa.company.com`) via Route 53 / Cloudflare | **Yes** | Point apex/subdomain CNAME to Load Balancer with edge caching and rate limiting. |
| **HTTPS / TLS** | Plain HTTP | Automated TLS 1.3 certificates via AWS ACM / Let's Encrypt | **Yes** | Strict HTTPS enforcement with HSTS headers. |

---

## 3. What Does NOT Need To Change

To ensure stability and maintainability, core architectural abstractions have been decoupled from specific deployment targets. The following components remain **100% unchanged** between development and production:

1. **Frontend API Contracts (`/api/*`)**:
   - `POST /api/documents/upload` (File upload and validation)
   - `GET /api/documents` (Listing documents and metadata)
   - `POST /api/chat` (Multi-turn legal Q&A request and response payload)
   - `GET /api/chat/history/{conv_id}` and `GET /api/conversations` (Persistence APIs)
   - `GET /api/health` (Service health status)
2. **Document & Conversation Domain Models**:
   - `DocumentMetadata`, `DocumentChunk`, `PageContent` (`app/models/document.py`)
   - `ChatRequest`, `ChatResponse`, `Citation` (`app/models/chat.py`)
   - `DocumentStructure`, `Article`, `Section`, `Clause` (`app/models/structure.py`)
3. **Legal Document Intelligence Engine**:
   - `StructureParser` (`app/services/structure_parser.py`): Hierarchical parsing of legal articles, sections, clauses, definitions, and cross-references.
   - `ChunkingService` (`app/services/chunking_service.py`): Legal boundary-aware chunking preserving numbering and section titles.
   - `Legal Reasoning Modules` (`app/services/legal_reasoning.py`): `ConflictDetector`, `TemporalReasoner`, `ObligationExtractor`, and `RiskAnalyzer`.
4. **Agent Orchestration & Tool Hierarchy**:
   - `IntentRouter` (`app/services/intent_router.py`): 7-intent deterministic classification.
   - Deterministic tools (`MetadataTool`, `ProfileTool`, `SectionStructureTool`): Execute without LLM token cost.
   - Grounded context synthesis: System prompt security boundary preventing prompt injection from uploaded files (`CONTEXT_START_TAG`).
5. **Database ORM Abstraction**:
   - `app/persistence/models.py` uses standard SQLAlchemy models (`ConversationModel`, `MessageModel`, `DocumentProfileModel`).
   - `DatabaseManager` (`app/persistence/database.py`) already detects PostgreSQL connection strings (`DATABASE_URL.startswith("sqlite") == False`) and automatically configures connection pooling (`pool_size=10`, `max_overflow=20`, `pool_pre_ping=True`).
6. **Pluggable Provider Architecture**:
   - `BaseLLMProvider` and `BaseEmbeddingProvider` interfaces allow switching between local mock, TF-IDF, Gemini, Grok, and OpenAI via configuration without modifying business logic.

---

## 4. Exact Migration Sequence

Follow this phased sequence to migrate from a local development instance to an enterprise cloud production environment.

```text
Phase 1: Production Infrastructure Provisioning
Phase 2: Secrets & Environment Configuration
Phase 3: Relational Database Initialization & Migration
Phase 4: Document Storage (Object Store) Setup
Phase 5: Managed Vector & Search Infrastructure Setup
Phase 6: Container Build & Application Deployment
Phase 7: Document Re-Indexing & Verification
Phase 8: Retrieval & LLM Generation Validation
Phase 9: Production Acceptance Testing (Rental Battery)
Phase 10: DNS Cutover & Traffic Routing
Phase 11: Real-time Telemetry & Monitoring Verification
Phase 12: Development Infrastructure Decommissioning
```

### Phase 1: Production Infrastructure Provisioning
- **Action**: Provision VPC, public/private subnets, Application Load Balancer (ALB), ECS Fargate/EKS cluster, managed RDS PostgreSQL instance, and S3/GCS bucket.
- **Where Configured**: Terraform / AWS CloudFormation / Pulumi.
- **Expected Result**: Network endpoints ready for API compute, database, and storage.
- **Validation**: Verify network reachability and security group ingress/egress rules.

### Phase 2: Secrets & Environment Configuration
- **Action**: Store sensitive keys in AWS Secrets Manager or Vault:
  - `LLM_API_KEY`, `EMBEDDING_API_KEY`, `DATABASE_URL`, `QDRANT_API_KEY`.
- **Where Configured**: Secrets Manager ARN mapped to container task definition environment.
- **Expected Result**: Secrets injected securely at container startup without disk persistence.
- **Validation**: Run container task echo inspection verifying variable injection without exposing values.

### Phase 3: Relational Database Initialization & Migration
- **Action**: Initialize production PostgreSQL tables.
- **Where Configured**: Database connection string set via `DATABASE_URL`.
- **Commands**:
  ```bash
  # Ensure psycopg2 or asyncpg is available
  pip install psycopg2-binary
  # Execute schema initialization via application startup or migration tool
  python -c "from app.persistence.database import DatabaseManager; db = DatabaseManager(); print('DB Initialized')"
  ```
- **Expected Result**: Tables `conversations`, `messages`, and `document_profiles` created with primary keys and foreign key constraints.
- **Validation**:
  ```sql
  SELECT table_name FROM information_schema.tables WHERE table_schema='public';
  ```

### Phase 4: Document Storage Setup
- **Action**: Create production S3 bucket (e.g., `legal-qa-documents-prod`) with private access, versioning, and SSE-S3/KMS encryption.
- **Where Configured**: S3 bucket policy and IAM Role assigned to the ECS task.
- **Expected Result**: Application has read/write access to object storage.
- **Validation**: Upload and delete a test object using AWS CLI with the task role credentials.

### Phase 5: Managed Vector & Search Infrastructure Setup
- **Action**: Provision managed Qdrant Cloud cluster or standalone containerized Qdrant instance.
- **Where Configured**:
  - `QDRANT_URL=https://<cluster-id>.qdrant.io:6333`
  - `QDRANT_API_KEY=<qdrant-cloud-token>`
- **Expected Result**: Vector store endpoint accessible via HTTPS.
- **Validation**:
  ```bash
  curl -H "api-key: $QDRANT_API_KEY" "$QDRANT_URL/collections"
  ```

### Phase 6: Container Build & Application Deployment
- **Action**: Build production container image using repository Dockerfile and deploy to container registry (ECR/GCR).
- **Commands**:
  ```bash
  docker build -t legal-qa-assistant:prod -f Dockerfile .
  docker tag legal-qa-assistant:prod <account_id>.dkr.ecr.<region>.amazonaws.com/legal-qa:prod
  docker push <account_id>.dkr.ecr.<region>.amazonaws.com/legal-qa:prod
  ```
- **Expected Result**: ECS service updates task definition and spawns healthy tasks.
- **Validation**: Check task health endpoint: `GET http://<alb-endpoint>/api/health` returns `HTTP 200`.

### Phase 7: Document Ingestion / Migration
- **Action**: Migrate legal PDFs from development or source repositories to production storage and index them.
- **Commands**: Run re-indexing procedure (see Section 8).
- **Expected Result**: Document chunks stored, embeddings generated, and vectors written to Qdrant collection.
- **Validation**: Verify point count in Qdrant matches total chunk count across documents.

### Phase 8: Retrieval & LLM Generation Validation
- **Action**: Query `/api/chat` with reference legal queries (notice period, cure period, indemnification).
- **Expected Result**: Verified grounded answers with accurate citations (document name, page, clause).
- **Validation**: Execute automated integration smoke test against the staging ALB URL.

### Phase 9: Production Acceptance Testing
- **Action**: Run the complete 31-query Legal QA Benchmark Suite against the production endpoint.
- **Commands**:
  ```bash
  APP_ENV=production LLM_PROVIDER=gemini PYTHONPATH=. python -m pytest tests/unit/ -v
  ```
- **Expected Result**: 100% pass rate on legal intelligence benchmarks.

### Phase 10: DNS Cutover & Traffic Routing
- **Action**: Update Route 53 / Cloudflare DNS records to route production domain to ALB.
- **Expected Result**: Live user traffic directed to new production infrastructure.
- **Validation**: Verify live HTTPS handshake and traffic appearance in ALB logs.

### Phase 11: Real-time Telemetry & Monitoring Verification
- **Action**: Observe error rates, request latency, and token consumption dashboards.
- **Expected Result**: Telemetry logs streaming to centralized aggregator without 5xx spikes.
- **Validation**: CloudWatch / Datadog latency alarm threshold confirmed active.

### Phase 12: Development Infrastructure Decommissioning
- **Action**: Archive development SQLite database, delete local temporary upload directories (`data/uploads`), and revoke development API test keys.
- **Expected Result**: Clean separation; zero orphaned test data.

---

## 5. Environment & Secrets Migration

The following table provides an exhaustive mapping of every environment variable in the application, comparing development settings to production requirements:

| Variable | Development Value | Production Target / Source | Required? | Secret? | Needs Changing? | Purpose & Constraints |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `APP_NAME` | `"Legal Document QA Assistant"` | `"Legal Document QA Assistant"` | Yes | No | No | Application branding |
| `APP_ENV` | `development` | `production` | Yes | No | **Yes** | Enables production security guards |
| `DEBUG` | `true` | `false` | Yes | No | **Yes** | Disables OpenAPI docs exposure and verbose traces |
| `PORT` | `8000` | `8000` | Yes | No | No | Container port |
| `HOST` | `0.0.0.0` | `0.0.0.0` | Yes | No | No | Bind interface |
| `UPLOAD_DIR` | `data/uploads` | S3 bucket path / `/mnt/shared/uploads` | Yes | No | **Yes** | Path for staging raw document uploads |
| `VECTOR_STORE_DIR` | `data/vector_store` | `/tmp/vector_cache` | Yes | No | **Yes** | Local cache directory for vectors/chunks |
| `DATABASE_PATH` | `data/legal_qa.db` | *Ignored when DATABASE_URL is set* | No | No | No | SQLite fallback path |
| `DATABASE_URL` | *Empty (defaults to SQLite)* | `postgresql://usr:pwd@rds.endpoint:5432/legal_qa` | **Yes** | **Yes** | **Yes** | Managed PostgreSQL connection string |
| `MAX_FILE_SIZE_MB` | `25` | `25` (or configured per enterprise policy) | Yes | No | Optional | Maximum allowed upload file size |
| `MAX_DOCUMENT_PAGES`| `500` | `500` | Yes | No | No | Hard page limit for uploaded documents |
| `MAX_CHUNKS_PER_DOC`| `5000` | `5000` | Yes | No | No | Memory limit guard |
| `CHUNK_SIZE` | `500` | `500` | Yes | No | No | Chunk character size target |
| `CHUNK_OVERLAP` | `100` | `100` | Yes | No | No | Chunk overlap |
| `MIN_CHUNK_SIZE` | `50` | `50` | Yes | No | No | Suppresses micro-fragments |
| `TOP_K` | `4` | `4` (or `6` for complex multi-clause contracts) | Yes | No | Optional | Candidate chunks fed to LLM context |
| `MAX_TOP_K` | `10` | `10` | Yes | No | No | Hard upper limit on retrieval candidates |
| `SIMILARITY_THRESHOLD`| `0.10` | `0.15` | Yes | No | Optional | Minimum cosine similarity threshold |
| `RELEVANCE_CONFIDENCE_THRESHOLD`| `0.35` | `0.35` | Yes | No | No | Minimum confidence for semantic gate |
| `MIN_CONTENT_WORD_OVERLAP`| `0.35` | `0.35` | Yes | No | No | Lexical grounding overlap ratio |
| `MAX_CONTEXT_CHARS` | `8000` | `12000` | Yes | No | Optional | Context budget for LLM prompt |
| `MAX_QUERY_CHARS` | `2000` | `2000` | Yes | No | No | Query length boundary validation |
| `MAX_PROMPT_TOKENS` | `4096` | `8192` | Yes | No | Optional | Prompt token budget |
| `MAX_OUTPUT_TOKENS` | `1024` | `2048` | Yes | No | Optional | Maximum response generation budget |
| `MAX_HISTORY_TURNS` | `3` | `4` | Yes | No | Optional | Bounded multi-turn context window |
| `MAX_HISTORY_TOKENS`| `500` | `1000` | Yes | No | Optional | Token budget for chat history |
| `CORS_ALLOWED_ORIGINS`| `*` | `https://app.yourdomain.com,https://dashboard.yourdomain.com` | Yes | No | **Yes** | Comma-separated allowed CORS origins |
| `RAG_PROVIDER` | `local` | `local` (managed Qdrant) or `xai` | Yes | No | Optional | RAG backend provider (`local`, `xai`, `grok`) |
| `XAI_API_KEY` | *Empty* | Cloud Secret Manager | Conditional | **Yes** | **Yes** | Required if `RAG_PROVIDER=xai` or `LLM_PROVIDER=xai` |
| `XAI_BASE_URL` | `https://api.x.ai/v1` | `https://api.x.ai/v1` | No | No | No | xAI API base endpoint |
| `XAI_COLLECTION_ID` | *Empty* | `legal_documents_prod` | Conditional | No | Optional | Remote collection ID when using xAI RAG |
| `LLM_PROVIDER` | `gemini` (or `mock`) | `gemini` / `grok` / `openai` | Yes | No | **Yes** | Production LLM provider selection |
| `LLM_API_KEY` | Development key in `.env` | Cloud Secret Manager / IAM | **Yes** | **Yes** | **Yes** | Secret API key for generation |
| `LLM_MODEL` | `gemini-3.8-flash` | `gemini-3.8-flash` or `grok-beta` | Yes | No | Optional | Target model name |
| `LLM_BASE_URL` | *Empty* | Custom endpoint (if using proxy/gateway) | No | No | Optional | Base URL override |
| `LLM_TEMPERATURE` | `0.0` | `0.0` | Yes | No | No | Keep 0.0 for deterministic factual legal Q&A |
| `EMBEDDING_PROVIDER`| `gemini` (or `tfidf`) | `gemini` or `openai` | Yes | No | **Yes** | Production dense embedding provider |
| `EMBEDDING_API_KEY` | Development key in `.env` | Cloud Secret Manager | **Yes** | **Yes** | **Yes** | Secret API key for embeddings |
| `EMBEDDING_MODEL` | `gemini-embedding-2` | `gemini-embedding-2` (dim=3072) | Yes | No | Optional | Target embedding model |
| `EMBEDDING_BASE_URL`| *Empty* | Custom endpoint (if using proxy) | No | No | Optional | Base URL override |
| `OCR_PROVIDER` | `local` | `local` (worker) or cloud OCR API | Yes | No | Optional | OCR extraction engine |
| `OCR_API_KEY` | *Empty* | Cloud Secret Manager (if external OCR) | No | **Yes** | Optional | OCR API key |
| `QDRANT_URL` | `http://localhost:6333` | `https://<cluster-id>.qdrant.io:6333` | Optional | No | **Yes** | Managed Qdrant cluster endpoint (when using external Qdrant server) |
| `QDRANT_API_KEY` | *Empty* | Cloud Secret Manager | Optional | **Yes** | **Yes** | Qdrant Cloud access token |

> [!CAUTION]
> Never commit actual API keys or secrets into source control or Docker images. In production, pass secrets directly through your orchestration environment (AWS ECS Task Definition Secrets, Kubernetes Secrets, or Cloud Run Environment Secrets).

---

## 6. Document & Data Migration

Migrating state from development to production requires handling three distinct tiers: binary document files, relational conversation histories, and vector embeddings.

### 6.1 Uploaded Binary Documents
* **Development Location**: `data/uploads/` on the local file system.
* **Production Location**: Managed Cloud Object Storage (`s3://<prod-legal-bucket>/documents/`).
* **Migration Strategy**:
  1. Do **not** bulk copy unverified development test PDFs (such as `test_*.pdf` or dummy files) into production.
  2. For official baseline agreements (e.g. Master Services Agreements, Rental Agreements):
     ```bash
     # Copy validated legal agreements to production S3 bucket
     aws s3 cp ./documents/ s3://prod-legal-bucket/documents/ --recursive --exclude "*.tmp"
     ```
  3. Update `DocumentService` to retrieve documents via S3 pre-signed URLs or an S3 storage backend rather than direct `open(local_path, "rb")`.

### 6.2 Relational Database Migration (SQLite → PostgreSQL)
* **Status**: Development uses SQLite (`data/legal_qa.db`); production requires PostgreSQL.
* **Migration Mechanism**:
  - The repository's ORM (`app/persistence/models.py`) is database-agnostic.
  - Development SQLite conversation threads and test runs contain transient testing state and should **not** be blindly dumped into production.
  - To migrate clean historical consultations if required:
    ```bash
    # Extract records using Python script into JSON, then import into Postgres
    # (NOT IMPLEMENTED AS A STANDALONE CLI SCRIPT — custom data migration script required if migrating old conversations)
    ```
  - For schema provisioning, running the application with `DATABASE_URL=postgresql://...` automatically executes `Base.metadata.create_all(bind=self.engine)` safely without dropping data.
  - Production recommendation: Integrate **Alembic** for tracked, version-controlled database migrations before production cutover.

### 6.3 Vector Index & Dimension Compatibility
* **Can development vectors be copied directly to production?**
  - **No.** Development uses local files (`data/vector_store/<doc_id>_vectors.npy`, `qdrant_db/`), which are bound to the local embedded file system and local architecture.
  - Furthermore, if the embedding provider or model changes (e.g., from local `tfidf` to `gemini-embedding-2`), vector dimensions and mathematical spaces are completely incompatible.
* **Re-Indexing Requirement**:
  - All production documents **must be ingested and re-indexed cleanly** in the production environment.
  - The application's `VectorStore` automatically validates dimensions on startup and query time via `EmbeddingDimensionMismatchError`. Stale vectors are rejected.

### 6.4 Embeddings Reusability
* Vector embeddings are non-transferable across different models:
  - `tfidf`: 1024 dimensions (sparse local vocabulary)
  - `fastembed` (`BAAI/bge-small-en-v1.5`): 384 dimensions
  - `text-embedding-3-small`: 1536 dimensions
  - `gemini-embedding-2`: 3072 dimensions
* Whenever `EMBEDDING_PROVIDER` or `EMBEDDING_MODEL` is modified, **all documents must be re-embedded**.

---

## 7. Provider Migration: Local → Production Managed RAG

### 7.1 Transitioning to Option A: Managed Qdrant + Gemini / Grok LLM

```text
Local Embedded Storage / SQLite
               ↓
Managed Qdrant Cloud + Cloud SQL Postgres + Gemini/Grok API
```

1. **Step 1: Set Up Qdrant Cloud Cluster**:
   - Create a cluster on [cloud.qdrant.io](https://cloud.qdrant.io).
   - Generate an API Key with collection management permissions.
   - Note the HTTPS cluster URL: `https://<id>.us-east-1-0.aws.cloud.qdrant.io:6333`.
2. **Step 2: Configure Environment Variables**:
   ```env
   QDRANT_URL="https://<id>.us-east-1-0.aws.cloud.qdrant.io:6333"
   QDRANT_API_KEY="<production-qdrant-key>"
   EMBEDDING_PROVIDER="gemini"
   EMBEDDING_API_KEY="<production-google-key>"
   EMBEDDING_MODEL="gemini-embedding-2"
   LLM_PROVIDER="gemini"
   LLM_API_KEY="<production-google-key>"
   LLM_MODEL="gemini-3.8-flash"
   ```
3. **Step 3: Point VectorStore to Remote Qdrant**:
   - In `app/services/vector_store.py`, ensure `QdrantClient` connects via URL and API key when `QDRANT_URL` is set to an external address:
     ```python
     if settings.QDRANT_URL.startswith("http"):
         self.qdrant_client = QdrantClient(
             url=settings.QDRANT_URL,
             api_key=settings.QDRANT_API_KEY or None
         )
     ```
4. **Step 4: Ingest Production Documents**:
   - Upload documents via the `/api/documents/upload` endpoint.
5. **Step 5: Run Acceptance Smoke Tests**:
   - Issue test queries and verify Qdrant cloud console shows point count increases and search latency is under 15ms.

---

### 7.2 Transitioning to Option B: Fully Managed xAI Production RAG

```text
Local Parsing & Retrieval Pipeline
               ↓
xAI Collections + xAI Server-side Hybrid Search + Grok
```

If the organization selects xAI's managed platform for production document retrieval, the migration path requires delegating the chunking and vector storage to xAI's native Collections API:

1. **Step 1: Provision xAI Enterprise Credentials**:
   - Generate an API key from the xAI Developer Console (`https://console.x.ai`).
   - Store the key securely as `XAI_API_KEY`.
2. **Step 2: Create Production Collection in xAI**:
   - Issue a request to create a legal document collection:
     ```bash
     curl https://api.x.ai/v1/collections \
       -H "Authorization: Bearer $XAI_API_KEY" \
       -H "Content-Type: application/json" \
       -d '{"name": "production_legal_documents", "description": "Master legal contracts repository"}'
     ```
3. **Step 3: Upload and Ingest Documents into xAI Collection**:
   - Upload file to xAI Files API:
     ```bash
     curl https://api.x.ai/v1/files \
       -H "Authorization: Bearer $XAI_API_KEY" \
       -F "file=@./documents/Master_Services_Agreement.pdf" \
       -F "purpose=rag"
     ```
   - Ingest uploaded file into the collection created in Step 2.
4. **Step 4: Configure xAI Provider in Application**:
   - Set environment variables:
     ```env
     LLM_PROVIDER="grok"
     LLM_API_KEY="<production-xai-key>"
     LLM_MODEL="grok-beta"
     LLM_BASE_URL="https://api.x.ai/v1"
     ```
5. **Step 5: Update Application Routing**:
   - Route retrieval through xAI's tool-calling completion interface (`search_collection` tool) or query synthesis endpoint.
   - Map application document IDs (`doc_123`) to xAI's remote file/document UUIDs.
6. **Step 6: Validate Answer Grounding**:
   - Verify that Grok returns citations referencing the uploaded documents and that safety guardrails prevent prompt injection.

---

## 8. Re-Indexing Strategy

### 8.1 When is Re-Indexing Required vs. NOT Required?

| Trigger Event | Re-Indexing Required? | Explanation |
| :--- | :--- | :--- |
| **Switching Embedding Model** (e.g. TF-IDF → Gemini 2) | **YES (Mandatory)** | Vector dimensions and semantic geometry change completely. Old vectors cannot be queried. |
| **Switching Embedding Dimensions** | **YES (Mandatory)** | Cosine similarity calculation will fail with `EmbeddingDimensionMismatchError`. |
| **Changing Chunk Size / Overlap** | **YES (Mandatory)** | Existing chunks in the vector store represent stale text boundaries. |
| **Modifying Legal Structure Parser** | **YES (Recommended)** | If clause/article detection regexes improve, chunks must be rebuilt to reflect updated metadata. |
| **Changing Retrieval Provider** (Local Qdrant → Managed Qdrant) | **YES (Mandatory)** | Data must be seeded into the remote cluster. |
| **Switching LLM Model Only** (Gemini Flash → Grok / GPT-4o) | **NO** | LLM generation operates over retrieved text chunks; embedding indices remain valid. |
| **Updating Database Schema** | **NO** | Document chunks and vectors reside in Qdrant, independent of relational metadata tables. |
| **Modifying System Prompt / Citation Validator** | **NO** | Prompts and citation verification occur dynamically at inference time. |

---

### 8.2 How to Re-Index Documents

#### Re-Indexing a Single Document
1. Delete the existing document via the API:
   ```bash
   curl -X DELETE "http://localhost:8000/api/documents/doc_123"
   ```
   *This automatically removes chunks and vectors from `VectorStore`, deletes the local Qdrant collection `doc_123`, and clears metadata cache.*
2. Re-upload the original PDF file:
   ```bash
   curl -X POST "http://localhost:8000/api/documents/upload" \
     -F "file=@./documents/Contract.pdf"
   ```

#### Re-Indexing All Documents
*Current Repository Status*: The application automatically checks compatibility on startup or upload. If the configured embedding model or provider differs from a document's stored metadata (`_meta.json`), `DocumentService.process_document` automatically detects the mismatch, wipes the stale collection, and re-indexes.

To trigger an explicit full re-index in production:
```bash
# NOT IMPLEMENTED AS A STANDALONE CLI SCRIPT — Recommended production CLI command:
# python -m scripts.reindex_all --force --provider=gemini --model=gemini-embedding-2
```
*Current Manual Procedure*:
1. Clear the vector store directory or drop the remote Qdrant collection:
   ```bash
   # Caution: Clears all vector data
   rm -rf data/vector_store/*
   ```
2. Loop through raw PDF files in storage and POST them to `/api/documents/upload`.

#### Detecting Failed Indexing
1. Check `data/vector_store/<doc_id>_meta.json` or query Qdrant collection info:
   ```bash
   curl "http://localhost:6333/collections/doc_123"
   ```
2. If `points_count` == 0 or `status` != `"green"`, indexing failed.
3. Review application logs for:
   - `PageLimitExceededError` (exceeded `MAX_DOCUMENT_PAGES`)
   - `ScannedPDFError` (OCR failed or text unextractable)
   - `EmbeddingDimensionMismatchError`

---

## 9. Zero-Downtime / Cutover Strategy

> [!IMPORTANT]
> **Can the current application perform a live zero-downtime cutover without architectural adjustments?**  
> **No.** In its default local setup, the application relies on an embedded SQLite database and a local embedded Qdrant instance with file locks. Attempting to switch providers or restart containers concurrently will result in file lock contention or temporary service interruption.

To achieve **zero-downtime cutover** during production migration, use the following **Blue/Green Deployment Strategy**:

```text
                  [Production Route 53 / Cloudflare DNS]
                                    │
                  ┌─────────────────┴─────────────────┐
                  │ (100% Traffic)                    │ (0% Staging Traffic)
                  ▼                                   ▼
        [Blue Environment]                  [Green Environment]
      - Existing/Dev Setup               - Production Infrastructure
      - Local SQLite / Qdrant            - Managed PostgreSQL (Aurora)
      - Development Keys                 - Managed Qdrant Cloud
                                         - Production Gemini/Grok Keys
                                                      │
                                                      ▼
                                         1. Pre-seed DB & Documents
                                         2. Ingest & Index all PDFs
                                         3. Run Benchmark Suite (31/31)
                                         4. Smoke test /api/chat
                                                      │
                  ▲                                   │
                  │ (Flip DNS to 100% Green)          │
                  └───────────────────────────────────┘
```

### Cutover Execution Steps:
1. **Pre-provision Green Environment**: Deploy the containerized application to ECS/Kubernetes connected to RDS PostgreSQL and Qdrant Cloud.
2. **Pre-seed Documents & Ingestion**: Ingest and embed all production documents in the Green environment while Blue continues serving live read requests.
3. **Verify Index Integrity**: Verify that chunk counts and vector counts on Green match expected totals.
4. **Execute Synthetic Test Suite**: Run the 31-query Legal QA Benchmark Suite against the Green staging endpoint.
5. **DNS Weight Adjustment**: Shift DNS weight from Blue to Green gradually (`90/10` -> `50/50` -> `0/100`) over a 15-minute window.
6. **Retire Blue**: Monitor Green error rates for 60 minutes. Once stable, spin down Blue compute instances.

---

## 10. Rollback Plan

If the production deployment experiences fatal errors (e.g. rate limit exhaustion on remote LLMs, database connection pool exhaustion, or degraded retrieval accuracy), execute this rollback procedure immediately:

### Rollback Procedure:
1. **DNS Reversion**:
   - Immediately switch DNS traffic back to the previous stable Blue environment.
   - TTL must be set to 60 seconds prior to migration to ensure rapid propagation.
2. **Configuration Fallback**:
   - If rolling back within the same container cluster, update environment variables:
     ```env
     # Revert from external provider to stable local/fallback provider
     LLM_PROVIDER=gemini
     EMBEDDING_PROVIDER=gemini
     # Or revert to mock/local fallback in emergency:
     # LLM_PROVIDER=mock
     # EMBEDDING_PROVIDER=tfidf
     ```
3. **State & Data Implications**:
   - **Indexed Documents**: Documents indexed in Qdrant Cloud remain intact; reverting the container configuration does not delete cloud collections.
   - **Conversations**: Conversations recorded in PostgreSQL during the cutover window will remain in PostgreSQL. If falling back to SQLite, conversations created during the cutover window will not appear unless synchronized.
   - **Uploaded Files**: Files stored in S3 remain unaffected.

---

## 11. Production Security Checklist

Ensure all items are verified before enabling public production traffic:

- [ ] **API Keys & Secrets**: All API keys removed from source code, Dockerfiles, and `.env`. Injected at runtime via AWS Secrets Manager or Kubernetes Secrets.
- [ ] **HTTPS / TLS 1.3**: All traffic strictly encrypted in transit. HTTP port 80 permanently redirects to HTTPS 443 with HSTS headers.
- [ ] **CORS Hardening**: Replace `allow_origins=["*"]` in `app/main.py` with explicit allowed production domain names (`https://legal-qa.company.com`).
- [ ] **Authentication & Authorization**: Implement OAuth2 / JWT authentication middleware. Ensure users can only query and view documents permitted by their tenant role.
- [ ] **Document Access Isolation**: Validate that `/api/documents/{id}/file` enforces tenant boundaries to prevent unauthorized downloads of confidential contracts.
- [ ] **Untrusted Evidentiary Boundary**: Verify that `CONTEXT_START_TAG` (`<context_document_data>`) and system prompt hierarchy are active in all LLM prompts to prevent prompt injection.
- [ ] **Rate Limiting & Request Budgeting**: Implement rate limiting per IP / API key (e.g., 60 requests/minute via Redis token bucket or Cloudflare WAF).
- [ ] **Payload Sanitization & Limits**: Ensure `MAX_FILE_SIZE_MB` (25MB), `MAX_QUERY_CHARS` (2000), and `MAX_DOCUMENT_PAGES` (500) boundaries are strictly enforced.
- [ ] **Database Connection Security**: Enable SSL mode (`sslmode=require`) on PostgreSQL connections.
- [ ] **Sanitized Logging**: Ensure no raw document text, personally identifiable information (PII), or API keys are written to standard output or error logs.

---

## 12. Scaling Considerations & Bottleneck Analysis

As active usage grows from a single developer to thousands of concurrent legal practitioners, system components will encounter scaling limits in a predictable sequence:

```text
Concurrent Users:
   1 user       →       10 users       →       100 users       →       1000+ users
[Dev Laptop]     [Single Container]     [Auto-scaled API]        [Distributed Queue &
                                         + Managed DB]           Dedicated Search Grid]
```

### Bottleneck Sequence & Remediation:

#### 1. Ingestion / OCR & PDF Parsing (First Bottleneck: ~5–10 concurrent uploads)
* **Cause**: PyMuPDF and RapidOCR are CPU-bound and block the Python GIL if executed in the main thread.
* **Remediation**:
  - Offload `/api/documents/upload` processing to an asynchronous Celery / AWS SQS worker pool.
  - Return `202 Accepted` with a job ID and notify frontend via WebSockets or polling when indexing completes.

#### 2. LLM Provider Rate Limits & Quotas (~20–50 concurrent users)
* **Cause**: Cloud providers (Gemini, Grok, OpenAI) enforce strict Tier-based RPM (requests per minute) and TPM (tokens per minute) quotas.
* **Remediation**:
  - Implement an exponential backoff retry mechanism with jitter.
  - Provision enterprise Tier commitments or multi-provider load balancing (e.g. fallback to Grok if Gemini returns HTTP 429).

#### 3. Database Connection Pool (~100 concurrent users)
* **Cause**: SQLite locks files during writes (`database is locked`). In PostgreSQL, excessive stateless container replicas can exhaust database connections.
* **Remediation**:
  - Deploy **PgBouncer** in front of PostgreSQL for connection pooling.
  - Utilize read replicas for conversation history queries.

#### 4. Vector Search & Lexical Fusion (~200+ concurrent queries)
* **Cause**: In-memory BM25 Okapi calculation in `retrieval_service.py` consumes CPU and memory per query on the web tier.
* **Remediation**:
  - Offload lexical search to an external search cluster (e.g., Qdrant Sparse Vectors or OpenSearch).
  - Cache frequent search results and query embeddings in Redis.

---

## 13. Development Cost vs. Production Cost

| Component | Development Setup (Cost) | Production Setup (Cost Basis) | Cost Driver / Optimization |
| :--- | :--- | :--- | :--- |
| **API Compute** | **$0.00** (Local developer machine) | **$30 – $150 / month** | AWS ECS Fargate (2–4 tasks, 0.5 vCPU, 1GB RAM) or GCP Cloud Run |
| **Database** | **$0.00** (Local SQLite file) | **$15 – $70 / month** | AWS RDS PostgreSQL `db.t4g.micro` or Aurora Serverless v2 |
| **Document Storage** | **$0.00** (Local disk) | **$1 – $10 / month** | AWS S3 Standard ($0.023/GB/month + data transfer) |
| **Vector DB** | **$0.00** (Local embedded Qdrant) | **$0 – $45 / month** | Qdrant Cloud Free Tier (1GB cluster) or standard tier |
| **Embeddings** | **$0.00** (Free Gemini Tier or TF-IDF) | **~$0.00002 / 1k tokens** | Gemini Embedding 2 / OpenAI `text-embedding-3-small`. Batch embeddings on upload. |
| **LLM Generation** | **$0.00** (Free tier / Mock) | **$5 – $50 / 1M tokens** | Paid token billing: Gemini 3.8 Flash (~$0.15/1M input tokens), Grok-beta, or GPT-4o. |
| **Monitoring & Logs** | **$0.00** (Standard output) | **$5 – $30 / month** | AWS CloudWatch Logs / Datadog APM |
| **Domain & DNS** | **$0.00** (`localhost`) | **$12 / year** | Route 53 domain registration + hosted zone ($0.50/mo) |
| **TLS Certificate** | **$0.00** (Self-signed / none) | **$0.00** (Free) | AWS Certificate Manager (ACM) or Let's Encrypt |

> [!NOTE]
> If using **xAI Grok / xAI Collections** in production, note that xAI is a paid cloud service requiring active billing credits. The development environment maintains a 100% free local option via Mock providers and local TF-IDF embeddings.

---

## 14. Production Acceptance Checklist

Before flipping production DNS, the operations team must verify each requirement:

```text
[ ] Production environment variables configured and validated
[ ] Cloud secrets injected (no plaintext API keys in configuration)
[ ] PostgreSQL database online, migrated, and connection pool verified
[ ] Object storage bucket created with SSE encryption and IAM policies active
[ ] Remote vector database (Qdrant Cloud) reachable and healthy
[ ] Production documents ingested, chunked, and indexed
[ ] Vector dimension compatibility verified against embedding model
[ ] Retrieval pipeline verified (Dense + BM25 + Reciprocal Rank Fusion)
[ ] Grounded LLM response synthesis verified with active system prompt
[ ] Document tenant isolation and boundary checks passed
[ ] Authentication and authorization middleware enabled
[ ] HTTPS certificate active with TLS 1.3 enforced
[ ] Structured JSON logging streaming to centralized log aggregator
[ ] CloudWatch / Prometheus telemetry and alerting rules active
[ ] Error handling and rate-limiting boundaries verified
[ ] Document backup and database snapshot schedule confirmed
[ ] Rollback procedure tested in staging environment
[ ] Full Legal QA Benchmark Suite (31/31 tests) passed on production target
[ ] Production DNS routing and traffic switch enabled
```

---

## 15. Exact Migration Commands

### Development Execution
```bash
# Activate virtual environment
source venv/bin/activate

# Run local development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run existing unit test suite
PYTHONPATH=. pytest tests/unit/ -v
```

### Production Build & Deployment
```bash
# 1. Build multi-stage production Docker container
docker build -t legal-qa:latest -f Dockerfile .

# 2. Authenticate and push to Amazon ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <aws_account_id>.dkr.ecr.us-east-1.amazonaws.com
docker tag legal-qa:latest <aws_account_id>.dkr.ecr.us-east-1.amazonaws.com/legal-qa:v1.0.0
docker push <aws_account_id>.dkr.ecr.us-east-1.amazonaws.com/legal-qa:v1.0.0

# 3. Update ECS Service
aws ecs update-service --cluster legal-qa-prod --service legal-qa-api --force-new-deployment
```

### Database Migration
```bash
# Initialize schema against PostgreSQL
DATABASE_URL="postgresql://user:pass@prod-db.internal:5432/legal_qa" python -c "
from app.persistence.database import DatabaseManager
db = DatabaseManager()
print('Production database tables initialized successfully.')
"
```
*Note: For tracked schema migrations, Alembic must be added to the repository (`NOT IMPLEMENTED — migration command must be added before production migration`).*

### Document Re-Indexing
```bash
# NOT IMPLEMENTED — migration command must be added before production migration.
# Recommended command to implement:
# python -m scripts.reindex_all --source=s3://prod-legal-bucket/documents/ --qdrant-url=$QDRANT_URL
```

### Verification & Health Check
```bash
# 1. Health check verification
curl -f -s https://legal-qa.company.com/api/health | jq .

# 2. Query verification
curl -X POST https://legal-qa.company.com/api/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the notice period for early termination?", "document_id": "doc_rental_agreement"}' | jq .
```

---

## 16. Migration Decision Record (MDR)

### Architecture Decision 1: Retrieval Engine
* **Current Development RAG**:
  - In-memory numpy vector store + Local Embedded Qdrant (`data/vector_store/qdrant_db`) + Local in-memory BM25 + Reciprocal Rank Fusion (RRF).
* **Recommended Production RAG**:
  - **Managed Qdrant Cloud** + Gemini Embedding 2 + Reciprocal Rank Fusion.
* **Why**:
  - Preserves custom legal structure-aware chunking and ranking algorithms.
  - Avoids multi-container filesystem locking issues present in embedded Qdrant.
  - Delivers sub-15ms vector retrieval at scale.
* **Alternative Considered**:
  - Fully Managed xAI Collections.
* **Why Not Selected as Primary**:
  - Bypasses proprietary legal structure chunking, risks vendor lock-in, and requires ongoing paid credits for document ingestion and storage. Kept as an optional turn-key alternative.

---

### Architecture Decision 2: LLM Generation Engine
* **Current Development LLM**:
  - Google Gemini 3.8 Flash (`gemini-3.8-flash`) via `google-genai` SDK, with zero-cost Mock fallback.
* **Recommended Production LLM**:
  - Google Gemini 3.8 Flash or xAI Grok (`grok-beta`).
* **Why**:
  - Gemini 3.8 Flash delivers sub-second response times, excellent legal reasoning capabilities, large context windows, and cost efficiency.
* **Alternative Considered**:
  - Local Ollama / vLLM (self-hosted Llama 3).
* **Why Not Selected**:
  - High GPU infrastructure overhead ($300+/month per instance) and added operational maintenance compared to managed API endpoints.

---

### Architecture Decision 3: Relational Persistence
* **Current Development DB**:
  - SQLite with WAL mode (`data/legal_qa.db`).
* **Recommended Production DB**:
  - AWS RDS PostgreSQL 16+ with connection pooling.
* **Why**:
  - Fully supported by existing SQLAlchemy models (`ConversationModel`, `MessageModel`, `DocumentProfileModel`).
  - Supports high concurrent writes and multi-container access without database lock errors.
* **Alternative Considered**:
  - DynamoDB / NoSQL.
* **Why Not Selected**:
  - Unnecessary schema re-architecture when SQLAlchemy models already support PostgreSQL natively out-of-the-box.
