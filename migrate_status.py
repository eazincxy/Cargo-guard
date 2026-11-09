"""
订单状态迁移：统一 status 字段为九个枚举值之一，并回填现有 6 条订单。
九种状态：正在运输中、未发货、已发货、申请退款中、申请退货中、已退款、已退货、待签收、已签收
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.db import get_connection, init_db

VALID_STATUSES = ["正在运输中", "未发货", "已发货", "申请退款中", "申请退货中", "已退款", "已退货", "待签收", "已签收"]

# 现有订单按数据合理回填（文档三条已重编为 ORD-1001~1003）
BACKFILL = {
    "ORD-1001": "未发货",       # 文档无物流信息
    "ORD-1002": "未发货",       # 文档无物流信息
    "ORD-1003": "未发货",       # 文档无物流信息
    "ORD-1004": "正在运输中",   # In transit, 有物流单号
    "ORD-1005": "正在运输中",   # Customs clearance, 有物流单号
    "ORD-1006": "已签收",       # Delivered, 有物流单号
}

def main():
    init_db()
    conn = get_connection()
    updated = 0
    for oid, st in BACKFILL.items():
        conn.execute("UPDATE orders SET status=? WHERE order_id=?", (st, oid))
        updated += conn.total_changes
    # 防御：把任何不在九种枚举内的状态置为 未发货
    conn.execute(
        "UPDATE orders SET status='未发货' WHERE status NOT IN ({})".format(
            ",".join("?" * len(VALID_STATUSES))
        ),
        VALID_STATUSES,
    )
    conn.commit()
    print(f"已回填/规范化 {updated} 条订单状态")
    print()
    for r in conn.execute("SELECT order_id, seller_name, product_name, tracking_number, shipping_status, status FROM orders ORDER BY order_id"):
        print(f"  {r['order_id']} | {r['seller_name']} | {r['product_name']} | tracking={r['tracking_number']} | shipping={r['shipping_status']} | status={r['status']}")
    conn.close()

if __name__ == "__main__":
    main()
