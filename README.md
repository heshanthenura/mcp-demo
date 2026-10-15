# MCP demo

`server.py` runs everything in one process:

- REST API + stock web UI on **http://localhost:8000** (API docs at `/docs`)
- MCP server on **http://localhost:9000/mcp**

Sales are in SQLite (`sales.db`, 120 seeded sales over 90 days, with an audit history). Stock is in memory.

## Run

```powershell
venv\Scripts\python.exe server.py
```

## Connect to Claude

**Claude Code:**

```powershell
claude mcp add --transport http demo http://localhost:9000/mcp
```

Then run `/mcp` inside Claude Code to confirm `demo` is connected.

## Tools

- Sales: `list_sales`, `sales_summary` (by product/region/month/day), `add_sale`, `update_sale`, `delete_sale`, `get_history`, `reset_demo_data`
- Stock: `list_items`, `add_item`, `update_item`, `delete_item`

## Demo prompts

1. "Summarize sales by product and region. What's my best performer?"
2. "Which product's sales are growing fastest over the last 3 months?"
3. "Add a sale: 3 Laptops in the West region today at $999."
4. "Delete the sale you just added, then show me the history log."
5. "Compare my sales with how many items I have in stock."
6. "Write an executive summary of this month vs. last month."
7. Run `reset_demo_data` before each demo to start clean.
