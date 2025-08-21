# FILE: app/services/ad_service.py
# ==============================================================================
# Service for interacting with Azure Active Directory via Microsoft Graph API.
# Handles token acquisition, user/group lookups, and membership checks.
# ==============================================================================
import logging
import msal
import requests

GRAPH_API_ENDPOINT = 'https://graph.microsoft.com/v1.0'
_app_cache = {} # Cache the MSAL app object to reuse its internal token cache

def get_access_token(config):
    """Acquires an access token for the Microsoft Graph API, using MSAL's built-in caching."""
    tenant_id = config['AZURE_TENANT_ID']
    client_id = config['AZURE_CLIENT_ID']
    
    if not all([tenant_id, client_id, config.get('AZURE_CLIENT_SECRET')]):
        logging.error("Azure AD credentials (TENANT_ID, CLIENT_ID, CLIENT_SECRET) are not configured.")
        return None

    # Reuse the app object to leverage MSAL's internal token cache
    if client_id not in _app_cache:
        authority = f"https://login.microsoftonline.com/{tenant_id}"
        app = msal.ConfidentialClientApplication(
            client_id=client_id,
            authority=authority,
            client_credential=config['AZURE_CLIENT_SECRET'],
        )
        _app_cache[client_id] = app
    
    app = _app_cache[client_id]
    
    # acquire_token_for_client will automatically use its cache and refresh if needed.
    token_result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])

    if "access_token" in token_result:
        return token_result["access_token"]
    else:
        logging.error(f"Failed to acquire Graph API token: {token_result.get('error_description')}")
        # Clear the app from cache in case of persistent auth failure
        if client_id in _app_cache:
            del _app_cache[client_id]
        return None

def get_user_id(user_email, token):
    """Gets the Azure AD object ID for a user from their email."""
    headers = {"Authorization": f"Bearer {token}"}
    
    # This filter is proven to work for finding both internal and guest users.
    params = {"$filter": f"mail eq '{user_email}' or userPrincipalName eq '{user_email}'"}

    response = requests.get(f"{GRAPH_API_ENDPOINT}/users", headers=headers, params=params)
    if response.status_code == 200:
        data = response.json().get("value")
        if data: 
            # logging.info(f"Found user with ID: {data[0]['id']}")
            return data[0]["id"]
    else:
        logging.error(f"Graph API error when searching for user '{user_email}': {response.status_code} - {response.text}")
        
    return None

def get_group_id(group_name, token):
    """Gets the Azure AD object ID for a group from its display name."""
    headers = {"Authorization": f"Bearer {token}"}
    params = {"$filter": f"displayName eq '{group_name}'"}
    response = requests.get(f"{GRAPH_API_ENDPOINT}/groups", headers=headers, params=params)
    if response.status_code == 200:
        data = response.json().get("value")
        if data: return data[0]["id"]
    return None

def is_user_in_group(user_email, group_name, config):
    """Checks if a user is a member of a specific Azure AD group."""
    token = get_access_token(config)
    if not token: return False
    group_id = get_group_id(group_name, token)
    if not group_id:
        logging.error(f"AD group '{group_name}' not found.")
        return False
    user_id = get_user_id(user_email, token)
    if not user_id:
        logging.warning(f"User '{user_email}' not found in AD for group check.")
        return False
    headers = {"Authorization": f"Bearer {token}"}
    json_payload = {"groupIds": [group_id]}
    response = requests.post(f"{GRAPH_API_ENDPOINT}/users/{user_id}/checkMemberGroups", headers=headers, json=json_payload)
    if response.status_code == 200:
        if group_id in response.json().get("value", []):
            logging.info(f"AD check PASSED: {user_email} is a member of '{group_name}'.")
            return True
    logging.warning(f"AD check FAILED: {user_email} is NOT a member of '{group_name}'.")
    return False

def get_user_manager(user_email, config):
    """Fetches the line manager's email for a given user from Azure AD."""
    token = get_access_token(config)
    if not token: return None
    user_id = get_user_id(user_email, token)
    if not user_id:
        logging.warning(f"Could not find user ID for '{user_email}'. Cannot fetch manager.")
        return None

    headers = {'Authorization': f'Bearer {token}'}
    
    # ===== FIX STARTS HERE =====
    # Step 1: Get the manager object. This might return a limited profile.
    manager_response = requests.get(f"{GRAPH_API_ENDPOINT}/users/{user_id}/manager", headers=headers)

    if manager_response.status_code == 200:
        manager_data = manager_response.json()
        manager_id = manager_data.get('id')
        
        if not manager_id:
            logging.warning(f"Found a manager object for {user_email}, but it has no ID.")
            return None

        # Step 2: Use the manager's ID to get their full user profile, which includes the email.
        full_profile_response = requests.get(f"{GRAPH_API_ENDPOINT}/users/{manager_id}", headers=headers)
        
        if full_profile_response.status_code == 200:
            full_profile_data = full_profile_response.json()
            manager_email = full_profile_data.get('mail')
            if manager_email:
                # logging.info(f"Found manager for {user_email}: {manager_email}")
                return manager_email.lower()
        else:
            logging.warning(f"Could not fetch full profile for manager of {user_email}. Status: {full_profile_response.status_code}, Body: {full_profile_response.text}")

    logging.warning(f"Could not fetch manager for {user_email}. Status: {manager_response.status_code}, Body: {manager_response.text}")
    return None
    # ===== FIX ENDS HERE =====

def get_group_owners(group_name, config):
    """Fetches the email addresses of the owners of a specific AD group."""
    token = get_access_token(config)
    if not token: return []
    group_id = get_group_id(group_name, token)
    if not group_id:
        logging.error(f"Cannot get owners because AD group '{group_name}' was not found.")
        return []
    headers = {'Authorization': f'Bearer {token}'}
    
    # Explicitly select the fields needed to ensure they are returned.
    params = {"$select": "displayName,mail"}
    response = requests.get(f"{GRAPH_API_ENDPOINT}/groups/{group_id}/owners", headers=headers, params=params)
    
    if response.status_code == 200:
        owners_data = response.json().get("value", [])
        owner_emails = [owner.get('mail').lower() for owner in owners_data if owner.get('mail')]
        logging.info(f"Found owners for group '{group_name}': {owner_emails}")
        return owner_emails
    logging.error(f"Error fetching owners for group '{group_name}': {response.text}")
    return []
