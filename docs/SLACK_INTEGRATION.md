# Slack Integration Guide — Legal Document QA Assistant

This guide documents the Slack integration adapter that connects Slack workspaces to the existing Legal Document QA Bot via the `/api/v1` REST API using Slack Bolt for Python and Socket Mode.

---

## 1. Architecture and Request Flow

```text
Slack Workspace (User / Channel / Thread / DM)
        │
        ▼ (Socket Mode WebSocket)
Slack Bolt Adapter (`app/integrations/slack_adapter.py`)
  ├── Mention & Command Parser (`slack_formatter.py`)
  ├── Event Deduplicator (`slack_dedup.py`)
  └── Session & Document Mapping Store (`slack_mapping_repo.py`)
        │
        ▼ (HTTP REST Requests)
FastAPI Backend Gateway (`/api/v1`)
  ├── POST /api/v1/chat
  ├── POST /api/v1/documents (PDF uploads)
  ├── GET /api/v1/documents (Listing)
  └── GET /api/v1/documents/{document_id}
        │
        ▼
Existing RAG, Chunking, Embedding, Vector Store, & LLM Services
        │
        ▼ (JSON Response with Answers & Citations)
Slack Bolt Adapter
        │
        ▼ (Blocks / Formatted Markdown)
Slack User (Grounded Answer with Page & Section Citations)
```

### Key Architectural Safeguards:
1. **Decoupled Integration**: The Slack adapter communicates exclusively via the HTTP REST API (`/api/v1`), ensuring zero duplication of retrieval, chunking, or LLM logic.
2. **Context Isolation**: Session mappings in SQLite/PostgreSQL link `{team_id}:{channel_id}:{thread_ts}:{user_id}`. Multiple users in the same channel or thread maintain strictly isolated document context and conversation histories.
3. **No Credential Leaks**: API keys, internal prompts, and raw server tracebacks are suppressed from Slack messages, displaying clean, actionable notices.
4. **Retry Protection**: An in-memory TTL deduplicator discards retried Slack events if transient network latency occurs.

---

## 2. Slack App Creation & Dashboard Configuration

To install the bot in your Slack workspace:

### 2.1 Create App
1. Go to [Slack API Apps](https://api.slack.com/apps) and click **Create New App** > **From scratch**.
2. Name your app (e.g. `LegalBot`) and select your target Slack workspace.

### 2.2 Enable Socket Mode
1. In the left navigation, select **Socket Mode**.
2. Toggle **Enable Socket Mode** to **On**.
3. Under App-Level Tokens, generate an app token named `socket-token` with scope `connections:write`.
4. Copy this token (starts with `xapp-`). This is your `SLACK_APP_TOKEN`.

### 2.3 Configure Bot Token Scopes (OAuth & Permissions)
Navigate to **OAuth & Permissions** > **Scopes** > **Bot Token Scopes** and add:
* `app_mentions:read` — Receive bot mentions (`@LegalBot`) in public/private channels.
* `chat:write` — Send answers and replies.
* `im:history` — Read direct messages sent to the bot.
* `im:read` — Access DM channel information.
* `im:write` — Initiate and send direct messages.
* `files:read` — Read and download uploaded PDF files.

### 2.4 Event Subscriptions
1. Navigate to **Event Subscriptions** and toggle **Enable Events** to **On**.
2. Under **Subscribe to bot events**, add:
   * `app_mention`
   * `message.im`
3. Click **Save Changes**.

### 2.5 Install App to Workspace
1. Navigate to **Install App** in the left sidebar and click **Install to Workspace**.
2. Authorize the permissions requested.
3. Copy the generated **Bot User OAuth Token** (starts with `xoxb-`). This is your `SLACK_BOT_TOKEN`.

---

## 3. Environment Configuration

Add the following variables to your `.env` file:

```bash
# Slack Integration Settings
SLACK_BOT_TOKEN="xoxb-your-bot-user-token"
SLACK_APP_TOKEN="xapp-your-app-level-token"
LEGAL_QA_API_BASE_URL="http://localhost:8000/api/v1"
```

A template is maintained in `.env.example`.

---

## 4. Running the System Locally

### Step 1: Start the FastAPI Backend
In your project directory, activate the virtual environment and start FastAPI:

```bash
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Verify backend health:
```bash
curl http://localhost:8000/api/v1/health
```

### Step 2: Start the Slack Adapter
In a separate terminal window, start the Slack Socket Mode daemon:

```bash
source venv/bin/activate
python -m app.integrations.slack_bot
```

You should see log output confirming connection:
```text
[INFO] [legal_qa]: Initializing Slack Integration for Legal QA Chatbot...
[INFO] [legal_qa]: Connecting to Legal QA REST API at: http://localhost:8000/api/v1
[INFO] [legal_qa]: Starting Slack Bolt Socket Mode Handler...
⚡️ Bolt app is running!
```

---

## 5. Using the Slack Bot

### Basic Questions (Phase A)
* In a channel where `@LegalBot` is invited:
  > `@LegalBot What is an NDA?`
* In a Direct Message with the bot:
  > `What are the typical remedies for breach of contract?`

### Document Selection & Follow-up Questions (Phase B)
* **List available documents**:
  > `@LegalBot list docs`
* **Select a specific document**:
  > `@LegalBot select doc_9111329e157f`
* **Ask questions against the selected document**:
  > `@LegalBot What is the notice period for early termination?`
* **Follow-up question** (retains document & conversation session in the thread):
  > `@LegalBot Who can initiate it?`
* **Reset context**:
  > `@LegalBot clear`

### PDF Uploads (Phase C)
* Attach a `.pdf` file to a direct message or channel mention.
* The bot will download the file, validate it, upload it to `POST /api/v1/documents`, index its contents, and report:
  - Document ID
  - Page count
  - Chunk count
* The uploaded document is automatically set as the active context for subsequent questions in that thread.

---

## 6. Security & Operational Considerations

1. **Authentication & Least Privilege**:
   - The bot requires only the minimum OAuth scopes for mentions, DMs, and reading uploaded files.
   - All file downloads authenticate against Slack's private download URL using the bot token.
2. **Context Isolation**:
   - The persistence model maps `{team_id}:{channel_id}:{thread_ts}:{user_id}`.
   - User A and User B querying the bot in the same channel or thread maintain separate document bindings and conversation histories.
3. **Information Disclosure Prevention**:
   - All internal HTTP errors and API timeouts are caught and sanitized.
   - No stack traces, environment variables, or secret keys are returned to Slack.
4. **Production Deployment**:
   - For continuous availability in production, deploy the Slack adapter as a background systemd service or Docker container running alongside the FastAPI web service.

