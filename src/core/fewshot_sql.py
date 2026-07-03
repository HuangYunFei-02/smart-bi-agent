"""
Few-shot SQL Example Library + Text2SQL Generator
Core features:
1. Maintain historical query-SQL pairs as few-shot examples
2. Dynamic example retrieval based on embedding similarity
3. SQL generation + Self-Correction mechanism
"""
import sqlite3
import json
from typing import List, Dict
from dataclasses import dataclass
import numpy as np

# sentence-transformers disabled to avoid HuggingFace download
USE_ST = False
EMBEDDING_MODEL = None

@dataclass
class SQLExample:
    id: str
    question: str
    sql: str
    description: str = ""
    tables_used: List[str] = None
    difficulty: str = "medium"

    def __post_init__(self):
        if self.tables_used is None:
            self.tables_used = []

class FewShotSQLLibrary:
    def __init__(self, db_path: str = None):
        self.examples: List[SQLExample] = []
        self.embeddings: Dict[str, np.ndarray] = {}
        self.db_path = db_path
        self._init_examples()

    def _init_examples(self):
        examples_data = [
            ("ex_001", "What was last month total sales",
             """SELECT SUM(oi.quantity * oi.unit_price - oi.discount_amount) as total_sales
FROM orders o
JOIN order_items oi ON o.order_id = oi.order_id
WHERE o.order_date >= date('now', 'start of month', '-1 month')
  AND o.order_date < date('now', 'start of month')
  AND o.order_status = 'Completed'""",
             "Cross-table JOIN + time range + aggregation", ["orders", "order_items"], "easy"),

            ("ex_002", "East region category sales ranking",
             """SELECT p.category,
    SUM(oi.quantity * oi.unit_price - oi.discount_amount) as sales_amount,
    RANK() OVER (ORDER BY SUM(oi.quantity * oi.unit_price - oi.discount_amount) DESC) as rank
FROM orders o
JOIN order_items oi ON o.order_id = oi.order_id
JOIN products p ON oi.product_id = p.product_id
WHERE o.region = 'East' AND o.order_status = 'Completed'
GROUP BY p.category
ORDER BY sales_amount DESC""",
             "Multi-table JOIN + grouping + window function ranking", ["orders", "order_items", "products"], "medium"),

            ("ex_003", "Quarterly sales year-over-year growth rate",
             """WITH quarterly_sales AS (
    SELECT strftime('%Y-Q' || ((strftime('%m', order_date) - 1) / 3 + 1), order_date) as quarter,
        SUM(oi.quantity * oi.unit_price - oi.discount_amount) as sales
    FROM orders o
    JOIN order_items oi ON o.order_id = oi.order_id
    WHERE order_date >= date('now', 'start of year', '-1 year') AND order_status = 'Completed'
    GROUP BY quarter)
SELECT q1.quarter, q1.sales as current_sales, q2.sales as last_year_sales,
    ROUND((q1.sales - q2.sales) * 100.0 / NULLIF(q2.sales, 0), 2) as yoy_growth_rate
FROM quarterly_sales q1
LEFT JOIN quarterly_sales q2 ON q2.quarter = strftime('%Y', date(q1.quarter || '-01', '-1 year')) || '-Q' || substr(q1.quarter, -1)
WHERE q1.quarter >= strftime('%Y', 'now') || '-Q1'
ORDER BY q1.quarter""",
             "CTE + YoY calculation + self-join", ["orders", "order_items"], "hard"),

            ("ex_004", "Top 5 products with highest return rate",
             """SELECT p.product_name, p.brand,
    COUNT(DISTINCT r.order_id) as return_orders,
    COUNT(DISTINCT o.order_id) as total_orders,
    ROUND(COUNT(DISTINCT r.order_id) * 100.0 / NULLIF(COUNT(DISTINCT o.order_id), 0), 2) as return_rate
FROM products p
LEFT JOIN order_items oi ON p.product_id = oi.product_id
LEFT JOIN orders o ON oi.order_id = o.order_id AND o.order_status = 'Completed'
LEFT JOIN returns r ON o.order_id = r.order_id AND p.product_id = r.product_id
GROUP BY p.product_id, p.product_name, p.brand
HAVING COUNT(DISTINCT o.order_id) > 10
ORDER BY return_rate DESC
LIMIT 5""",
             "Return rate calculation + multi-table join + HAVING filter", ["products", "order_items", "orders", "returns"], "hard"),

            ("ex_005", "VIP level 4+ customer spending this month",
             """SELECT c.customer_name, c.vip_level,
    SUM(oi.quantity * oi.unit_price - oi.discount_amount) as total_spent
FROM customers c
JOIN orders o ON c.customer_id = o.customer_id
JOIN order_items oi ON o.order_id = oi.order_id
WHERE c.vip_level >= 4 AND o.order_date >= date('now', 'start of month') AND o.order_status = 'Completed'
GROUP BY c.customer_id, c.customer_name, c.vip_level
ORDER BY total_spent DESC""",
             "Conditional filter + multi-table JOIN + grouping", ["customers", "orders", "order_items"], "medium"),

            ("ex_006", "Sales proportion by channel",
             """WITH channel_sales AS (
    SELECT channel, SUM(oi.quantity * oi.unit_price - oi.discount_amount) as sales
    FROM orders o JOIN order_items oi ON o.order_id = oi.order_id
    WHERE o.order_status = 'Completed' GROUP BY channel)
SELECT channel, sales, ROUND(sales * 100.0 / SUM(sales) OVER(), 2) as percentage
FROM channel_sales ORDER BY sales DESC""",
             "Channel analysis + CTE + window function percentage", ["orders", "order_items"], "medium"),

            ("ex_007", "Which brand has highest average order value in digital electronics",
             """SELECT p.brand,
    AVG(oi.quantity * oi.unit_price - oi.discount_amount) as avg_order_value,
    COUNT(DISTINCT o.order_id) as order_count
FROM products p
JOIN order_items oi ON p.product_id = oi.product_id
JOIN orders o ON oi.order_id = o.order_id
WHERE p.category = 'Digital Electronics' AND o.order_status = 'Completed'
GROUP BY p.brand
HAVING COUNT(DISTINCT o.order_id) >= 5
ORDER BY avg_order_value DESC
LIMIT 1""",
             "Category filter + brand grouping + AOV calculation", ["products", "order_items", "orders"], "medium"),

            ("ex_008", "Daily sales trend for last 30 days",
             """SELECT o.order_date,
    COUNT(DISTINCT o.order_id) as order_count,
    SUM(oi.quantity * oi.unit_price - oi.discount_amount) as daily_sales,
    SUM(oi.quantity) as total_quantity
FROM orders o JOIN order_items oi ON o.order_id = oi.order_id
WHERE o.order_date >= date('now', '-30 days') AND o.order_status = 'Completed'
GROUP BY o.order_date ORDER BY o.order_date""",
             "Time series + daily aggregation", ["orders", "order_items"], "easy"),

            ("ex_009", "Average order amount enterprise vs individual customers",
             """SELECT c.customer_type, AVG(order_total) as avg_order_amount, COUNT(*) as order_count
FROM (
    SELECT o.order_id, o.customer_id, SUM(oi.quantity * oi.unit_price - oi.discount_amount) as order_total
    FROM orders o JOIN order_items oi ON o.order_id = oi.order_id
    WHERE o.order_status = 'Completed' GROUP BY o.order_id, o.customer_id
) order_totals
JOIN customers c ON order_totals.customer_id = c.customer_id
WHERE c.customer_type IN ('Enterprise', 'Individual')
GROUP BY c.customer_type""",
             "Subquery order amount + customer type comparison", ["orders", "order_items", "customers"], "hard"),

            ("ex_010", "How much did this month sales grow compared to last month",
             """WITH monthly_comparison AS (
    SELECT CASE WHEN order_date >= date('now', 'start of month') THEN 'This Month' ELSE 'Last Month' END as period,
        SUM(oi.quantity * oi.unit_price - oi.discount_amount) as sales
    FROM orders o JOIN order_items oi ON o.order_id = oi.order_id
    WHERE order_date >= date('now', 'start of month', '-1 month')
      AND order_date < date('now', 'start of month', '+1 month')
      AND order_status = 'Completed'
    GROUP BY period)
SELECT MAX(CASE WHEN period = 'This Month' THEN sales END) as this_month,
    MAX(CASE WHEN period = 'Last Month' THEN sales END) as last_month,
    MAX(CASE WHEN period = 'This Month' THEN sales END) - MAX(CASE WHEN period = 'Last Month' THEN sales END) as growth_amount,
    ROUND((MAX(CASE WHEN period = 'This Month' THEN sales END) - MAX(CASE WHEN period = 'Last Month' THEN sales END)) * 100.0 / 
          NULLIF(MAX(CASE WHEN period = 'Last Month' THEN sales END), 0), 2) as growth_rate
FROM monthly_comparison""",
             "MoM calculation + CASE WHEN conditional aggregation", ["orders", "order_items"], "hard"),
        ]

        for data in examples_data:
            ex = SQLExample(id=data[0], question=data[1], sql=data[2], 
                          description=data[3], tables_used=data[4], difficulty=data[5])
            self.add_example(ex)

    def _compute_embedding(self, text: str) -> np.ndarray:
        if USE_ST:
            return EMBEDDING_MODEL.encode(text)
        else:
            words = set(text.lower().split())
            vocab = list(words)
            return np.array([1.0 if w in words else 0.0 for w in vocab])

    def add_example(self, example: SQLExample):
        self.examples.append(example)
        embedding_text = f"{example.question} {example.description}"
        self.embeddings[example.id] = self._compute_embedding(embedding_text)

    def retrieve_similar(self, query: str, k: int = 3) -> List[SQLExample]:
        if not self.examples:
            return []
        query_embedding = self._compute_embedding(query)
        similarities = []
        for ex in self.examples:
            ex_embedding = self.embeddings[ex.id]
            if len(ex_embedding) != len(query_embedding):
                max_len = max(len(ex_embedding), len(query_embedding))
                ex_embedding = np.pad(ex_embedding, (0, max_len - len(ex_embedding)))
                query_embedding = np.pad(query_embedding, (0, max_len - len(query_embedding)))
            similarity = np.dot(ex_embedding, query_embedding) / (
                np.linalg.norm(ex_embedding) * np.linalg.norm(query_embedding) + 1e-8
            )
            similarities.append((similarity, ex))
        similarities.sort(key=lambda x: x[0], reverse=True)
        return [ex for _, ex in similarities[:k]]

    def get_examples_by_tables(self, tables: List[str]) -> List[SQLExample]:
        table_set = set(tables)
        return [ex for ex in self.examples if table_set & set(ex.tables_used)]

    def format_few_shot_prompt(self, examples: List[SQLExample]) -> str:
        prompt_parts = []
        for i, ex in enumerate(examples, 1):
            prompt_parts.append(f"### Example {i}")
            prompt_parts.append(f"Question: {ex.question}")
            prompt_parts.append(f"SQL:\n{ex.sql}")
            prompt_parts.append("")
        return "\n".join(prompt_parts)

    def save_to_db(self):
        if not self.db_path:
            return
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sql_examples (
                id TEXT PRIMARY KEY, question TEXT NOT NULL, sql TEXT NOT NULL,
                description TEXT, tables_used TEXT, difficulty TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
        """)
        for ex in self.examples:
            cursor.execute("""
                INSERT OR REPLACE INTO sql_examples (id, question, sql, description, tables_used, difficulty)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (ex.id, ex.question, ex.sql, ex.description, json.dumps(ex.tables_used), ex.difficulty))
        conn.commit()
        conn.close()

    def load_from_db(self):
        if not self.db_path:
            return
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sql_examples")
            rows = cursor.fetchall()
            self.examples = []
            self.embeddings = {}
            for row in rows:
                ex = SQLExample(id=row[0], question=row[1], sql=row[2], description=row[3],
                              tables_used=json.loads(row[4]) if row[4] else [], difficulty=row[5])
                self.add_example(ex)
            conn.close()
        except Exception as e:
            print(f"[WARN] Failed to load examples: {e}")
