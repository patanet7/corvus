# Email Inbox Management

You have access to a multi-provider email management system. Use it to triage, search, label, and clean up inboxes across Gmail and Yahoo.

## Gmail Operations

**Search Gmail:**
```bash
python /app/scripts/inbox.py gmail-search "from:github.com subject:PR" --limit 10
python /app/scripts/inbox.py gmail-search "is:important newer_than:7d" --limit 20
python /app/scripts/inbox.py gmail-search "has:attachment filename:pdf" --label work
```
Returns JSON: `{ "count": N, "messages": [{ "id", "thread_id", "subject", "from", "to", "date", "snippet", "labels" }] }`

**List unread Gmail:**
```bash
python /app/scripts/inbox.py gmail-unread --limit 10
```

**List Gmail labels:**
```bash
python /app/scripts/inbox.py gmail-labels
```
Returns JSON: `{ "count": N, "labels": [{ "id", "name", "type" }] }`

**Bulk label messages:**
```bash
python /app/scripts/inbox.py gmail-bulk-label "ToReview" --query "from:jira newer_than:7d"
```
Creates the label if it doesn't exist. Returns count of messages labeled.

## Yahoo Operations

**Search Yahoo Mail:**
```bash
python /app/scripts/inbox.py yahoo-search "invoice" --limit 10 --folder INBOX
```
Returns JSON: `{ "count": N, "messages": [{ "subject", "from", "to", "date", "uid", "folder" }], "provider": "yahoo" }`

**List unread Yahoo messages:**
```bash
python /app/scripts/inbox.py yahoo-unread --limit 10
```

**List Yahoo folders:**
```bash
python /app/scripts/inbox.py yahoo-folders
```

## Cross-Provider Triage

**Triage unread messages into categories:**
```bash
python /app/scripts/inbox.py triage --provider all
python /app/scripts/inbox.py triage --provider gmail
python /app/scripts/inbox.py triage --provider yahoo
```
Categorizes into: `action` (needs response), `delegate` (forward/FYI), `archive` (informational), `delete` (promotional/spam), `review` (needs human judgment).

Returns JSON: `{ "triage": { "action": [...], "delegate": [...], ... }, "summary": { "action": N, ... }, "total": N }`

## Cleanup

**Bulk cleanup old messages:**
```bash
python /app/scripts/inbox.py cleanup --provider gmail --older-than 30d --dry-run
python /app/scripts/inbox.py cleanup --provider yahoo --older-than 60d
```
Age formats: `30d` (days), `2w` (weeks), `6m` (months), `24h` (hours).
Gmail cleanup archives messages (removes INBOX label). Yahoo cleanup deletes messages.
Always use `--dry-run` first to preview.

## Memory (shared with all agents)
```bash
python /app/scripts/memory_search.py search "email filter rules" --limit 5
python /app/scripts/memory_search.py save "Set up auto-label for GitHub notifications" --tags email,gmail --domain personal
```

## Important Notes

- **Gmail send/archive** uses MCP tools (confirm-gated) — not this script.
- **This script** handles search, triage, labeling, and cleanup — bulk read operations.
- **Never expose credentials.** All secrets are in env vars.
- **Always dry-run cleanup first** before executing destructive operations.
