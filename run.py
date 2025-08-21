# FILE: run.py
# ==============================================================================
# Orchestrates the onboarding workflow using a producer-consumer model.
# The producer groups configurations by mailbox and creates a polling task
# for each unique mailbox, supporting both shared and independent mailboxes.
# ==============================================================================

import time
import logging
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from app.main import run
from app.services import db_service
from app.config import get_static_config
from collections import defaultdict

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(threadName)s - %(module)s - %(message)s'
)

WORK_QUEUE = queue.Queue()

def worker_thread(static_config):
    """ Worker thread that dequeues and processes one mailbox task at a time. """
    logging.info("Worker thread started")
    while True:
        task = WORK_QUEUE.get()
        if task is None:
            logging.info("Worker received sentinel to shut down")
            break
        try:
            mailbox_id = task.get('mailbox_config', {}).get('id')
            logging.info(f"Worker picking up task for mailbox_id: {mailbox_id}")
            run(task['mailbox_config'], task['associated_configs'], static_config)
        except Exception as e:
            mailbox_id = task.get('mailbox_config', {}).get('id', 'unknown')
            logging.error(f"Error in worker for mailbox {mailbox_id}: {e}", exc_info=True)
        finally:
            WORK_QUEUE.task_done()

def producer_thread():
    """ Producer thread that groups configs by mailbox and schedules one task per mailbox. """
    while True:
        try:
            logging.info("Producer waking to schedule tasks")
            
            # Group configurations by their mailbox_id to create one task per mailbox
            active_configs = db_service.get_all_active_configurations()
            tasks_by_mailbox = defaultdict(list)
            for config in active_configs:
                if config.get('mailbox_id'):
                    tasks_by_mailbox[config['mailbox_id']].append(config)

            if not tasks_by_mailbox:
                logging.info("No active mailboxes to poll.")
            else:
                logging.info(f"Scheduling polling for {len(tasks_by_mailbox)} unique mailboxes.")
                for mailbox_id, associated_configs in tasks_by_mailbox.items():
                    mailbox_config = db_service.get_mailbox_config_by_id(mailbox_id)
                    if mailbox_config:
                        task = {
                            "mailbox_config": mailbox_config,
                            "associated_configs": associated_configs
                        }
                        WORK_QUEUE.put(task)
                    else:
                        logging.error(f"Could not find mailbox configuration for mailbox_id: {mailbox_id}. Skipping.")

            static_config = get_static_config()
            interval = static_config.get("SCHEDULE_MINUTES", 5) * 60
            time.sleep(interval)
        except Exception as e:
            logging.error(f"Producer thread error: {e}", exc_info=True)
            time.sleep(60)

if __name__ == "__main__":
    logging.info("Starting onboarding application with thread pool")
    static_cfg = get_static_config()
    max_workers = static_cfg.get("MAX_WORKER_THREADS", 10)

    db_service.setup_database()

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="Worker") as executor:
        for _ in range(max_workers):
            executor.submit(worker_thread, static_cfg)

        producer = threading.Thread(target=producer_thread, name="Producer")
        producer.daemon = True
        producer.start()

        try:
            producer.join()
        except KeyboardInterrupt:
            logging.info("Shutdown requested, signaling workers to stop...")
            for _ in range(max_workers):
                WORK_QUEUE.put(None)