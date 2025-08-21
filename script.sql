-- ==============================================================================
-- SQL Schema for the Onboarding Automation Application
-- ==============================================================================

-- Drop tables in reverse order of creation to handle dependencies if they already exist.
DROP TRIGGER IF EXISTS set_timestamp ON public.onboarding_tracker;
DROP FUNCTION IF EXISTS public.trigger_set_timestamp();
DROP TABLE IF EXISTS public.app_state;
DROP TABLE IF EXISTS public.processed_uids;
DROP TABLE IF EXISTS public.onboarding_log;
DROP TABLE IF EXISTS public.onboarding_tracker;
DROP TABLE IF EXISTS public.configuration;
DROP TABLE IF EXISTS public.mailboxes;


-- ==============================================================================
-- Table: mailboxes
-- Purpose: Stores unique mailbox credentials. This allows multiple workflows
-- to share the same mailbox or use their own independent ones.
-- ==============================================================================
CREATE TABLE public.mailboxes (
    id SERIAL PRIMARY KEY,
    description TEXT,
    imap_server TEXT NOT NULL,
    imap_user TEXT NOT NULL,
    imap_pass TEXT NOT NULL,
    smtp_server TEXT NOT NULL,
    smtp_port INTEGER NOT NULL,
    smtp_user TEXT NOT NULL,
    smtp_pass TEXT NOT NULL
);

COMMENT ON TABLE public.mailboxes IS 'Stores unique credentials for each email account the system needs to access.';
COMMENT ON COLUMN public.mailboxes.id IS 'Unique identifier for the mailbox configuration.';


-- ==============================================================================
-- Table: configuration
-- Purpose: Stores the specific rules for each onboarding workflow.
-- ==============================================================================
CREATE TABLE public.configuration (
    config_id TEXT PRIMARY KEY,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    team_alias TEXT NOT NULL,
    workflow_type TEXT NOT NULL DEFAULT 'ad_validated',
    required_ad_group TEXT,
    mailbox_id INTEGER REFERENCES public.mailboxes(id) ON DELETE SET NULL,
    target_db_type TEXT,
    target_db_config JSONB,
    target_table_name TEXT,
    target_column_mappings JSONB
);

COMMENT ON TABLE public.configuration IS 'Defines the rules for each distinct onboarding workflow (e.g., for DEV team, DBA team).';
COMMENT ON COLUMN public.configuration.config_id IS 'Unique identifier for the workflow configuration (e.g., DBA_Onboarding).';
COMMENT ON COLUMN public.configuration.mailbox_id IS 'Foreign key linking to the specific mailbox credentials in the mailboxes table.';


