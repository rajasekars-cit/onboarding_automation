import os
import msal
import requests
from dotenv import load_dotenv

load_dotenv()

TENANT_ID = os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPE = ["https://graph.microsoft.com/.default"]
GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"

def get_access_token():
    app = msal.ConfidentialClientApplication(
        CLIENT_ID, authority=AUTHORITY, client_credential=CLIENT_SECRET
    )
    result = app.acquire_token_for_client(scopes=SCOPE)
    if "access_token" in result:
        return result["access_token"]
    else:
        raise Exception(f"Failed to acquire token: {result}")

def get_user_id(user_email, token):
    resp = requests.get(
        f"{GRAPH_API_BASE}/users?$filter=mail eq '{user_email}' or userPrincipalName eq '{user_email}'",
        headers={"Authorization": f"Bearer {token}"}
    )
    if resp.status_code != 200:
        raise Exception(f"Error fetching user: {resp.status_code}, {resp.text}")

    data = resp.json()
    if not data.get("value"):
        return None
    return data["value"][0]["id"]

def get_group_id(group_name, token):
    group_resp = requests.get(
        f"{GRAPH_API_BASE}/groups?$filter=displayName eq '{group_name}'",
        headers={"Authorization": f"Bearer {token}"}
    )
    if group_resp.status_code != 200:
        raise Exception(f"Error fetching group: {group_resp.status_code}, {group_resp.text}")

    group_data = group_resp.json()
    if not group_data.get("value"):
        return None
    return group_data["value"][0]["id"]

def check_user_group_membership(user_email, group_name, token):
    group_id = get_group_id(group_name, token)
    if not group_id:
        return f"❌ Group '{group_name}' not found."

    user_id = get_user_id(user_email, token)
    if not user_id:
        return f"❌ User '{user_email}' not found in Azure AD."

    check_resp = requests.post(
        f"{GRAPH_API_BASE}/users/{user_id}/checkMemberGroups",
        headers={"Authorization": f"Bearer {token}"},
        json={"groupIds": [group_id]}
    )

    if check_resp.status_code == 200:
        result = check_resp.json()
        if group_id in result.get("value", []):
            return f"✅ {user_email} IS a member of '{group_name}'."
        else:
            return f"❌ {user_email} is NOT a member of '{group_name}'."
    else:
        return f"⚠ Unexpected response: {check_resp.status_code}, {check_resp.text}"

def get_manager(user_email, token):
    user_id = get_user_id(user_email, token)
    if not user_id:
        return f"❌ User '{user_email}' not found in Azure AD."

    manager_resp = requests.get(
        f"{GRAPH_API_BASE}/users/{user_id}/manager",
        headers={"Authorization": f"Bearer {token}"}
    )

    if manager_resp.status_code == 200:
        manager_data = manager_resp.json()
        manager_name = manager_data.get("displayName", "Unknown")
        manager_email = manager_data.get("mail", "No email")
        return f"👤 Manager for {user_email}: {manager_name} ({manager_email})"
    elif manager_resp.status_code == 404:
        return f"ℹ No manager found for {user_email}."
    else:
        return f"⚠ Error: {manager_resp.status_code}, {manager_resp.text}"

def get_group_owners(group_name, token):
    group_id = get_group_id(group_name, token)
    if not group_id:
        return f"❌ Group '{group_name}' not found."

    owners_resp = requests.get(
        f"{GRAPH_API_BASE}/groups/{group_id}/owners",
        headers={"Authorization": f"Bearer {token}"}
    )

    if owners_resp.status_code == 200:
        owners_data = owners_resp.json().get("value", [])
        if not owners_data:
            return f"ℹ No owners found for group '{group_name}'."

        owners_list = [
            f"{owner.get('displayName', 'Unknown')} ({owner.get('mail', 'No email')})"
            for owner in owners_data
        ]
        return f"👥 Owners of '{group_name}':\n" + "\n".join(owners_list)
    else:
        return f"⚠ Error fetching owners: {owners_resp.status_code}, {owners_resp.text}"

if __name__ == "__main__":
    user_email = "jayalakshmi.subni@gmail.com"  # External or internal user
    group_name = "DEV"
    token = get_access_token()

    print(check_user_group_membership(user_email, group_name, token))
    print(get_manager(user_email, token))
    print(get_group_owners(group_name, token))

#Output
#subni.shervinah@gmail.com IS a member of 'DEV'.
#👤 Manager for subni.shervinah@gmail.com: Subathra Rajasekar (subabuvan.ilan@gmail.com)
#👥 Owners of 'DEV':
#Rajasekar S (raj.sekarcit@gmail.com)