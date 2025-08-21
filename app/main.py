# FILE: app/main.py
# ==============================================================================
# Main workflow orchestrator called by worker threads.
# It manages the two-phase workflow for a single mailbox and all its
# associated configurations (e.g., one shared mailbox for DEV and DBA).
# ==============================================================================

import logging
from app.services.email_service import (
    ingest_emails_to_db, 
    process_pending_actions, 
    process_pending_reminders
)

def run(mailbox_config, associated_configs, static_config):
    """
    Orchestrates the workflow for a single mailbox and its associated configurations.
    """
    mailbox_id = mailbox_config.get('id')
    logging.info(f"[Mailbox ID: {mailbox_id}] Starting two-phase workflow cycle.")

    # Phase 1: Ingest emails from the single mailbox
    try:
        logging.info(f"[Mailbox ID: {mailbox_id}] --- Phase 1: Ingesting Emails ---")
        ingest_emails_to_db(mailbox_config, associated_configs, static_config)
    except Exception as e:
        logging.error(f"[Mailbox ID: {mailbox_id}] Error during email ingestion phase: {e}", exc_info=True)

    # Phase 2: Process actions for each configuration associated with this mailbox
    logging.info(f"[Mailbox ID: {mailbox_id}] --- Phase 2: Processing Actions & Reminders ---")
    for dynamic_config in associated_configs:
        config_id = dynamic_config.get('config_id')
        try:
            # Create a full, merged config object for each specific workflow
            full_config = {**static_config, **mailbox_config, **dynamic_config}
            process_pending_actions(full_config)
            process_pending_reminders(full_config)
        except Exception as e:
            logging.error(f"[Config ID: {config_id}] Error during action/reminder phase: {e}", exc_info=True)

    logging.info(f"[Mailbox ID: {mailbox_id}] Completed two-phase workflow cycle")