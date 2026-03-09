# Harlequin — Design Reference Patterns

Source: https://github.com/tconbeer/harlequin (MIT License)

## 3-Panel Layout with Sidebar Toggle

Harlequin's layout is the gold standard for sidebar + main content + results:

```python
# harlequin/app.py (simplified layout concept)
class HarlequinApp:
    """Three-panel layout with toggleable sidebar."""

    show_sidebar: reactive[bool] = reactive(True)

    def compose(self):
        """
        Layout ratio: sidebar 1:3 with main content.

        ┌──────────┬───────────────────────────┐
        │ Sidebar  │ Main Content              │
        │ (1/4)    │ (3/4)                     │
        │          │                           │
        │ Tables   │ Query Editor              │
        │  └ db    │                           │
        │   └ tbl  │                           │
        │    └ col ├───────────────────────────┤
        │          │ Results                   │
        │          │ (tabbed)                  │
        └──────────┴───────────────────────────┘
        """
        yield Sidebar()  # Left panel
        yield Container(
            QueryEditor(),    # Top
            ResultsViewer(),  # Bottom (tabbed)
        )

    def toggle_sidebar(self):
        """Collapse/expand sidebar."""
        self.show_sidebar = not self.show_sidebar
        # When collapsed, sidebar gets display:none
        # Main content expands to fill
```

## Disabled Widget Collapsing

When a panel is hidden, it collapses via CSS-like display toggling:

```python
# harlequin/components/sidebar.py (simplified)
class Sidebar:
    """Collapsible sidebar with tree view."""

    def watch_show_sidebar(self, show: bool):
        if show:
            self.styles.display = "block"
            self.styles.width = "25%"
        else:
            self.styles.display = "none"
            # Main content auto-expands to 100%
```

## TabbedContent for Results

Multiple result sets shown as tabs:

```python
# harlequin/components/results.py (simplified)
class ResultsViewer:
    """Tabbed results display."""

    def add_result(self, name: str, data: list[dict]):
        """Add a new result tab."""
        tab = ResultTab(name=name, data=data)
        self.tabs.append(tab)
        self.active_tab = tab

    def render_tab(self, tab: ResultTab):
        """Render result as Rich Table."""
        table = Table(title=tab.name)
        for col in tab.columns:
            table.add_column(col)
        for row in tab.rows:
            table.add_row(*row)
        return table
```

## RunQueryBar — Status Strip

```python
# harlequin/components/run_query_bar.py (simplified)
class RunQueryBar:
    """Status strip at bottom of screen."""

    def render(self):
        """
        ┌──────────────────────────────────────────────┐
        │ Ctrl+Enter: Run │ F5: Run All │ 2.3s │ 150 rows │
        └──────────────────────────────────────────────┘
        """
        return StatusBar(
            items=[
                ("Ctrl+Enter", "Run"),
                ("F5", "Run All"),
                (f"{self.elapsed:.1f}s", ""),
                (f"{self.row_count} rows", ""),
            ]
        )
```

## Tree View — Database Browser

The sidebar uses a tree structure for hierarchical navigation:

```python
# harlequin/components/data_catalog.py (simplified)
class DataCatalog:
    """Tree view for database objects.

    Database
    ├── Schema
    │   ├── Table
    │   │   ├── column (int)
    │   │   └── column (text)
    │   └── View
    └── Schema
    """

    def build_tree(self, catalog: list[DatabaseObject]):
        tree = Tree("Databases")
        for db in catalog:
            db_node = tree.add(f"[bold]{db.name}")
            for schema in db.schemas:
                schema_node = db_node.add(schema.name)
                for table in schema.tables:
                    table_node = schema_node.add(f"[green]{table.name}")
                    for col in table.columns:
                        table_node.add(f"[dim]{col.name} ({col.type})")
        return tree
```

## Key Takeaway for Corvus TUI

- **Sidebar ratio**: 1:3 (25% sidebar, 75% main) is the sweet spot
- **Toggle pattern**: `display: none` to collapse, auto-expand main
- **Tree view**: Rich Tree() for agent/session hierarchies
- **Tabs**: TabbedContent for multiple active views (workers, sessions, tools)
- **Status strip**: Compact key hints + live metrics at bottom
- **This is our primary reference for the pop-out panel pattern**
