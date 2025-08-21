# ==============================================================================
# Database interaction layer for user onboarding requests.
# Manages all tables, including the 'mailboxes' table for credential
# grouping and the simplified 'configuration' table for workflow rules.
# ==============================================================================

import psycopg2
import logging
import json
import os
from psycopg2.extras import DictCursor
from datetime import datetime, timedelta
import mysql.connector
import oracledb
import pyodbc
from app.services import ad_service

def get_db_connection():
    """Establishes and returns a connection to the main PostgreSQL database."""
    try:
        return psycopg2.connect(
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASS"),
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT")
        )
    except Exception as e:
        logging.error(f"Failed to connect to application DB: {e}")
        raise

def setup_database():
    """Initializes all necessary tables and triggers in the database."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Stores unique mailbox credentials
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mailboxes (
                    id SERIAL PRIMARY KEY,
                    description TEXT,
                    imap_server TEXT NOT NULL,
                    imap_user TEXT NOT NULL,
                    imap_pass TEXT NOT NULL,
                    smtp_server TEXT NOT NULL,
                    smtp_port INT NOT NULL,
                    smtp_user TEXT NOT NULL,
                    smtp_pass TEXT NOT NULL
                );
            """)

            # Stores workflow-specific rules and links to a mailbox
            cur.execute("""
                CREATE TABLE IF NOT EXISTS configuration (
                    config_id TEXT PRIMARY KEY,
                    description TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    team_alias TEXT NOT NULL,
                    workflow_type TEXT NOT NULL DEFAULT 'ad_validated',
                    required_ad_group TEXT,
                    mailbox_id INTEGER REFERENCES mailboxes(id),
                    target_db_type TEXT,
                    target_db_config JSONB,
                    target_table_name TEXT,
                    target_column_mappings JSONB
                );
            """)

            # Other application tables (unchanged)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS onboarding_tracker (
                    id SERIAL PRIMARY KEY, user_to_onboard_email VARCHAR(255) NOT NULL,
                    requested_group VARCHAR(100) NOT NULL, config_id TEXT NOT NULL,
                    status VARCHAR(50) NOT NULL DEFAULT 'new_unprocessed', current_stage INT DEFAULT 1,
                    stage_approvals JSONB DEFAULT '{}'::jsonb, delegated_approvers JSONB DEFAULT '[]'::jsonb,
                    duplicate_of INTEGER, request_count INT DEFAULT 1, last_activity_details TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_onboard_email_group_config ON onboarding_tracker(user_to_onboard_email, requested_group, config_id);")
            cur.execute("CREATE TABLE IF NOT EXISTS onboarding_log (email TEXT NOT NULL, config_id TEXT NOT NULL, access_flag BOOLEAN DEFAULT FALSE, created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (email, config_id));")
            cur.execute("CREATE TABLE IF NOT EXISTS processed_uids (uid TEXT PRIMARY KEY, processed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP);")
            cur.execute("CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);")
            
            # Timestamp trigger (unchanged)
            cur.execute("""
                CREATE OR REPLACE FUNCTION trigger_set_timestamp() RETURNS TRIGGER AS $$
                BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
                $$ LANGUAGE plpgsql;
            """)
            cur.execute("DROP TRIGGER IF EXISTS set_timestamp ON onboarding_tracker;")
            cur.execute("CREATE TRIGGER set_timestamp BEFORE UPDATE ON onboarding_tracker FOR EACH ROW EXECUTE PROCEDURE trigger_set_timestamp();")
            conn.commit()
            logging.info("Database setup checked and completed.")

