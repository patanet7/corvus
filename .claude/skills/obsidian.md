# Obsidian Vault

You have direct access to the Obsidian vault for reading, searching, and creating notes. The vault is the canonical markdown store for all memory and knowledge.

## Searching notes
Run: `python /app/scripts/obsidian.py search "<query>" --limit 10`
Optionally filter by domain: `--domain personal`
Returns JSON array of {path, title, score, frontmatter, modified}.
Use this to find notes by keyword across filenames, tags, and body content.

## Reading a note
Run: `python /app/scripts/obsidian.py read "<relative/path/to/note.md>"`
Returns JSON with {path, title, frontmatter, body, modified, size_bytes}.
Use the path from search or list results.

## Listing notes
Run: `python /app/scripts/obsidian.py list --domain personal --tag health`
Both `--domain` and `--tag` are optional filters. Returns JSON array.
Use this to browse notes in a specific domain or with a specific tag.

## Recently modified notes
Run: `python /app/scripts/obsidian.py recent --days 7 --domain work`
Both `--days` (default 7) and `--domain` are optional. Returns JSON sorted by most recent first.
Use this for catching up on recent activity.

## Creating a note
Run: `python /app/scripts/obsidian.py create "<content>" --domain personal --title "My Note" --tags health,medication`
Required: `--domain` and `--title`. Optional: `--tags`, `--content-type` (journal, meeting, task, project, runbook), `--importance` (0.0-1.0).
Returns JSON with {status, path, title, domain}.

## Domain routing
Notes are organized by domain: personal, work, homelab, finance, music, email, docs, home, shared.
Each domain maps to a subfolder in the vault. Content types (journal, meeting, task, etc.) create additional subfolders.

## Conventions
- Filenames are kebab-case: `my-important-note.md`
- Frontmatter always includes: tags, created, source, importance
- Tags are hierarchical: `homelab/docker`, `personal/health`
- Wiki links `[[like this]]` are preserved for cross-referencing
- Dates in content are auto-linked as `[[YYYY-MM-DD]]`

## When to use which command
- **search**: Find notes matching a keyword — don't know the exact path
- **read**: Read a specific note — you have the path from search/list
- **list**: Browse all notes in a domain or with a tag
- **recent**: See what's been active lately
- **create**: Save new knowledge to the vault
