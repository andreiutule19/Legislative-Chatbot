# RAG Chatbot

A full-stack chatbot application with a ChatGPT-style interface, powered by **FastAPI** (backend), **React** (frontend), and **Google Cloud Vertex AI RAG Engine**.

## Architecture

```
┌──────────────────────────────────────────────────┐
│                   React Frontend                  │
│  ┌────────────┐  ┌────────────────────────────┐  │
│  │  Sidebar    │  │  Chat Area                 │  │
│  │  - convs    │  │  - messages + markdown     │  │
│  │  - search   │  │  - SSE streaming           │  │
│  │  - user     │  │  - code highlighting       │  │
│  └────────────┘  └────────────────────────────┘  │
└───────────────────────┬──────────────────────────┘
                        │ HTTP + SSE
┌───────────────────────▼──────────────────────────┐
│                  FastAPI Backend                   │
│  ┌──────────┐  ┌──────────┐  ┌────────────────┐  │
│  │ Auth API  │  │ Chat API │  │ RAG Service    │  │
│  │ (JWT)     │  │ (SSE)    │  │ (Vertex AI)    │  │
│  └─────┬────┘  └────┬─────┘  └───────┬────────┘  │
│        │             │                │            │
│  ┌─────▼─────────────▼────┐   ┌──────▼─────────┐ │
│  │  Redis (in-memory)      │   │  GCP Vertex AI │ │
│  │  - auth, users          │   │  RAG Engine    │ │
│  │  - conversations, msgs  │   │  + Gemini      │ │
│  └─────────────────────────┘   └────────────────┘ │
└───────────────────────────────────────────────────┘
```

### Key Design Decisions

- **Redis in-memory storage**: no disk database — all auth, user, conversation, and message data lives in Redis hashes, sorted sets, and lists. Fast, simple, and runs inside the same Docker container.
- **`yield` / async generators** for streaming: the backend uses Python `async def ... yield` generators so that token-by-token responses flow to the client via SSE without blocking the event loop — other requests continue being served.
- **Table-class pattern** (inspired by [open-webui](https://github.com/open-webui/open-webui)): each entity (`AuthsTable`, `ConversationsTable`, `MessagesTable`) encapsulates its own Redis operations so routes stay clean.
- **Separate Auth / User key spaces**: credentials (`auth:{id}`) are stored independently from user profiles (`user:{id}`), matching the open-webui architecture.

## Quick Start (Docker)

The easiest way to run the full app — one container, one command:

```bash
# 1. Create a .env from the template
cp backend/.env.example .env

# 2. Edit .env with your GCP credentials + a real SECRET_KEY

# 3. Build and run
docker compose up --build
```

The app will be available at **http://localhost:8000**.

To use a different port: `PORT=3000 docker compose up --build`

### Mounting GCP credentials in Docker

If running with Vertex AI RAG, mount your Application Default Credentials:

```bash
docker compose run \
  -v "$HOME/.config/gcloud:/root/.config/gcloud:ro" \
  -e GOOGLE_APPLICATION_CREDENTIALS=/root/.config/gcloud/application_default_credentials.json \
  chatbot
```

Or add the volume to `docker-compose.yml` directly.

## Local Development (without Docker)

### Prerequisites

- Python 3.11+
- Node.js 18+
- Redis running locally (`brew install redis && redis-server`, or `apt install redis-server`)
- A Google Cloud project with Vertex AI API enabled (for RAG)
- `gcloud` CLI authenticated (`gcloud auth application-default login`)

### Backend

```bash
cd backend

python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

pip install -r requirements.txt

cp .env.example .env
# Edit .env — set REDIS_URL, GCP project ID, RAG corpus name, SECRET_KEY

uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend

npm install

cp .env.example .env
# Keep REACT_APP_API_URL=http://localhost:8000 for local dev

npm start
```

The frontend dev server runs at **http://localhost:3000** and proxies API calls to `:8000`.

## Setting Up Vertex AI RAG

1. Create a RAG corpus in your GCP project:

```python
from vertexai import rag
import vertexai

vertexai.init(project="YOUR_PROJECT", location="us-central1")

corpus = rag.create_corpus(
    display_name="my-knowledge-base",
    backend_config=rag.RagVectorDbConfig(
        rag_embedding_model_config=rag.RagEmbeddingModelConfig(
            vertex_prediction_endpoint=rag.VertexPredictionEndpoint(
                publisher_model="publishers/google/models/text-embedding-005"
            )
        )
    ),
)
print(corpus.name)  # Use this as RAG_CORPUS_NAME in .env
```

2. Import files into the corpus:

```python
rag.import_files(
    corpus.name,
    ["gs://your-bucket/docs/", "https://drive.google.com/file/d/..."],
    transformation_config=rag.TransformationConfig(
        chunking_config=rag.ChunkingConfig(chunk_size=512, chunk_overlap=100)
    ),
)
```

3. Set `RAG_CORPUS_NAME` in `backend/.env` to the corpus name from step 1.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/signup` | Create account |
| POST | `/api/auth/signin` | Sign in |
| GET | `/api/auth/me` | Get current user |
| GET | `/api/chat/conversations` | List conversations |
| POST | `/api/chat/conversations` | Create conversation |
| PUT | `/api/chat/conversations/:id` | Update conversation |
| DELETE | `/api/chat/conversations/:id` | Delete conversation |
| GET | `/api/chat/conversations/:id/messages` | Get messages |
| POST | `/api/chat/send` | Send message (SSE stream) |
