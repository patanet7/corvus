# Music Practice

You have access to tools for tracking piano practice, managing repertoire,
and reviewing progress.

## Logging practice
Run: `python /app/scripts/obsidian.py create "<content>" --domain music
    --title "Practice YYYY-MM-DD" --tags practice --content-type journal`

## Searching practice history
Run: `python /app/scripts/memory_search.py search "<piece name>" --limit 10`
Run: `python /app/scripts/obsidian.py search "<query>" --domain music`

## Recent practice sessions
Run: `python /app/scripts/obsidian.py recent --days 14 --domain music`

## Saving progress notes
Run: `python /app/scripts/memory_search.py save "<progress note>"
    --tags music,practice --domain music`

## When to use which
- **memory_search.py search**: Find specific facts about a piece or technique
- **obsidian.py search**: Find full practice log entries
- **obsidian.py recent**: See recent activity
- **obsidian.py create**: Save new practice logs
- **memory_search.py save**: Save a quick fact or progress note for recall
