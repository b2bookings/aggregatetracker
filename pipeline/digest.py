"""Email new high-priority flags (or a full morning summary).

SMTP settings come from the environment: SMTP_HOST, SMTP_PORT (default 587),
SMTP_USER, SMTP_PASSWORD, DIGEST_TO (comma-separated), DIGEST_FROM (defaults
to SMTP_USER) and SITE_URL (link back to the tracker). For Google Workspace,
use smtp.gmail.com with an app password.
"""
import html
import os
import smtplib
from email.message import EmailMessage

import config
from util import load_json


def _li(text, href=None):
    t = html.escape(text or "")
    return f'<li><a href="{html.escape(href)}">{t}</a></li>' if href else f"<li>{t}</li>"


def _account_block(a):
    rows = []
    for s in a["sites"][:3]:
        top = s["reasons"][0]
        rows.append(_li(f'{s["name"]} ({s["state"]}): {top["text"]}', top.get("source")))
    for n in a["company_news"][:2]:
        rows.append(_li(f'Company news: {n["text"]}', n.get("source")))
    badge = ' <span style="color:#F7830F">NEW</span>' if a["is_new"] else ""
    return f'<h3 style="margin:16px 0 4px">{html.escape(a["company"])} - score {a["score"]:.0f}{badge}</h3><ul>{"".join(rows)}</ul>'


def _contact_block(c):
    why = "; ".join(r["text"] for r in c["reasons"][:2])
    badge = ' <span style="color:#F7830F">NEW</span>' if c["is_new"] else ""
    return _li(f'{c["name"]}, {c["title"]} ({c["company"]}, {c["state"]}) - {why}', c.get("linkedin")).replace("</li>", f"{badge}</li>")


def run(mode="new"):
    needed = ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "DIGEST_TO")
    if not all(os.environ.get(k) for k in needed):
        print("  SMTP settings not set - skipping digest")
        return {}

    pq = load_json(config.PRIORITY_FILE, {"accounts": [], "contacts": []})
    if mode == "summary":
        accounts, contacts = pq["accounts"][:8], pq["contacts"][:10]
        subject = "Aggregate tracker - morning priority summary"
    else:
        accounts = [a for a in pq["accounts"] if a["is_new"] and a["score"] >= config.DIGEST_MIN_SCORE]
        contacts = [c for c in pq["contacts"] if c["is_new"] and c["score"] >= config.DIGEST_MIN_SCORE]
        subject = f"Aggregate tracker - {len(accounts) + len(contacts)} new priority flag(s)"
    if not accounts and not contacts:
        print("  nothing new to send")
        return {}

    site = os.environ.get("SITE_URL", "")
    body = ['<div style="font-family:system-ui,sans-serif;color:#2A2A28;max-width:640px">']
    if accounts:
        body.append("<h2>Accounts</h2>" + "".join(_account_block(a) for a in accounts))
    if contacts:
        body.append("<h2>Contacts to reach now</h2><ul>" + "".join(_contact_block(c) for c in contacts) + "</ul>")
    if site:
        body.append(f'<p><a href="{html.escape(site)}">Open the tracker</a></p>')
    body.append("</div>")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get("DIGEST_FROM") or os.environ["SMTP_USER"]
    msg["To"] = os.environ["DIGEST_TO"]
    msg.set_content("This digest is HTML - open it in a mail client that shows HTML.")
    msg.add_alternative("".join(body), subtype="html")
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587"))) as smtp:
        smtp.starttls()
        smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        smtp.send_message(msg)
    print(f"  sent digest: {len(accounts)} accounts, {len(contacts)} contacts")
    return {}
