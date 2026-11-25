import json
import os
import sqlite3

# 绝对路径：避免服务以不同工作目录启动时连到空库；测试可用 SUPPORTPILOT_DB 指向临时库
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("SUPPORTPILOT_DB") or os.path.join(ROOT, "data.db")
DEMO_ORDERS_PATH = os.path.join(ROOT, "data", "demo_orders.json")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _add_columns(conn, table: str, additions: list[tuple[str, str]]) -> None:
    """幂等补列：表不存在（由 init_db 稍后创建）或列已存在时跳过。"""
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if not cols:
        return
    for name, typ in additions:
        if name not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")


def _migrate(conn):
    """对已存在的旧库做幂等加列，补齐订单展示与可观测性埋点字段。"""
    # 订单展示列：旧库曾由导入脚本补齐，新库/CI 直接在这里建全
    _add_columns(conn, "orders", [
        ("product_name", "TEXT"),
        ("quantity", "INTEGER DEFAULT 1"),
        ("unit_price", "REAL"),
        ("currency", "TEXT DEFAULT 'USD'"),
        ("merchant_avatar", "TEXT"),
        ("product_image", "TEXT"),
        ("shipping_fee", "REAL DEFAULT 0"),
        ("order_time", "TEXT"),
    ])
    _add_columns(conn, "conversations", [
        ("retrieved_sources", "TEXT"),
        ("review_passed", "INTEGER"),
        ("review_note", "TEXT"),
        ("buyer_country", "TEXT"),
        ("buyer_state", "TEXT"),
        ("capability", "TEXT"),
    ])
    # agent_turns 与 conversations 的关联列（旧库补列）
    _add_columns(conn, "agent_turns", [("conversation_id", "INTEGER")])
    conn.commit()


def _dedupe_work_orders(conn):
    """合并历史重复工单：同订单同类型只保留最新一条未关闭记录，其余置为 Closed。

    唯一索引建立前必须先跑一次；之后每次启动都是幂等空操作。
    """
    conn.execute("""
        UPDATE work_orders
        SET status = 'Closed'
        WHERE COALESCE(status, 'Open') != 'Closed'
          AND id NOT IN (
              SELECT MAX(id) FROM work_orders
              WHERE COALESCE(status, 'Open') != 'Closed'
              GROUP BY order_id, case_type
          )
    """)


def _ensure_work_order_unique(conn):
    """未关闭工单部分唯一索引：并发审批也不会重复建单。"""
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_work_orders_active
        ON work_orders(order_id, case_type)
        WHERE COALESCE(status, 'Open') != 'Closed'
    """)


def normalize_order_totals(conn):
    """保证订单金额勾稽：订单总额 = 商品单价 × 数量 + 运费。

    只修正在数据迁移/回填中被落下的不一致行（容差 0.01），幂等。
    订单表若尚未补齐 quantity/unit_price 等列则跳过。
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(orders)").fetchall()}
    if not {"quantity", "unit_price", "shipping_fee", "total_amount"} <= cols:
        return
    conn.execute("""
        UPDATE orders
        SET total_amount = ROUND(quantity * unit_price + COALESCE(shipping_fee, 0), 2)
        WHERE quantity IS NOT NULL
          AND unit_price IS NOT NULL
          AND ABS(COALESCE(total_amount, 0)
                  - (quantity * unit_price + COALESCE(shipping_fee, 0))) > 0.01
    """)


def seed_demo_orders() -> int:
    """空库首次启动时灌入演示订单，保证公网部署开箱可演示；已有数据时不做修改。"""
    conn = get_connection()
    try:
        if conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]:
            return 0
        with open(DEMO_ORDERS_PATH, encoding="utf-8") as f:
            rows = json.load(f)
        for row in rows:
            cols = list(row)
            conn.execute(
                f"INSERT OR REPLACE INTO orders ({','.join(cols)}) "
                f"VALUES ({','.join('?' for _ in cols)})",
                [row[col] for col in cols],
            )
        normalize_order_totals(conn)
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def init_db():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT UNIQUE,
            seller_name TEXT,
            buyer_name TEXT,
            buyer_phone TEXT,
            buyer_email TEXT,
            tracking_number TEXT,
            total_amount REAL,
            shipping_address TEXT,
            origin_address TEXT,
            shipping_status TEXT,
            logistics_info TEXT,
            status TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT,
            user_message TEXT,
            agent_response TEXT,
            retrieved_sources TEXT,
            review_passed INTEGER,
            review_note TEXT,
            buyer_country TEXT,
            buyer_state TEXT,
            capability TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    _migrate(conn)
    normalize_order_totals(conn)
    # 每轮 Agent 的节点级指标落库，供运营/排障查询（此前只打在 JSON 日志里，不可查）
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            thread_id TEXT,
            order_id TEXT,
            intent TEXT,
            total_ms REAL,
            llm_prompt_tokens INTEGER,
            llm_completion_tokens INTEGER,
            llm_total_tokens INTEGER,
            llm_calls INTEGER,
            summary_triggered INTEGER,
            review_mode TEXT,
            review_passed INTEGER,
            error_count INTEGER,
            capability TEXT,
            nodes_json TEXT,
            errors_json TEXT,
            conversation_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 统一观测视图：一轮 Agent 指标 + 对应的 API 会话记录
    conn.execute("""
        CREATE VIEW IF NOT EXISTS agent_turn_conversations AS
        SELECT t.id AS turn_id,
               t.created_at,
               t.user_id,
               t.thread_id,
               t.order_id,
               t.intent,
               t.total_ms,
               t.llm_total_tokens,
               t.llm_calls,
               t.summary_triggered,
               t.review_mode,
               t.review_passed AS turn_review_passed,
               t.error_count,
               t.capability AS turn_capability,
               c.id AS conversation_id,
               c.user_message,
               c.agent_response,
               c.retrieved_sources,
               c.capability AS conversation_capability
        FROM agent_turns t
        LEFT JOIN conversations c ON c.id = t.conversation_id
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS work_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT,
            priority TEXT,
            case_type TEXT,
            assignee TEXT,
            status TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    _dedupe_work_orders(conn)
    _ensure_work_order_unique(conn)
    conn.commit()
    conn.close()