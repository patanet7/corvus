"""Tool catalog — maps module names to MCPToolDef definitions.

Each module declares its tools with:
- name: tool identifier (module_action format, matching existing tool_registry names)
- description: minimal (~30 tokens) for context window
- requires_credentials: env var names the tool needs
- is_mutation: whether the tool modifies state
- input_schema: JSON Schema for typed inputs
"""

from collections.abc import Callable

from corvus.security.mcp_tool import MCPToolDef


def get_module_tool_defs(module_name: str, module_config: dict) -> list[MCPToolDef]:
    """Get MCPToolDef instances for a module based on its config.

    Only returns tools that are enabled in the module config.
    """
    builders = _MODULE_BUILDERS.get(module_name)
    if not builders:
        return []
    return builders(module_config)


def _obsidian_tools(cfg: dict) -> list[MCPToolDef]:
    tools: list[MCPToolDef] = []
    if cfg.get("read", True):
        tools.append(MCPToolDef(
            name="obsidian_search",
            description="Search Obsidian vault notes by query string",
            requires_credentials=["OBSIDIAN_URL", "OBSIDIAN_API_KEY"],
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "context_length": {"type": "integer", "default": 100},
                },
                "required": ["query"],
            },
        ))
        tools.append(MCPToolDef(
            name="obsidian_read",
            description="Read an Obsidian note by path (content + frontmatter)",
            requires_credentials=["OBSIDIAN_URL", "OBSIDIAN_API_KEY"],
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
            },
        ))
    if cfg.get("write", False):
        tools.append(MCPToolDef(
            name="obsidian_write",
            description="Create or overwrite an Obsidian vault note",
            requires_credentials=["OBSIDIAN_URL", "OBSIDIAN_API_KEY"],
            is_mutation=True,
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        ))
        tools.append(MCPToolDef(
            name="obsidian_append",
            description="Append content to an Obsidian vault note",
            requires_credentials=["OBSIDIAN_URL", "OBSIDIAN_API_KEY"],
            is_mutation=True,
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        ))
    return tools


def _ha_tools(cfg: dict) -> list[MCPToolDef]:
    tools: list[MCPToolDef] = []
    tools.append(MCPToolDef(
        name="ha_list_entities",
        description="List Home Assistant entities, optionally filtered by domain",
        requires_credentials=["HA_URL", "HA_TOKEN"],
        input_schema={
            "type": "object",
            "properties": {
                "domain": {"type": "string"},
            },
        },
    ))
    tools.append(MCPToolDef(
        name="ha_get_state",
        description="Get current state and attributes of an HA entity",
        requires_credentials=["HA_URL", "HA_TOKEN"],
        input_schema={
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
            },
            "required": ["entity_id"],
        },
    ))
    tools.append(MCPToolDef(
        name="ha_call_service",
        description="Call a Home Assistant service to control a device",
        requires_credentials=["HA_URL", "HA_TOKEN"],
        is_mutation=True,
        input_schema={
            "type": "object",
            "properties": {
                "domain": {"type": "string"},
                "service": {"type": "string"},
                "entity_id": {"type": "string"},
                "data": {"type": "object"},
            },
            "required": ["domain", "service"],
        },
    ))
    return tools


def _paperless_tools(cfg: dict) -> list[MCPToolDef]:
    tools: list[MCPToolDef] = []
    tools.append(MCPToolDef(
        name="paperless_search",
        description="Search Paperless-NGX documents by query",
        requires_credentials=["PAPERLESS_URL", "PAPERLESS_API_TOKEN"],
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "tag": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    ))
    tools.append(MCPToolDef(
        name="paperless_read",
        description="Read a single Paperless document by ID",
        requires_credentials=["PAPERLESS_URL", "PAPERLESS_API_TOKEN"],
        input_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
            },
            "required": ["id"],
        },
    ))
    tools.append(MCPToolDef(
        name="paperless_tags",
        description="List all Paperless-NGX tags",
        requires_credentials=["PAPERLESS_URL", "PAPERLESS_API_TOKEN"],
        input_schema={"type": "object", "properties": {}},
    ))
    tools.append(MCPToolDef(
        name="paperless_tag",
        description="Add a tag to a Paperless document",
        requires_credentials=["PAPERLESS_URL", "PAPERLESS_API_TOKEN"],
        is_mutation=True,
        input_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "tag": {"type": "string"},
            },
            "required": ["id", "tag"],
        },
    ))
    tools.append(MCPToolDef(
        name="paperless_bulk_edit",
        description="Batch tag/correspondent changes on multiple documents",
        requires_credentials=["PAPERLESS_URL", "PAPERLESS_API_TOKEN"],
        is_mutation=True,
        input_schema={
            "type": "object",
            "properties": {
                "documents": {"type": "array", "items": {"type": "integer"}},
                "method": {"type": "string"},
                "parameters": {"type": "object"},
            },
            "required": ["documents", "method", "parameters"],
        },
    ))
    return tools


