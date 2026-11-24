"""把 tests/fixtures/orders.json 灌入 data.db，供 CI 回归使用。

data.db 被 .gitignore 排除，干净环境需要先执行本脚本，Agent 才能读到订单事实。
幂等：按 order_id 覆盖写入。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.db import get_connection, init_db, normalize_order_totals  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "orders.json")


def main() -> None:
    init_db()
    rows = json.loads(Path(FIXTURE).read_text(encoding="utf-8"))
    conn = get_connection()
    try:
        for row in rows:
            cols = list(row)
            conn.execute(
                f"INSERT OR REPLACE INTO orders ({','.join(cols)}) "
                f"VALUES ({','.join('?' for _ in cols)})",
                [row[c] for c in cols],
            )
        normalize_order_totals(conn)
        conn.commit()
    finally:
        conn.close()
    print(f"seeded {len(rows)} orders from {FIXTURE}")


if __name__ == "__main__":
    main()
