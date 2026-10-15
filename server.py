import itertools
import random
import sqlite3
import sys
import threading
from datetime import date, datetime, timedelta
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel

DB = "sales.db"
PRODUCTS = {
    "Laptop": 999.0,
    "Phone": 599.0,
    "Headphones": 89.0,
    "Monitor": 249.0,
    "Keyboard": 49.0,
}
REGIONS = ["North", "South", "East", "West"]
GROUPS = {
    "product": "product",
    "region": "region",
    "day": "date",
    "month": "substr(date,1,7)",
}


def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def log(c, action, sale_id, details):
    c.execute(
        "INSERT INTO history (ts, action, sale_id, details) VALUES (?,?,?,?)",
        (datetime.now().isoformat(timespec="seconds"), action, sale_id, str(details)),
    )


def init_sales(reset=False):
    with db() as c:
        if reset:
            c.executescript("DROP TABLE IF EXISTS sales; DROP TABLE IF EXISTS history;")
        c.executescript(
            """CREATE TABLE IF NOT EXISTS sales (
                 id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, product TEXT,
                 region TEXT, quantity INTEGER, unit_price REAL);
               CREATE TABLE IF NOT EXISTS history (
                 id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, action TEXT,
                 sale_id INTEGER, details TEXT);"""
        )
        if c.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 0:
            rnd = random.Random(42)
            for _ in range(120):
                d = date.today() - timedelta(days=rnd.randint(0, 89))
                p = rnd.choice(list(PRODUCTS))
                qty = rnd.randint(1, 5) + (
                    2 if p == "Phone" and (date.today() - d).days < 30 else 0
                )
                c.execute(
                    "INSERT INTO sales (date, product, region, quantity, unit_price) VALUES (?,?,?,?,?)",
                    (d.isoformat(), p, rnd.choice(REGIONS), qty, PRODUCTS[p]),
                )
            log(c, "seed", None, "Seeded 120 demo sales")
    return {"status": "reset to seed data" if reset else "ready"}


def db_list_sales(product=None, region=None, start=None, end=None, limit=50):
    q, args = "SELECT * FROM sales WHERE 1=1", []
    for col, val, op in [
        ("product", product, "="),
        ("region", region, "="),
        ("date", start, ">="),
        ("date", end, "<="),
    ]:
        if val:
            q += f" AND {col} {op} ?"
            args.append(val)
    with db() as c:
        return [
            dict(r)
            for r in c.execute(
                q + " ORDER BY date DESC, id DESC LIMIT ?", args + [limit]
            )
        ]


def db_summary(group_by="product", start=None, end=None):
    if group_by not in GROUPS:
        raise ValueError(f"group_by must be one of {list(GROUPS)}")
    where, args = "WHERE 1=1", []
    for cond, val in [("date >= ?", start), ("date <= ?", end)]:
        if val:
            where += f" AND {cond}"
            args.append(val)
    with db() as c:
        return [
            dict(r)
            for r in c.execute(
                f"SELECT {GROUPS[group_by]} AS grp, COUNT(*) AS orders, SUM(quantity) AS units, "
                f"ROUND(SUM(quantity*unit_price),2) AS revenue FROM sales {where} GROUP BY grp ORDER BY grp",
                args,
            )
        ]


def db_add_sale(date, product, region, quantity, unit_price):
    with db() as c:
        cur = c.execute(
            "INSERT INTO sales (date, product, region, quantity, unit_price) VALUES (?,?,?,?,?)",
            (date, product, region, quantity, unit_price),
        )
        row = {
            "id": cur.lastrowid,
            "date": date,
            "product": product,
            "region": region,
            "quantity": quantity,
            "unit_price": unit_price,
        }
        log(c, "add", cur.lastrowid, row)
        return row


def db_update_sale(sale_id, **fields):
    fields = {k: v for k, v in fields.items() if v is not None}
    with db() as c:
        if not c.execute("SELECT 1 FROM sales WHERE id=?", (sale_id,)).fetchone():
            raise KeyError(f"Sale {sale_id} not found")
        if fields:
            c.execute(
                f"UPDATE sales SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?",
                [*fields.values(), sale_id],
            )
            log(c, "update", sale_id, fields)
        return dict(c.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone())


def db_delete_sale(sale_id):
    with db() as c:
        row = c.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
        if not row:
            raise KeyError(f"Sale {sale_id} not found")
        c.execute("DELETE FROM sales WHERE id=?", (sale_id,))
        log(c, "delete", sale_id, dict(row))
        return dict(row)


def db_history(limit=20):
    with db() as c:
        return [
            dict(r)
            for r in c.execute(
                "SELECT * FROM history ORDER BY id DESC LIMIT ?", (limit,)
            )
        ]


_ids = itertools.count(1)
stock: dict[int, dict] = {}
for _n, _q, _p in [
    ("Blue T-Shirt", 20, 15.99),
    ("Coffee Mug", 50, 8.50),
    ("Notebook", 100, 3.25),
]:
    _i = next(_ids)
    stock[_i] = {"id": _i, "name": _n, "quantity": _q, "price": _p}


def stock_add(name, quantity, price):
    i = next(_ids)
    stock[i] = {"id": i, "name": name, "quantity": quantity, "price": price}
    return stock[i]