def _firefly_tools(cfg: dict) -> list[MCPToolDef]:
    tools: list[MCPToolDef] = []
    tools.append(MCPToolDef(
        name="firefly_transactions",
        description="Query Firefly III transactions with optional filters",
        requires_credentials=["FIREFLY_URL", "FIREFLY_API_TOKEN"],
        input_schema={
            "type": "object",
            "properties": {
                "start": {"type": "string"},
                "end": {"type": "string"},
                "limit": {"type": "integer"},
                "type": {"type": "string"},
            },
        },
    ))
    tools.append(MCPToolDef(
        name="firefly_accounts",
        description="List Firefly III accounts with optional type filter",
        requires_credentials=["FIREFLY_URL", "FIREFLY_API_TOKEN"],
        input_schema={
            "type": "object",
            "properties": {
                "type": {"type": "string"},
            },
        },
    ))
    tools.append(MCPToolDef(
        name="firefly_categories",
        description="List Firefly III spending categories",
        requires_credentials=["FIREFLY_URL", "FIREFLY_API_TOKEN"],
        input_schema={"type": "object", "properties": {}},
    ))
    tools.append(MCPToolDef(
        name="firefly_summary",
        description="Get Firefly III spending summary for a date range",
        requires_credentials=["FIREFLY_URL", "FIREFLY_API_TOKEN"],
        input_schema={
            "type": "object",
            "properties": {
                "start": {"type": "string"},
                "end": {"type": "string"},
            },
        },
    ))
    tools.append(MCPToolDef(
        name="firefly_create_transaction",
        description="Create a new Firefly III transaction",
        requires_credentials=["FIREFLY_URL", "FIREFLY_API_TOKEN"],
        is_mutation=True,
        input_schema={
            "type": "object",
            "properties": {
                "description": {"type": "string"},
                "amount": {"type": "number"},
                "type": {"type": "string", "default": "withdrawal"},
                "source_name": {"type": "string"},
                "destination_name": {"type": "string"},
                "category_name": {"type": "string"},
                "date": {"type": "string"},
                "currency_code": {"type": "string"},
            },
            "required": ["description", "amount"],
        },
    ))
    return tools


def _email_tools(cfg: dict) -> list[MCPToolDef]:
    # Email uses OAuth tokens managed by GoogleClient/YahooClient,
    # not direct env var credentials.
    tools: list[MCPToolDef] = []
    read_only = cfg.get("read_only", False)

    tools.append(MCPToolDef(
        name="email_list",
        description="Search email messages across Gmail or Yahoo",
        requires_credentials=[],
        input_schema={
            "type": "object",
            "properties": {
                "provider": {"type": "string", "default": "gmail"},
                "query": {"type": "string", "default": "is:inbox"},
                "account": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    ))
    tools.append(MCPToolDef(
        name="email_read",
        description="Read a full email message by ID",
        requires_credentials=[],
        input_schema={
            "type": "object",
            "properties": {
                "provider": {"type": "string", "default": "gmail"},
                "message_id": {"type": "string"},
                "account": {"type": "string"},
            },
            "required": ["message_id"],
        },
    ))

    if not read_only:
        tools.append(MCPToolDef(
            name="email_draft",
            description="Create a Gmail draft message",
            requires_credentials=[],
            is_mutation=True,
            input_schema={
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "in_reply_to": {"type": "string"},
                    "account": {"type": "string"},
                },
                "required": ["to", "subject", "body"],
            },
        ))
        tools.append(MCPToolDef(
            name="email_send",
            description="Send an email or draft message",
            requires_credentials=[],
            is_mutation=True,
            input_schema={
                "type": "object",
                "properties": {
                    "draft_id": {"type": "string"},
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "account": {"type": "string"},
                },
            },
        ))
        tools.append(MCPToolDef(
            name="email_archive",
            description="Archive an email message (remove from inbox)",
            requires_credentials=[],
            is_mutation=True,
            input_schema={
                "type": "object",
                "properties": {
                    "provider": {"type": "string", "default": "gmail"},
                    "message_id": {"type": "string"},
                    "account": {"type": "string"},
                },
                "required": ["message_id"],
            },
        ))
        tools.append(MCPToolDef(
            name="email_label",
            description="Add or remove Gmail labels from a message",
            requires_credentials=[],
            is_mutation=True,
            input_schema={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string"},
                    "add_labels": {"type": "array", "items": {"type": "string"}},
                    "remove_labels": {"type": "array", "items": {"type": "string"}},
                    "account": {"type": "string"},
                },
                "required": ["message_id"],
            },
        ))
        tools.append(MCPToolDef(
            name="email_labels",
            description="List available Gmail labels",
            requires_credentials=[],
            input_schema={
                "type": "object",
                "properties": {
                    "account": {"type": "string"},
                },
            },
        ))
    return tools


