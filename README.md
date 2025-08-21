# AI-Powered Onboarding Automation Bot

This application provides a robust, scalable, and intelligent solution to automate multi-system user onboarding workflows. It monitors team-specific or shared mailboxes, validates requests against an identity provider (Microsoft Entra ID / Azure AD), manages complex multi-stage approval processes, and uses a local LLM (Ollama) for intelligent email analysis.

## Key Features

- **Multi-System Support:** Manage an unlimited number of onboarding workflows for different teams or systems simultaneously, each with its own configuration.
- **Dynamic Configuration:** All workflow settings, including mail server credentials, approvers, team aliases, and target database connections, are stored in a central PostgreSQL database. This allows for changes without redeploying code.
- **Heterogeneous Database Support:** Onboard users directly into team-specific databases, including PostgreSQL, MySQL, Oracle, and MS SQL Server, with custom table and column mappings for ultimate flexibility.
- **Active Directory Integration:**
  - **Line Manager Validation:** Automatically verifies that an onboarding request comes from the user's official line manager via the Microsoft Graph API.
  - **Group Membership Validation:** Ensures the user is a member of a required AD group before initiating the onboarding process.
- **Multi-Stage Approval Workflows:** Supports complex, sequential approval chains (e.g., Stage 1: Line Manager, Stage 2: IT Security), automatically routing requests to the next stage upon completion.
- **Local LLM Powered:** Uses a local Ollama instance for email intent classification and entity extraction, ensuring data privacy and cost control.
- **Scalable Architecture:** Built on a producer-consumer model with a fixed-size thread pool, allowing it to handle hundreds of configurations efficiently without overwhelming the system.
- **Automated Notifications:** Sends automated emails for approvals, rejections (with reasons), confirmations, and reminders for pending requests.

---

## Architecture

The application uses a producer-consumer model to achieve high scalability and efficiency:

- **Producer Thread:** A single thread runs on a schedule (e.g., every 5 minutes). Its sole responsibility is to query the database for all active onboarding configurations and group them by their associated mailbox.
- **Work Queue:** The producer places each mailbox's processing task into a central, thread-safe queue.
- **Consumer Thread Pool:** A fixed number of worker threads constantly monitor the queue. When a task appears, the next available worker picks it up and executes a two-phase workflow for all configurations associated with that specific mailbox.

This design decouples task scheduling from execution, ensuring that even with hundreds of configured teams, the application's resource footprint remains small and stable.

---

## Prerequisites

- **Python 3.7+** and `pip`
- **PostgreSQL Database** for operational data
- **Ollama** running locally with a recommended model (`llama3:8b`)
- **Microsoft Entra ID (Azure AD)** account with permissions to register apps and grant API permissions
- **Database Drivers** depending on the target databases (e.g., ODBC drivers for MS SQL Server, Oracle Instant Client)

---

## Setup Instructions

### 1. Project Setup

```bash
onboarding_bot/
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── main.py
│   └── services/
│       ├── __init__.py
│       ├── ad_service.py
│       ├── ai_service.py
│       ├── db_service.py
│       └── email_service.py
├── .env
├── requirements.txt
└── run.py
```

### 2. Python Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate   # macOS/Linux
.\venv\Scripts\activate    # Windows
pip install -r requirements.txt
└── run.py
```

### 3. Ollama Setup

```bash
ollama pull llama3:8b
```
Ensure the Ollama service is running in the background.

### 4. Microsoft Entra ID (Azure AD) App Registration
1. Navigate to Microsoft Entra ID > App registrations > New registration
2. Name it `OnboardingAutomationBot`, restrict to your org
3. Copy Application (client) ID and Directory (tenant) ID
4. Create a client secret under Certificates & secrets
5. Under API Permissions add Microsoft Graph > Application permissions:
   - User.Read.All
   - GroupMember.Read.All
6. Grant admin consent

### 5. Environment Configuration
Create `.env` in project root:

```bash
# --- Scheduler and Worker Configuration ---
SCHEDULE_MINUTES=5
MAX_WORKER_THREADS=10
MATURITY_DELAY_MINUTES=1
INITIAL_LOOKBACK_DAYS=7
REMINDER_THRESHOLD_HOURS=24