def stock_update(item_id, **fields):
    if item_id not in stock:
        raise KeyError(f"Item {item_id} not found")
    stock[item_id].update({k: v for k, v in fields.items() if v is not None})
    return stock[item_id]


def stock_delete(item_id):
    if item_id not in stock:
        raise KeyError(f"Item {item_id} not found")
    return stock.pop(item_id)


class Sale(BaseModel):
    date: str
    product: str
    region: str
    quantity: int
    unit_price: float


class SaleUpdate(BaseModel):
    date: Optional[str] = None
    product: Optional[str] = None
    region: Optional[str] = None
    quantity: Optional[int] = None
    unit_price: Optional[float] = None


class Item(BaseModel):
    name: str
    quantity: int
    price: float


class ItemUpdate(BaseModel):
    name: Optional[str] = None
    quantity: Optional[int] = None
    price: Optional[float] = None


app = FastAPI(title="Sales + Stock demo")
templates = Jinja2Templates(directory="templates")


def http(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/sales")
def api_sales(
    product: Optional[str] = None,
    region: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = 200,
):
    return db_list_sales(product, region, start, end, limit)


@app.post("/api/sales")
def api_add_sale(s: Sale):
    return db_add_sale(**s.model_dump())


@app.put("/api/sales/{sale_id}")
def api_update_sale(sale_id: int, s: SaleUpdate):
    return http(db_update_sale, sale_id, **s.model_dump(exclude_unset=True))


@app.delete("/api/sales/{sale_id}")
def api_delete_sale(sale_id: int):
    return http(db_delete_sale, sale_id)


@app.get("/api/summary")
def api_summary(
    group_by: str = "product", start: Optional[str] = None, end: Optional[str] = None
):
    return http(db_summary, group_by, start, end)


@app.get("/api/history")
def api_history(limit: int = 50):
    return db_history(limit)


@app.post("/api/reset")
def api_reset():
    return init_sales(reset=True)


@app.get("/api/items")
def api_items():
    return list(stock.values())


@app.post("/api/items")
def api_add_item(item: Item):
    return stock_add(**item.model_dump())


@app.put("/api/items/{item_id}")
def api_update_item(item_id: int, item: ItemUpdate):
    return http(stock_update, item_id, **item.model_dump(exclude_unset=True))


@app.delete("/api/items/{item_id}")
def api_delete_item(item_id: int):
    return http(stock_delete, item_id)


@app.get("/", response_class=HTMLResponse)
def ui(request: Request):
    return templates.TemplateResponse(request, "index.html")


mcp = MCPServer("sales-stock-demo")


@mcp.tool()
def list_sales(
    product: Optional[str] = None,
    region: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """List sales records (newest first). Dates are YYYY-MM-DD. Filter by product/region/date range."""
    return db_list_sales(product, region, start, end, limit)


@mcp.tool()
def sales_summary(
    group_by: str = "product", start: Optional[str] = None, end: Optional[str] = None
) -> list[dict]:
    """Aggregate orders, units and revenue. group_by: product | region | month | day."""
    return db_summary(group_by, start, end)


@mcp.tool()
def add_sale(
    date: str, product: str, region: str, quantity: int, unit_price: float
) -> dict:
    """Record a new sale. date is YYYY-MM-DD."""
    return db_add_sale(date, product, region, quantity, unit_price)


@mcp.tool()
def update_sale(
    sale_id: int,
    date: Optional[str] = None,
    product: Optional[str] = None,
    region: Optional[str] = None,
    quantity: Optional[int] = None,
    unit_price: Optional[float] = None,
) -> dict:
    """Update fields on an existing sale. Only provided fields change."""
    return db_update_sale(
        sale_id,
        date=date,
        product=product,
        region=region,
        quantity=quantity,
        unit_price=unit_price,
    )


@mcp.tool()
def delete_sale(sale_id: int) -> dict:
    """Delete a sale by id."""
    return db_delete_sale(sale_id)


@mcp.tool()
def get_history(limit: int = 20) -> list[dict]:
    """Audit log of every sales add/update/delete, newest first."""
    return db_history(limit)


@mcp.tool()
def reset_demo_data() -> dict:
    """Wipe all sales changes and restore the original seed data."""
    return init_sales(reset=True)


@mcp.tool()
def list_items() -> list[dict]:
    """List all items currently in the shop's stock."""
    return list(stock.values())


@mcp.tool()
def add_item(name: str, quantity: int, price: float) -> dict:
    """Add a new item to the shop's stock."""
    return stock_add(name, quantity, price)


@mcp.tool()
def update_item(
    item_id: int,
    name: Optional[str] = None,
    quantity: Optional[int] = None,
    price: Optional[float] = None,
) -> dict:
    """Update fields on an existing stock item. Only provided fields change."""
    return stock_update(item_id, name=name, quantity=quantity, price=price)


@mcp.tool()
def delete_item(item_id: int) -> dict:
    """Delete an item from the shop's stock."""
    return stock_delete(item_id)


if __name__ == "__main__":
    init_sales()
    threading.Thread(
        target=lambda: uvicorn.run(app, port=8000, log_level="warning"), daemon=True
    ).start()
    if "--stdio" in sys.argv:
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="streamable-http", port=9000)
