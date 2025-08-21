# FILE: app/config.py
# ==============================================================================
# Static configuration loader for environment variables
# ==============================================================================

import os
import logging
from dotenv import load_dotenv

# Load environment variables from a .env file if it exists
load_dotenv()

def get_static_config():
    """Loads static configuration from environment variables."""
    logging.info("Loading static configuration from environment variables")
    config = {}
    config['SCHEDULE_MINUTES'] = int(os.getenv("SCHEDULE_MINUTES", 1))
    config['MAX_WORKER_THREADS'] = int(os.getenv("MAX_WORKER_THREADS", 5))
    config['INITIAL_LOOKBACK_DAYS'] = int(os.getenv("INITIAL_LOOKBACK_DAYS", 1))
    config['REMINDER_THRESHOLD_HOURS'] = int(os.getenv("REMINDER_THRESHOLD_HOURS", 24))
    
    # NEW: Delay for the action worker to process staged requests
    config['MATURITY_DELAY_MINUTES'] = int(os.getenv("MATURITY_DELAY_MINUTES", 0))

    # AI Service Config
    config['OLLAMA_HOST'] = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    config['OLLAMA_MODEL'] = os.getenv("OLLAMA_MODEL", "llama3:8b")
    
    # Azure AD / Graph API Config
    config['AZURE_TENANT_ID'] = os.getenv("AZURE_TENANT_ID")
    config['AZURE_CLIENT_ID'] = os.getenv("AZURE_CLIENT_ID")
    config['AZURE_CLIENT_SECRET'] = os.getenv("AZURE_CLIENT_SECRET")
    
    logging.info("Static configuration loaded.")
    return config