-- ==============================================================================
-- Table: onboarding_tracker
-- Purpose: Tracks the state of every individual onboarding request.
-- ==============================================================================
CREATE TABLE public.onboarding_tracker (
    id SERIAL PRIMARY KEY,
    user_to_onboard_email VARCHAR(255) NOT NULL,
    requested_group VARCHAR(100) NOT NULL,
    config_id TEXT NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'new_unprocessed',
    current_stage INTEGER DEFAULT 1,
    stage_approvals JSONB DEFAULT '{}'::jsonb,
    delegated_approvers JSONB DEFAULT '[]'::jsonb,
    duplicate_of INTEGER,
    request_count INTEGER DEFAULT 1,
    last_activity_details TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Composite index to speed up lookups for active requests.
CREATE INDEX IF NOT EXISTS idx_onboard_email_group_config
ON public.onboarding_tracker(user_to_onboard_email, requested_group, config_id);

COMMENT ON TABLE public.onboarding_tracker IS 'Tracks the status and approval history of each individual onboarding request.';
COMMENT ON COLUMN public.onboarding_tracker.status IS 'The current state of the request (e.g., new_unprocessed, pending_manager_approval, completed).';


-- ==============================================================================
-- Table: onboarding_log
-- Purpose: A permanent record of users who have been granted access.
-- ==============================================================================
CREATE TABLE public.onboarding_log (
    email TEXT NOT NULL,
    config_id TEXT NOT NULL,
    access_flag BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    -- Composite primary key ensures a user can only have one entry per configuration.
    PRIMARY KEY (email, config_id)
);

COMMENT ON TABLE public.onboarding_log IS 'Maintains a final record of which users have been successfully onboarded to which system.';


-- ==============================================================================
-- Table: processed_uids
-- Purpose: Prevents the system from processing the same email more than once.
-- ==============================================================================
CREATE TABLE public.processed_uids (
    uid TEXT PRIMARY KEY,
    processed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE public.processed_uids IS 'Stores the unique IDs (UIDs) of emails that have already been processed to prevent duplicates.';


-- ==============================================================================
-- Table: app_state
-- Purpose: Stores persistent application state, like the last email check time.
-- ==============================================================================
CREATE TABLE public.app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

COMMENT ON TABLE public.app_state IS 'A simple key-value store for application state, such as last_check_timestamps for each mailbox.';


-- ==============================================================================
-- Function and Trigger: trigger_set_timestamp
-- Purpose: Automatically updates the 'updated_at' column in the
-- onboarding_tracker table whenever a row is modified.
-- ==============================================================================
CREATE OR REPLACE FUNCTION public.trigger_set_timestamp()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER set_timestamp
BEFORE UPDATE ON public.onboarding_tracker
FOR EACH ROW
EXECUTE FUNCTION public.trigger_set_timestamp();

COMMENT ON TRIGGER set_timestamp ON public.onboarding_tracker IS 'Automatically updates the updated_at field on row modification.';



-- Step 1: Create the shared mailbox record in the new 'mailboxes' table.
-- This will create a record with id = 1, which we will reference below.
INSERT INTO public.mailboxes
(description, imap_server, imap_user, imap_pass, smtp_server, smtp_port, smtp_user, smtp_pass)
VALUES
('Tech Teams Shared Mailbox', 'imap.gmail.com', 'facilebase@gmail.com', 'fjxp etsp bhzw bbnz', 'smtp.gmail.com', 587, 'facilebase@gmail.com', 'fjxp etsp bhzw bbnz');


-- Step 2: Create the workflow configurations that USE the shared mailbox.
-- Notice both configurations now point to 'mailbox_id = 1'.

-- Configuration for the DBA Team
INSERT INTO public.configuration
(config_id, description, is_active, team_alias, workflow_type, required_ad_group, mailbox_id, target_db_type, target_db_config, target_table_name, target_column_mappings)
VALUES
('DBA_Onboarding', 'Onboarding for the DBA Team', true, 'DBA Team', 'ad_validated', 'DB', 1, 'postgresql', '{"host": "localhost", "port": 5432, "user": "postgres", "dbname": "onboarding_db", "password": "RSK12@postgres"}', 'db_users', '{"email_column": "email", "active_column": "active", "default_access_level": "ro"}');

-- Configuration for the DEV Team
INSERT INTO public.configuration
(config_id, description, is_active, team_alias, workflow_type, required_ad_group, mailbox_id, target_db_type, target_db_config, target_table_name, target_column_mappings)
VALUES
('DEV_Onboarding', 'Onboarding for the DEV Team', true, 'DEV Team', 'ad_validated', 'DEV', 1, 'postgresql', '{"host": "localhost", "port": 5432, "user": "postgres", "dbname": "onboarding_db", "password": "RSK12@postgres"}', 'dev_users', '{"email_column": "email", "active_column": "active", "default_access_level": "rw"}');

UPDATE public.configuration
SET 
    target_column_mappings = '{"email_column": "email", "active_column": "active", "access_level_column": "access_level", "default_access_level": "rw"}'
WHERE 
    config_id = 'DEV_Onboarding';

UPDATE public.configuration
SET 
    target_column_mappings = '{"email_column": "email", "active_column": "active", "access_level_column": "access_level", "default_access_level": "ro"}'
WHERE 
    config_id = 'DBA_Onboarding';


-- This script adds the missing 'access_level' column to your target user tables.

-- Add the column to the dev_users table
ALTER TABLE public.dev_users
ADD COLUMN access_level VARCHAR(50);

-- Add the column to the db_users table (for your DBA_Onboarding config)
ALTER TABLE public.db_users
ADD COLUMN access_level VARCHAR(50);