def get_last_check_time(config_id, config):
    """
    Gets the last check timestamp for a given config, applying a 30-second safety overlap.
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            key = f"last_check_timestamp_{config_id}"
            cur.execute("SELECT value FROM app_state WHERE key = %s;", (key,))
            row = cur.fetchone()
            if row and row[0]:
                last_time = datetime.fromisoformat(row[0])
                overlapped_time = last_time - timedelta(seconds=30)
                logging.info(f"[{config_id}] Last check: {last_time}. Using overlap time: {overlapped_time}")
                return overlapped_time.isoformat()

            fallback = (datetime.now() - timedelta(days=config.get('INITIAL_LOOKBACK_DAYS', 1))).isoformat()
            logging.info(f"[{config_id}] No last check timestamp found, using fallback: {fallback}")
            return fallback

def update_last_check_time(config_id, timestamp_iso):
    """Updates the last check timestamp for a given config."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            key = f"last_check_timestamp_{config_id}"
            cur.execute("INSERT INTO app_state (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;", (key, timestamp_iso))
            conn.commit()

def create_onboarding_request_composite(user_email, group, config_id, status='new_unprocessed', current_stage=1, stage_approvals=None):
    """
    Creates a new request record. The 'stage_approvals' structure is pre-populated
    with all required approvers for all stages at creation time.
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO onboarding_tracker (user_to_onboard_email, requested_group, config_id, status, current_stage, stage_approvals) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id;",
                (user_email, group, config_id, status, current_stage, json.dumps(stage_approvals or {}))
            )
            request_id = cur.fetchone()[0]
            conn.commit()
            log_details = f"Created request ID {request_id} for {user_email} with status '{status}'."
            if stage_approvals:
                log_details += f" Pre-populated approvers for stages {', '.join(stage_approvals.keys())}."
            logging.info(log_details)
            return request_id

def find_active_request_by_user(user_email):
    """Finds the most recent, non-completed/duplicate request for a user across all configs."""
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(
                "SELECT * FROM onboarding_tracker WHERE user_to_onboard_email = %s AND status NOT IN ('completed', 'duplicate', 'error') ORDER BY updated_at DESC LIMIT 1;",
                (user_email,)
            )
            return cur.fetchone()

def get_mature_unprocessed_requests(config_id, config):
    """
    Fetches requests that are in 'new_unprocessed' state and older than the configured maturity delay.
    """
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            delay_minutes = config.get('MATURITY_DELAY_MINUTES', 5)
            cur.execute(
                "SELECT * FROM onboarding_tracker WHERE config_id = %s AND status = 'new_unprocessed' AND created_at < NOW() - INTERVAL '%s minutes';",
                (config_id, delay_minutes)
            )
            return cur.fetchall()

def onboard_user_to_target_db(user_email, config):
    """
    Handles the final step of provisioning the user in the target database.
    """
    update_internal_user_access(user_email, config['config_id'])
    if not all([config.get('target_db_type'), config.get('target_table_name'), config.get('target_column_mappings')]):
        logging.warning(f"[{config['config_id']}] No target DB configured, skipping final onboarding.")
        return
    conn = None
    try:
        db_type = config['target_db_type']
        db_config = config['target_db_config']
        if db_type == 'postgresql':
            conn = psycopg2.connect(**db_config)
        elif db_type == 'mysql':
            conn = mysql.connector.connect(**db_config)
        elif db_type == 'oracle':
            conn = oracledb.connect(**db_config)
        elif db_type == 'mssql':
            conn_str = ';'.join([f'{k}={v}' for k, v in db_config.items()])
            conn = pyodbc.connect(conn_str)
        else:
            logging.error(f"Unsupported target DB type: {db_type}")
            return

        cursor = conn.cursor()
        table = config['target_table_name']
        mappings = config['target_column_mappings']
        email_col = mappings['email_column']

        cursor.execute(f"SELECT {email_col} FROM {table} WHERE {email_col} = %s", (user_email,))
        exists = cursor.fetchone()

        default_values = {mappings[k.replace('default_', '') + '_column']: v for k, v in mappings.items() if k.startswith('default_')}

        if exists:
            update_cols = {**default_values, **{mappings['active_column']: True}}
            set_clause = ', '.join([f"{col} = %s" for col in update_cols.keys()])
            query = f"UPDATE {table} SET {set_clause} WHERE {email_col} = %s"
            params = list(update_cols.values()) + [user_email]
        else:
            insert_cols = {**default_values, **{mappings['email_column']: user_email, mappings['active_column']: True}}
            cols_clause = ', '.join(insert_cols.keys())
            placeholders = ', '.join(['%s'] * len(insert_cols))
            query = f"INSERT INTO {table} ({cols_clause}) VALUES ({placeholders})"
            params = list(insert_cols.values())

        cursor.execute(query, params)
        conn.commit()
        logging.info(f"User {user_email} onboarded in target table {table}")
    except Exception as e:
        logging.error(f"Onboarding to target DB failed: {e}", exc_info=True)
        if conn:
            conn.rollback()
        # ===== FIX =====
        # Re-raise the exception so the calling function knows the operation failed.
        raise
    finally:
        if conn:
            conn.close()

def get_required_approvers_for_stage(request, config):
    """
    Gets the base list of required approvers by reading the 'required' list
    from the pre-populated 'stage_approvals' JSON field. This avoids repeated AD calls.
    """
    stage_str = str(request['current_stage'])
    all_approvals_data = request.get('stage_approvals', {})

    # Gracefully handle if the JSON is in the new format or an old one.
    stage_data = all_approvals_data.get(stage_str)
    if isinstance(stage_data, dict):
        return stage_data.get('required', [])
    else:
        # Fallback for old data format or error. This path should not be taken in the new flow.
        logging.warning(f"Request ID {request['id']} has legacy or malformed stage_approvals. Falling back to live AD lookup.")
        stage = request['current_stage']
        if stage == 1:
            mgr = ad_service.get_user_manager(request['user_to_onboard_email'], config)
            return [mgr.lower()] if mgr else []
        elif stage == 2:
            return ad_service.get_group_owners(config['required_ad_group'], config)
        return []

def get_effective_approvers_for_stage(request, config):
    """
    Calculates the list of people who can actually approve, including delegations.
    """
    required = set(get_required_approvers_for_stage(request, config))
    delegations_raw = request.get('delegated_approvers', '[]')
    delegations = json.loads(delegations_raw) if isinstance(delegations_raw, str) else delegations_raw
    
    if not delegations:
        return list(required)
        
    mapping = {item['original'].lower(): item['delegate'].lower() for item in delegations}
    effective = set()
    for approver in required:
        effective.add(mapping.get(approver, approver))
    return list(effective)

def get_missing_approvers_for_stage(request, config):
    """Compares effective approvers with those who have already approved for the current stage."""
    effective = set(get_effective_approvers_for_stage(request, config))
    all_approvals_data = request.get('stage_approvals', {})
    stage_str = str(request['current_stage'])
    stage_data = all_approvals_data.get(stage_str)

    approved_for_stage = set()
    if isinstance(stage_data, dict):
        # New format: {"required": [...], "approved": [...]}
        approved_for_stage = set(stage_data.get('approved', []))
    elif isinstance(stage_data, list):
        # Old format: [...]
        approved_for_stage = set(stage_data)
    
    return list(effective - approved_for_stage)

def add_stage_approval(request, approver_email, config):
    """
    Adds an approver's email to the 'approved' list for the current stage.
    It also proactively adds the approval to any future stages where the same
    user is a required approver.
    """
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            current_stage_num = request['current_stage']
            stage_approvals = request.get('stage_approvals', {})
            approver_email_lower = approver_email.lower()

            # --- Main approval for the current stage ---
            current_stage_str = str(current_stage_num)
            if current_stage_str not in stage_approvals or not isinstance(stage_approvals.get(current_stage_str), dict):
                logging.error(f"Cannot add approval for request {request['id']}. Stage {current_stage_str} data is missing or malformed.")
                return False

            stage_data = stage_approvals[current_stage_str]
            current_approved = stage_data.get('approved', [])
            
            if approver_email_lower in current_approved:
                logging.info(f"Approval by {approver_email} was already recorded for request ID {request['id']} at stage {current_stage_str}.")
                return False

            stage_data['approved'] = current_approved + [approver_email_lower]
            stage_approvals[current_stage_str] = stage_data
            logging.info(f"Added approval from {approver_email} for request ID {request['id']} at stage {current_stage_str}.")

            # --- Proactive approval for future stages ---
            max_stage = max([int(k) for k in stage_approvals.keys()] + [0])
            if current_stage_num < max_stage:
                for stage_num in range(current_stage_num + 1, max_stage + 1):
                    future_stage_str = str(stage_num)
                    future_stage_data = stage_approvals.get(future_stage_str, {})
                    
                    if isinstance(future_stage_data, dict):
                        future_required = future_stage_data.get('required', [])
                        future_approved = future_stage_data.get('approved', [])
                        
                        if approver_email_lower in future_required and approver_email_lower not in future_approved:
                            future_stage_data['approved'] = future_approved + [approver_email_lower]
                            stage_approvals[future_stage_str] = future_stage_data
                            logging.info(f"Proactively added approval from {approver_email} for request ID {request['id']} at future stage {future_stage_str}.")

            # --- Commit changes to DB ---
            cur.execute(
                "UPDATE onboarding_tracker SET stage_approvals = %s::jsonb, last_activity_details = %s WHERE id = %s;",
                (json.dumps(stage_approvals), f"Approval recorded from {approver_email}", request['id'])
            )
            conn.commit()
            return cur.rowcount > 0

def update_request_status_composite(user_email, group, config_id, status, details):
    """Updates the status and details of the active request for a user/group/config."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE onboarding_tracker SET status=%s, last_activity_details=%s WHERE user_to_onboard_email=%s AND requested_group=%s AND config_id=%s AND status != 'duplicate';",
                (status, details, user_email, group, config_id)
            )
            conn.commit()