def _drive_tools(cfg: dict) -> list[MCPToolDef]:
    # Drive uses OAuth tokens managed by GoogleClient, not direct env vars.
    tools: list[MCPToolDef] = []
    read_only = cfg.get("read_only", False)

    tools.append(MCPToolDef(
        name="drive_list",
        description="List or search files in Google Drive",
        requires_credentials=[],
        input_schema={
            "type": "object",
            "properties": {
                "account": {"type": "string"},
                "query": {"type": "string"},
                "folder_id": {"type": "string"},
                "limit": {"type": "integer", "default": 100},
            },
        },
    ))
    tools.append(MCPToolDef(
        name="drive_read",
        description="Read file metadata and content from Google Drive",
        requires_credentials=[],
        input_schema={
            "type": "object",
            "properties": {
                "file_id": {"type": "string"},
                "account": {"type": "string"},
            },
            "required": ["file_id"],
        },
    ))

    if not read_only:
        tools.append(MCPToolDef(
            name="drive_create",
            description="Create a file or Google Doc in Drive",
            requires_credentials=[],
            is_mutation=True,
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "account": {"type": "string"},
                    "mime_type": {"type": "string"},
                    "folder_id": {"type": "string"},
                },
                "required": ["name"],
            },
        ))
        tools.append(MCPToolDef(
            name="drive_edit",
            description="Edit a Google Doc using batchUpdate",
            requires_credentials=[],
            is_mutation=True,
            input_schema={
                "type": "object",
                "properties": {
                    "file_id": {"type": "string"},
                    "account": {"type": "string"},
                    "insertions": {"type": "array"},
                    "replacements": {"type": "array"},
                },
                "required": ["file_id"],
            },
        ))
        tools.append(MCPToolDef(
            name="drive_move",
            description="Move a file to a different Drive folder",
            requires_credentials=[],
            is_mutation=True,
            input_schema={
                "type": "object",
                "properties": {
                    "file_id": {"type": "string"},
                    "folder_id": {"type": "string"},
                    "account": {"type": "string"},
                },
                "required": ["file_id", "folder_id"],
            },
        ))
        tools.append(MCPToolDef(
            name="drive_delete",
            description="Move a Drive file to trash",
            requires_credentials=[],
            is_mutation=True,
            input_schema={
                "type": "object",
                "properties": {
                    "file_id": {"type": "string"},
                    "account": {"type": "string"},
                },
                "required": ["file_id"],
            },
        ))
        tools.append(MCPToolDef(
            name="drive_permanent_delete",
            description="Permanently delete a Drive file",
            requires_credentials=[],
            is_mutation=True,
            input_schema={
                "type": "object",
                "properties": {
                    "file_id": {"type": "string"},
                    "account": {"type": "string"},
                },
                "required": ["file_id"],
            },
        ))
        tools.append(MCPToolDef(
            name="drive_share",
            description="Share a Drive file with a user",
            requires_credentials=[],
            is_mutation=True,
            input_schema={
                "type": "object",
                "properties": {
                    "file_id": {"type": "string"},
                    "email": {"type": "string"},
                    "role": {"type": "string", "default": "reader"},
                    "account": {"type": "string"},
                },
                "required": ["file_id", "email"],
            },
        ))
        tools.append(MCPToolDef(
            name="drive_cleanup",
            description="Find and trash old Drive files matching criteria",
            requires_credentials=[],
            is_mutation=True,
            input_schema={
                "type": "object",
                "properties": {
                    "account": {"type": "string"},
                    "older_than": {"type": "integer"},
                    "query": {"type": "string"},
                    "dry_run": {"type": "boolean", "default": True},
                },
            },
        ))
    return tools


def _memory_tools(cfg: dict) -> list[MCPToolDef]:
    """Memory tools use the local MemoryHub — no external credentials needed."""
    return [
        MCPToolDef(
            name="memory_search",
            description="Search memories by semantic query",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                    "domain": {"type": "string"},
                },
                "required": ["query"],
            },
        ),
        MCPToolDef(
            name="memory_save",
            description="Save a new memory to the agent's domain",
            is_mutation=True,
            input_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "visibility": {"type": "string", "enum": ["private", "shared"], "default": "private"},
                    "tags": {"type": "string", "default": ""},
                    "importance": {"type": "number", "default": 0.5},
                },
                "required": ["content"],
            },
        ),
        MCPToolDef(
            name="memory_get",
            description="Retrieve a specific memory by its ID",
            input_schema={
                "type": "object",
                "properties": {
                    "record_id": {"type": "string"},
                },
                "required": ["record_id"],
            },
        ),
        MCPToolDef(
            name="memory_list",
            description="List recent memories, optionally filtered by domain",
            input_schema={
                "type": "object",
                "properties": {
                    "domain": {"type": "string"},
                    "limit": {"type": "integer", "default": 20},
                },
            },
        ),
        MCPToolDef(
            name="memory_forget",
            description="Soft-delete a memory by ID (own domain only)",
            is_mutation=True,
            input_schema={
                "type": "object",
                "properties": {
                    "record_id": {"type": "string"},
                },
                "required": ["record_id"],
            },
        ),
    ]


_MODULE_BUILDERS: dict[str, Callable[[dict], list[MCPToolDef]]] = {
    "obsidian": _obsidian_tools,
    "ha": _ha_tools,
    "paperless": _paperless_tools,
    "firefly": _firefly_tools,
    "email": _email_tools,
    "drive": _drive_tools,
    "memory": _memory_tools,
}
