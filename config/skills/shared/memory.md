# Memory System

You have access to a persistent memory system. Use it to recall past conversations, save important facts, and maintain context across sessions.

## Searching memories
Run: `python /app/scripts/memory_search.py search "<query>" --limit 10`
Returns JSON array of {content, file_path, score, created_at}.
Use this when the user references something from a past conversation or when you need context.

## Saving a memory
Run: `python /app/scripts/memory_search.py save "<content>" --tags tag1,tag2`
Saves to today's daily log and indexes for future search.
Save important facts, decisions, preferences, and outcomes.

## Reading a specific memory file
Run: `python /app/scripts/memory_search.py get "<filename>"`
Available files: MEMORY.md, USER.md, memory/personal.md, memory/projects.md, memory/health.md, memory/YYYY-MM-DD.md

## When to search vs read
- **Search**: When you need to find something but don't know which file it's in
- **Read**: When you know the exact file (e.g., reading today's daily log)
- **Save**: When the user shares important information that should persist