# --- Bot's Own Database Configuration (PostgreSQL) ---
DB_HOST="localhost"
DB_PORT="5432"
DB_NAME="onboarding_bot_db"
DB_USER="postgres"
DB_PASS="your_db_password"

# --- Ollama Configuration ---
OLLAMA_HOST="http://localhost:11434"
OLLAMA_MODEL="llama3:8b"

# --- Microsoft Graph API (Azure AD) Configuration ---
AZURE_TENANT_ID="your-directory-tenant-id"
AZURE_CLIENT_ID="your-application-client-id"
AZURE_CLIENT_SECRET="your-client-secret-value"

```
### Database Setup

The application creates operational tables on first run. You must pre-populate mailboxes and configuration tables to define workflows.

### Schema Overview
- **mailboxes** → Stores mailbox credentials
- **configuration** → Defines per-team onboarding workflows
- **onboarding_tracker** → Tracks requests, approvals, and status
- **onboarding_log** → Permanent record of completed onboardings
- **processed_uids** → Prevents reprocessing same email
- **app_state** → Stores last-checked timestamps

Includes triggers (`trigger_set_timestamp`) to auto-update `updated_at`.

### Example SQL: Shared Mailbox & Configurations

```sql
-- Shared mailbox
INSERT INTO mailboxes
(description, imap_server, imap_user, imap_pass, smtp_server, smtp_port, smtp_user, smtp_pass)
VALUES
('Tech Teams Shared Mailbox', 'imap.gmail.com', 'tech.onboarding@yourcompany.com', 'your-app-password', 'smtp.gmail.com', 587, 'tech.onboarding@yourcompany.com', 'your-app-password')
RETURNING id;

-- DEV Team config
INSERT INTO configuration
(config_id, description, is_active, team_alias, required_ad_group, mailbox_id, target_db_type, target_db_config, target_table_name, target_column_mappings)
VALUES
('DEV_Onboarding', 'Onboarding for the DEV Team', TRUE, 'DEV Team', 'DEV', 1, 'postgresql', '{"host": "dev-db.yourcompany.com", "port": 5432, "user": "dev_user", "password": "db_password", "dbname": "devdb"}', 'users', '{"email_column": "email", "active_column": "active"}');

-- DBA Team config
INSERT INTO configuration
(config_id, description, is_active, team_alias, required_ad_group, mailbox_id, target_db_type, target_db_config, target_table_name, target_column_mappings)
VALUES
('DBA_Onboarding', 'Onboarding for the DBA Team', TRUE, 'DBA Team', 'DBA', 1, 'postgresql', '{"host": "dba-db.yourcompany.com", "port": 5432, "user": "dba_user", "password": "db_password", "dbname": "dbadb"}', 'users', '{"email_column": "email", "active_column": "active"}');

-- Update config to include access level
UPDATE configuration
SET target_column_mappings = '{"email_column": "email", "active_column": "active", "access_level_column": "access_level", "default_access_level": "rw"}'
WHERE config_id = 'DEV_Onboarding';
```

## ▶️ Running the Application
From project root with venv active:

```bash
python run.py
```

---

## ✅ Best Practices
- Use shared mailboxes for multiple small teams to reduce overhead
- Secure secrets using Azure Key Vault or HashiCorp Vault instead of plain `.env`
- Configure indexes on frequently queried columns (already included in schema)
- Rotate client secrets regularly
- Keep worker pool sizes small (5–10) unless handling high volume

---

## ⚠️ Limitations
- Relies on IMAP/SMTP connectivity; no direct Graph API mail read yet
- Requires local Ollama instance — no remote fallback
- Approval flows are sequential only (parallel not supported yet)
- Assumes stable DB connectivity

---

## 🔮 Next Steps
- Add parallel approval flows
- Extend AI classification with Retrieval-Augmented Generation (RAG)
- Optional cloud-hosted LLM fallback
- Build a dashboard UI for monitoring
- Support non-Azure identity providers