# FILE: app/services/ai_service.py
# ==============================================================================
# AI service for analyzing email content using Ollama.
# Determines intent (new_request, approval, etc.) and extracts key information.
# ==============================================================================
import logging
import json
import re
import ollama

client = None

def is_real_user_email(email_address):
    """Helper to filter out no-reply/bot/system email addresses."""
    if not email_address: return False
    patterns = [
        r'no-?reply@', r'notification', r'do-?not-?reply@', r'mailer-daemon', r'postmaster@',
        r'automated', r'helpdesk', r'bounces@', r'^noreply', r'bot@', r'listserv',
        r'system@', r'alerts?@'
    ]
    return not any(re.search(pat, email_address, re.IGNORECASE) for pat in patterns)

KEYWORDS = ['onboard', 'request access', 'join', 'add access', 'add to group', 'registration', 'enable access', 'new user', 'account setup', 'provision', 'grant access', 'request membership', 'add user']

def contains_onboarding_keyword(text):
    """Checks if text contains common onboarding-related keywords."""
    return any(kw in text.lower() for kw in KEYWORDS)

def analyze_email(subject, body, config):
    """
    Analyzes email content using an LLM to determine intent and extract entities.
    """
    global client
    if client is None:
        logging.info(f"Initializing Ollama client with host: {config['OLLAMA_HOST']}")
        client = ollama.Client(host=config['OLLAMA_HOST'])

    full_content = f"Subject: {subject}\n\nBody:\n{body}"
    compacted = re.sub(r'\s+', ' ', full_content).strip()[:5000]
    
    # RESTORED: Using the original, more detailed prompt for higher accuracy.
    system_prompt = """
You are a careful IT onboarding gatekeeper. Your job is to classify incoming emails.
You MUST ONLY return a JSON dictionary, and nothing else.

A "new_request" is valid ONLY when BOTH:
* The email expresses a clear onboarding intent (contains keywords like "onboard", "request access", "add user", "join", "add to group", "enable access", "registration"), AND
* Contains a real person's email address (NOT no-reply, notification, bot, mailer-daemon, etc).

If BOTH these conditions are not met, classify as intent "query" and set all extracted fields to null.

JSON format for output:

For onboarding requests:
  {
      "intent": "new_request",
      "user_email": "[REAL_EMAIL]",
      "requested_group": "[GROUP]" // The Team/System requested, e.g. "DEV". If you can't find it, set it to null.
  }

For everything else:
  {
    "intent": "query",
    "user_email": null,
    "delegate_email": null,
    "requested_group": null
  }
Do NOT guess or invent values. ONLY extract real emails from the body or subject and carefully check the sender.
If the only email present is a no-reply, notification, daemon, or other bot/system address, DO NOT create new_request.
Never use example.com or placeholder values.

For approvals and other flows: (same as before)
      {"intent": "[approval_or_rejection]", "user_email": "[USER]", "requested_group": "[GROUP_NAME]"}
      (if not found, use nulls)

If you see an “out of office” response that names a delegate, return:
      {"intent": "out_of_office", "delegate_email": "[DELEGATE_EMAIL]"}

REMEMBER:
* If the message does not contain onboarding keywords AND a real user email, classify as "query".
"""

    try:
        response = client.chat(
            model=config['OLLAMA_MODEL'],
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': compacted}
            ],
            options={'temperature': 0.0},
            format='json'
        )
        result_json_str = response['message']['content']
        res = json.loads(result_json_str)

        # Post-processing validation to ensure high-quality results
        user_email = res.get('user_email')
        if res.get('intent') == 'new_request':
            if not (is_real_user_email(user_email) and contains_onboarding_keyword(subject + ' ' + body)):
                logging.warning(f"AI classified as 'new_request' but failed validation. Reverting to 'query'.")
                res['intent'] = "query"
                res['user_email'] = None
                res['requested_group'] = None
                
        logging.info(f"AI Analysis Result: {json.dumps(res)}")
        return res

    except Exception as e:
        logging.error(f"Error calling Ollama or parsing its response: {e}", exc_info=True)
        return None