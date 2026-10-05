"""Pull Salesforce engagement for tracked contacts into contacts.json.

Auth uses the OAuth 2.0 client-credentials flow of a Salesforce connected app
(SF_LOGIN_URL, SF_CLIENT_ID, SF_CLIENT_SECRET). Custom fields to read are set
with SF_CONTACT_FIELDS; if any of them don't exist in the org the query falls
back to standard fields only, so a field-name mismatch never breaks the run.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

import config
from util import load_json, now_iso, save_json

STANDARD_FIELDS = ["Id", "Email", "AccountId", "Account.Name", "Owner.Name", "LastActivityDate"]
DEFAULT_CUSTOM_FIELDS = "Outbound_Contact__c,Account.Engagement_Stage__c"
API_VERSION = "v61.0"


def _token():
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": os.environ["SF_CLIENT_ID"],
        "client_secret": os.environ["SF_CLIENT_SECRET"],
    }).encode()
    url = os.environ["SF_LOGIN_URL"].rstrip("/") + "/services/oauth2/token"
    with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=30) as resp:
        data = json.load(resp)
    return data["access_token"], data["instance_url"]


def _query(token, instance, soql):
    url = f"{instance}/services/data/{API_VERSION}/query?" + urllib.parse.urlencode({"q": soql})
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)["records"]


def _get(record, dotted):
    cur = record
    for part in dotted.split("."):
        cur = (cur or {}).get(part)
    return cur


def run():
    if not all(os.environ.get(k) for k in ("SF_LOGIN_URL", "SF_CLIENT_ID", "SF_CLIENT_SECRET")):
        print("  Salesforce credentials not set - skipping engagement sync")
        return {}

    contacts = load_json(config.CONTACTS_FILE, [])
    emails = sorted({c["email"].lower() for c in contacts if c.get("email")})
    custom = [f.strip() for f in (os.environ.get("SF_CONTACT_FIELDS") or DEFAULT_CUSTOM_FIELDS).split(",") if f.strip()]
    token, instance = _token()

    found = {}
    fields = STANDARD_FIELDS + custom
    for start in range(0, len(emails), 100):
        chunk = emails[start:start + 100]
        in_list = ",".join("'" + e.replace("'", "\\'") + "'" for e in chunk)
        try:
            records = _query(token, instance, f"SELECT {', '.join(fields)} FROM Contact WHERE Email IN ({in_list})")
        except urllib.error.HTTPError as err:
            if fields != STANDARD_FIELDS and err.code == 400:
                print(f"  custom fields rejected ({err.read()[:200]!r}); using standard fields only")
                fields = STANDARD_FIELDS
                records = _query(token, instance, f"SELECT {', '.join(fields)} FROM Contact WHERE Email IN ({in_list})")
            else:
                raise
        for r in records:
            found[(r.get("Email") or "").lower()] = {
                "id": r.get("Id"),
                "account_id": r.get("AccountId"),
                "account": _get(r, "Account.Name"),
                "owner": _get(r, "Owner.Name"),
                "last_activity": r.get("LastActivityDate"),
                **{f.split(".")[-1]: _get(r, f) for f in fields if f not in STANDARD_FIELDS},
            }

    stamp = now_iso()
    for c in contacts:
        sf = found.get((c.get("email") or "").lower())
        if sf:
            c["sf"] = sf
        else:
            c.pop("sf", None)
    save_json(config.CONTACTS_FILE, contacts)
    print(f"  matched {len(found)} of {len(emails)} contacts in Salesforce")
    return {"salesforce_synced_at": stamp}
