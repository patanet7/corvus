# Paperless-ngx Document Management

You have access to a Paperless-ngx instance for document management. Use it to search, retrieve, and tag scanned documents, receipts, invoices, and correspondence.

## Searching documents
Run: `python /app/scripts/paperless.py search "<query>" --limit 10`
Returns JSON array of `{id, title, created, tags, correspondent, document_type, content, score, highlights}`.
Use this when the user asks about a document, receipt, invoice, or letter.

Optionally filter by tag: `python /app/scripts/paperless.py search "<query>" --tag "invoice"`

## Getting a specific document
Run: `python /app/scripts/paperless.py get <doc_id>`
Returns JSON with `{id, title, content, created, modified, added, tags, correspondent, document_type, archive_serial_number, original_file_name}`.
Use this when you have a document ID and need its full content or metadata.

## Listing all tags
Run: `python /app/scripts/paperless.py tags`
Returns JSON array of `{id, name, color, document_count}`.
Use this when the user wants to see available categories or organize documents.

## Tagging a document
Run: `python /app/scripts/paperless.py tag <doc_id> "<tag_name>"`
Adds the named tag to the document. Returns `{status, document_id, tag_name, tag_id}`.
Use this when the user wants to categorize or label a document.

## When to use which command
- **Search**: User asks "find my electric bill" or "show recent invoices"
- **Get**: User asks about a specific document after seeing search results
- **Tags**: User asks "what categories exist?" or "show me all tags"
- **Tag**: User asks "mark this as paid" or "tag document 42 as invoice"

## Notes
- Tag names are case-insensitive when resolving
- Search results include content snippets (first 500 chars) and relevance scores
- Tags in search results are returned as integer IDs — use `tags` command to map to names
- All output is JSON to stdout; errors are JSON to stderr with non-zero exit code