def get_active_request(user_email, group, config_id):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT * FROM onboarding_tracker WHERE user_to_onboard_email=%s AND requested_group=%s AND config_id=%s AND status NOT IN ('completed', 'duplicate', 'error') ORDER BY created_at DESC LIMIT 1;", (user_email, group, config_id))
            return cur.fetchone()

def advance_to_next_stage_composite(user_email, group, config_id):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("UPDATE onboarding_tracker SET current_stage = current_stage + 1 WHERE user_to_onboard_email = %s AND requested_group = %s AND config_id = %s AND status NOT IN ('duplicate', 'completed') RETURNING *;", (user_email, group, config_id))
            req = cur.fetchone()
            conn.commit()
            return req

def get_pending_requests_for_reminder(config):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            reminder_hours = config.get('REMINDER_THRESHOLD_HOURS', 24)
            cur.execute("SELECT * FROM onboarding_tracker WHERE status LIKE 'pending_%%' AND updated_at < NOW() - INTERVAL '%s hours' AND config_id = %s;", (reminder_hours, config['config_id']))
            return cur.fetchall()

def claim_uid_for_processing(uid):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO processed_uids (uid) VALUES (%s) ON CONFLICT (uid) DO NOTHING;", (uid,))
            conn.commit()
            return cur.rowcount > 0

def get_all_active_configurations():
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT * FROM configuration WHERE is_active = TRUE;")
            return cur.fetchall()

def update_internal_user_access(user_email, config_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO onboarding_log (email, config_id, access_flag) VALUES (%s, %s, TRUE) ON CONFLICT (email, config_id) DO UPDATE SET access_flag=TRUE;", (user_email, config_id))
            conn.commit()

def get_mailbox_config_by_id(mailbox_id):
    """Fetches a single mailbox configuration by its ID."""
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT * FROM mailboxes WHERE id = %s;", (mailbox_id,))
            return cur.fetchone()
