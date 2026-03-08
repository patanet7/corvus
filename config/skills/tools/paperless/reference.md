# Paperless-ngx API Reference

## Document Search
Full-text search across all document content, titles, and tags. Returns document ID, title, match score, and snippet.

## Tags
Tags are labels applied to documents for organization. Use `tags` to list available tags, then `tag` to apply them.

## Bulk Edit Methods
- `set_tags` — Set tags on multiple documents
- `add_tags` — Add tags to multiple documents
- `remove_tags` — Remove tags from multiple documents
- `set_correspondent` — Set correspondent on multiple documents

## Parameters Format
The `--parameters` flag accepts a JSON object specific to each method, e.g.:
- `--method set_tags --parameters '{"tags": [1, 2, 3]}'`
