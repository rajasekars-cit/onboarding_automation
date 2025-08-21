# AI-Powered Onboarding Automation Bot

[GitHub Repository](https://github.com/rajasekars-cit/onboarding_automation)

This application provides a robust, scalable, and intelligent solution to automate multi-system user onboarding workflows. It monitors team-specific or shared mailboxes, validates requests against an identity provider (Microsoft Entra ID / Azure AD), manages complex multi-stage approval processes, and uses a local LLM (Ollama) for intelligent email analysis.

---

## Key Features

- *Multi-System Support:* Manage an unlimited number of onboarding workflows for different teams or systems simultaneously, each with its own configuration.
- *Dynamic Configuration:* All workflow settings, including mail server credentials, approvers, team aliases, and target database connections, are stored in a central PostgreSQL database. This allows for changes without redeploying code.
- *Heterogeneous Database Support:* Onboard users directly into team-specific databases, including PostgreSQL, MySQL, Oracle, and MS SQL Server, with custom table and column mappings.
- *Active Directory Integration:*
  - *Line Manager Validation:* Automatically verifies that an onboarding request comes from the user's official line manager via Microsoft Graph API.
  - *Group Membership Validation:* Ensures the user is a member of a required AD group before onboarding.
- *Multi-Stage Approval Workflows:* Supports sequential approval chains (e.g., Stage 1: Line Manager, Stage 2: IT Security).
- *Local LLM Powered:* Uses Ollama for email intent classification and entity extraction, ensuring privacy and cost control.
- *Scalable Architecture:* Producer-consumer model with thread pool for efficient handling of multiple teams.
- *Automated Notifications:* Emails for approvals, rejections (with reasons), confirmations, and reminders.

---

## Architecture

The application uses a producer-consumer model for scalability:

- *Producer Thread:* Runs on schedule (e.g., every 5 minutes). Fetches active onboarding configurations and groups them by mailbox.
- *Work Queue:* Central, thread-safe queue for tasks.
- *Consumer Thread Pool:* Worker threads process mailbox tasks, executing a two-phase workflow for all configs tied to that mailbox.

This ensures the app remains resource-efficient even with hundreds of teams.

---

## Prerequisites

- Python 3.7+ and pip  
- PostgreSQL Database  
- Ollama (with model: `llama3:8b`)  
- Microsoft Entra ID (Azure AD) account  
- Database drivers (ODBC for MS SQL Server, Oracle Instant Client, etc.)

---

## Setup Instructions

### 1. Project Setup

{code:bash}
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
{code}

### 2. Python Virtual Environment

{code:bash}
python3 -m venv venv
source venv/bin/activate   # macOS/Linux
.\venv\Scripts\activate    # Windows
pip install -r requirements.txt
{code}

### 3. Ollama Setup

{code:bash}
ollama pull llama3:8b
{code}

Ensure Ollama service is running.

### 4. Microsoft Entra ID (Azure AD) App Registration

1. Go to Microsoft Entra ID → App registrations → New registration  
2. Name: *OnboardingAutomationBot* (org-only)  
3. Copy *Application (client) ID* and *Directory (tenant) ID*  
4. Create a *client secret* under Certificates & secrets  
5. Under API Permissions add Microsoft Graph → Application permissions:  
   - `User.Read.All`  
   - `GroupMember.Read.All`  
6. Grant admin consent ✅  

### 5. Environment Configuration

Create `.env` in project root:

{code:bash}
# --- Scheduler and Worker Configuration ---
SCHEDULE_MINUTES=5
MAX_WORKER_THREADS=10
MATURITY_DELAY_MINUTES=1
INITIAL_LOOKBACK_DAYS=7
REMINDER_THRESHOLD_HOURS=24

# --- Bot Database (PostgreSQL) ---
DB_HOST="localhost"
DB_PORT="5432"
DB_NAME="onboarding_bot_db"
DB_USER="postgres"
DB_PASS="your_db_password"

# --- Ollama ---
OLLAMA_HOST="http://localhost:11434"
OLLAMA_MODEL="llama3:8b"

# --- Microsoft Graph API (Azure AD) ---
AZURE_TENANT_ID="your-directory-tenant-id"
AZURE_CLIENT_ID="your-application-client-id"
AZURE_CLIENT_SECRET="your-client-secret-value"
{code}

---

## Database Setup

The application creates operational tables on first run. You must pre-populate *mailboxes* and *configuration* tables.

### Schema Overview

- mailboxes → Mailbox credentials  
- configuration → Per-team workflows  
- onboarding_tracker → Requests, approvals, status  
- onboarding_log → Permanent onboarding records  
- processed_uids → Prevents duplicate email processing  
- app_state → Last-checked timestamps  

Includes triggers (`trigger_set_timestamp`) to auto-update `updated_at`.

### Example SQL

{code:sql}
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
{code}

---

## Running the Application

{code:bash}
python run.py
{code}

---

## Best Practices

- Use shared mailboxes for multiple teams  
- Store secrets in *Azure Key Vault* or *HashiCorp Vault*  
- Index frequently queried DB columns  
- Rotate client secrets regularly  
- Keep worker pool sizes small (5–10)

---

## Limitations

- Relies on IMAP/SMTP (no Graph mail read yet)  
- Needs local Ollama instance  
- Approval flows sequential only  
- Assumes stable DB connectivity  

---

## Next Steps

- Add parallel approvals  
- Extend AI classification with RAG  
- Cloud-hosted LLM fallback  
- Dashboard UI for monitoring  
- Support non-Azure identity providers
