"""
Schema Management Module
Features:
1. Auto-extract database schema
2. Business term dictionary mapping
3. Dynamic schema pruning (expose only relevant tables/columns to LLM)
4. Enhanced field descriptions
"""
import sqlite3
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

@dataclass
class ColumnInfo:
    name: str
    type: str
    description: str = ""
    is_primary_key: bool = False
    foreign_key: Optional[str] = None

@dataclass
class TableInfo:
    name: str
    description: str = ""
    columns: List[ColumnInfo] = None

    def __post_init__(self):
        if self.columns is None:
            self.columns = []

class SchemaManager:
    BUSINESS_TERMS = {
        "sales": ["orders", "order_items"],
        "order": ["orders", "order_items"],
        "product": ["products"],
        "item": ["products"],
        "customer": ["customers"],
        "user": ["customers"],
        "return": ["returns"],

        "sales_amount": ["order_items.unit_price * order_items.quantity"],
        "revenue": ["order_items.unit_price * order_items.quantity"],
        "income": ["order_items.unit_price * order_items.quantity"],
        "quantity": ["order_items.quantity"],
        "unit_price": ["order_items.unit_price", "products.sale_price"],
        "cost": ["products.cost_price"],
        "profit": ["(order_items.unit_price - products.cost_price) * order_items.quantity"],
        "profit_margin": ["(order_items.unit_price - products.cost_price) / order_items.unit_price"],

        "region": ["orders.region", "customers.region"],
        "area": ["orders.region", "customers.region"],
        "province": ["orders.province"],
        "city": ["orders.city"],

        "time": ["orders.order_date"],
        "date": ["orders.order_date"],
        "month": ["strftime('%Y-%m', orders.order_date)"],
        "quarter": ["strftime('%Y-Q' || ((strftime('%m', orders.order_date) - 1) / 3 + 1), orders.order_date)"],
        "year": ["strftime('%Y', orders.order_date)"],

        "category": ["products.category"],
        "type": ["products.category", "products.sub_category"],
        "brand": ["products.brand"],
        "channel": ["orders.channel"],

        "customer_type": ["customers.customer_type"],
        "VIP": ["customers.vip_level"],
        "member_level": ["customers.vip_level"],

        "return_rate": ["COUNT(DISTINCT returns.order_id) * 1.0 / COUNT(DISTINCT orders.order_id)"],
        "refund": ["returns.refund_amount"],
        "return_reason": ["returns.return_reason"],
    }

    TIME_EXPRESSIONS = {
        "today": "date('now')",
        "yesterday": "date('now', '-1 day')",
        "this_week": "date('now', 'weekday 0', '-7 days')",
        "last_week": "date('now', 'weekday 0', '-14 days')",
        "this_month": "date('now', 'start of month')",
        "last_month": "date('now', 'start of month', '-1 month')",
        "this_quarter": "date('now', 'start of month', '-' || ((strftime('%m', 'now') - 1) % 3) || ' months')",
        "last_quarter": "date('now', 'start of month', '-' || ((strftime('%m', 'now') - 1) % 3 + 3) || ' months')",
        "this_year": "date('now', 'start of year')",
        "last_year": "date('now', 'start of year', '-1 year')",
        "last_7_days": "date('now', '-7 days')",
        "last_30_days": "date('now', '-30 days')",
        "last_90_days": "date('now', '-90 days')",
    }

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.schema_cache: Dict[str, TableInfo] = {}
        self._load_schema()

    def _load_schema(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()

        for (table_name,) in tables:
            if table_name.startswith("sqlite_"):
                continue

            table_info = TableInfo(name=table_name)
            table_info.description = self._get_table_description(table_name)

            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = cursor.fetchall()

            for col in columns:
                col_id, name, col_type, not_null, default_val, is_pk = col
                col_info = ColumnInfo(
                    name=name,
                    type=col_type or "TEXT",
                    description=self._get_column_description(table_name, name),
                    is_primary_key=is_pk == 1
                )
                table_info.columns.append(col_info)

            cursor.execute(f"PRAGMA foreign_key_list({table_name})")
            fks = cursor.fetchall()
            for fk in fks:
                _, _, ref_table, from_col, to_col, *_ = fk
                for col in table_info.columns:
                    if col.name == from_col:
                        col.foreign_key = f"{ref_table}.{to_col}"

            self.schema_cache[table_name] = table_info

        conn.close()

    def _get_table_description(self, table_name: str) -> str:
        descriptions = {
            "products": "Product info table, contains all product basic information",
            "orders": "Order master table, records basic info of each order",
            "order_items": "Order detail table, records product details in orders",
            "customers": "Customer info table",
            "returns": "Return record table"
        }
        return descriptions.get(table_name, f"{table_name} table")

    def _get_column_description(self, table_name: str, column_name: str) -> str:
        descriptions = {
            ("products", "product_id"): "Product unique ID",
            ("products", "product_name"): "Product name",
            ("products", "category"): "Product category (Digital/Electronics/Clothing/Food/Home)",
            ("products", "sub_category"): "Product sub-category",
            ("products", "brand"): "Brand",
            ("products", "cost_price"): "Cost price",
            ("products", "sale_price"): "Sale price",
            ("products", "supplier"): "Supplier",

            ("orders", "order_id"): "Order unique ID",
            ("orders", "customer_id"): "Customer ID, FK to customers",
            ("orders", "order_date"): "Order date, format YYYY-MM-DD",
            ("orders", "region"): "Sales region (East/South/North/Southwest/Central)",
            ("orders", "province"): "Province",
            ("orders", "city"): "City",
            ("orders", "channel"): "Sales channel (Online/Offline/3rd-party/Enterprise)",
            ("orders", "payment_method"): "Payment method",
            ("orders", "order_status"): "Order status",
            ("orders", "discount_rate"): "Discount rate",

            ("order_items", "item_id"): "Detail unique ID",
            ("order_items", "order_id"): "Order ID, FK to orders",
            ("order_items", "product_id"): "Product ID, FK to products",
            ("order_items", "quantity"): "Purchase quantity",
            ("order_items", "unit_price"): "Transaction unit price",
            ("order_items", "discount_amount"): "Discount amount",

            ("customers", "customer_id"): "Customer unique ID",
            ("customers", "customer_name"): "Customer name",
            ("customers", "customer_type"): "Customer type (Individual/Enterprise/Distributor)",
            ("customers", "registration_date"): "Registration date",
            ("customers", "vip_level"): "VIP level (1-5)",
            ("customers", "region"): "Customer region",

            ("returns", "return_id"): "Return unique ID",
            ("returns", "order_id"): "Order ID",
            ("returns", "product_id"): "Product ID",
            ("returns", "return_date"): "Return date",
            ("returns", "return_reason"): "Return reason",
            ("returns", "refund_amount"): "Refund amount",
            ("returns", "return_status"): "Return status",
        }
        return descriptions.get((table_name, column_name), f"{column_name} field")

    def get_full_schema(self) -> str:
        schema_text = "Database Schema:\n"
        for table_name, table_info in self.schema_cache.items():
            schema_text += f"\nTable: {table_name}\n"
            schema_text += f"Description: {table_info.description}\n"
            schema_text += "Columns:\n"
            for col in table_info.columns:
                pk_mark = " [PK]" if col.is_primary_key else ""
                fk_mark = f" -> {col.foreign_key}" if col.foreign_key else ""
                schema_text += f"  - {col.name} ({col.type}){pk_mark}{fk_mark}: {col.description}\n"
        return schema_text

    def get_relevant_schema(self, query: str) -> Tuple[str, List[str]]:
        query_lower = query.lower()
        relevant_tables = set()

        for term, tables in self.BUSINESS_TERMS.items():
            if term in query_lower:
                for t in tables:
                    if "." in t:
                        relevant_tables.add(t.split(".")[0])
                    else:
                        relevant_tables.add(t)

        if not relevant_tables:
            relevant_tables = set(self.schema_cache.keys())

        if "orders" in relevant_tables and "order_items" not in relevant_tables:
            if any(kw in query_lower for kw in ["sales", "amount", "quantity", "price", "profit"]):
                relevant_tables.add("order_items")

        if "order_items" in relevant_tables and "products" not in relevant_tables:
            if any(kw in query_lower for kw in ["category", "type", "brand", "cost", "profit", "margin"]):
                relevant_tables.add("products")

        schema_text = "Relevant Table Schema:\n"
        for table_name in sorted(relevant_tables):
            if table_name in self.schema_cache:
                table_info = self.schema_cache[table_name]
                schema_text += f"\nTable: {table_name}\n"
                schema_text += f"Description: {table_info.description}\n"
                schema_text += "Columns:\n"
                for col in table_info.columns:
                    pk_mark = " [PK]" if col.is_primary_key else ""
                    fk_mark = f" -> {col.foreign_key}" if col.foreign_key else ""
                    schema_text += f"  - {col.name} ({col.type}){pk_mark}{fk_mark}: {col.description}\n"

        return schema_text, list(relevant_tables)

    def resolve_time_expression(self, query: str) -> Tuple[str, Dict[str, str]]:
        time_params = {}
        modified_query = query

        for expr, sql_expr in self.TIME_EXPRESSIONS.items():
            if expr in modified_query:
                placeholder = f"__TIME_{len(time_params)}__"
                time_params[placeholder] = sql_expr
                modified_query = modified_query.replace(expr, placeholder)

        return modified_query, time_params

    def get_business_terms_hint(self, query: str) -> str:
        hints = []
        query_lower = query.lower()

        for term, mappings in self.BUSINESS_TERMS.items():
            if term in query_lower:
                for mapping in mappings:
                    if "." in mapping or "(" in mapping:
                        hints.append(f"- '{term}' maps to: {mapping}")

        if hints:
            return "\nBusiness Term Mapping Hints:\n" + "\n".join(hints)
        return ""

    def get_join_hints(self, tables: List[str]) -> str:
        joins = []

        if "orders" in tables and "order_items" in tables:
            joins.append("- orders JOIN order_items ON orders.order_id = order_items.order_id")
        if "order_items" in tables and "products" in tables:
            joins.append("- order_items JOIN products ON order_items.product_id = products.product_id")
        if "orders" in tables and "customers" in tables:
            joins.append("- orders JOIN customers ON orders.customer_id = customers.customer_id")
        if "returns" in tables and "orders" in tables:
            joins.append("- returns JOIN orders ON returns.order_id = orders.order_id")
        if "returns" in tables and "products" in tables:
            joins.append("- returns JOIN products ON returns.product_id = products.product_id")

        if joins:
            return "\nTable Join Hints:\n" + "\n".join(joins)
        return ""
