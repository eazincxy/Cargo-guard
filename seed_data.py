from app.db import get_connection

orders = [
    {
        "order_id": "ORD-1004",
        "seller_name": "Northwind Store",
        "buyer_name": "Alice Johnson",
        "buyer_phone": "+1 415-555-0198",
        "buyer_email": "alice.johnson@example.com",
        "tracking_number": "TRK123456",
        "total_amount": 89.99,
        "origin_address": "Los Angeles, CA, USA",
        "shipping_address": "广州市天河区珠江新城, 中国",
        "shipping_status": "In transit",
        "logistics_info": "International logistics center -> local warehouse -> final delivery",
        "status": "正在运输中",
    },
    {
        "order_id": "ORD-1005",
        "seller_name": "Ocean Commerce",
        "buyer_name": "Bob Smith",
        "buyer_phone": "+44 7700 900123",
        "buyer_email": "bob.smith@example.co.uk",
        "tracking_number": "TRK234567",
        "total_amount": 134.50,
        "origin_address": "London, UK",
        "shipping_address": "深圳市福田区, 中国",
        "shipping_status": "Customs clearance",
        "logistics_info": "Export warehouse -> customs -> destination hub -> local courier",
        "status": "正在运输中",
    },
    {
        "order_id": "ORD-1006",
        "seller_name": "Sunrise Goods",
        "buyer_name": "Charlie Lee",
        "buyer_phone": "+81 90-1234-5678",
        "buyer_email": "charlie.lee@example.jp",
        "tracking_number": "TRK345678",
        "total_amount": 56.20,
        "origin_address": "Tokyo, Japan",
        "shipping_address": "成都市锦江区春熙路, 中国",
        "shipping_status": "Delivered",
        "logistics_info": "Factory -> air freight -> city distribution center -> doorstep delivery",
        "status": "已签收",
    }
]

conn = get_connection()
for order in orders:
    conn.execute("""
        INSERT OR IGNORE INTO orders (
            order_id, seller_name, buyer_name, buyer_phone, buyer_email,
            tracking_number, total_amount, origin_address, shipping_address,
            shipping_status, logistics_info, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        order["order_id"],
        order.get("seller_name"),
        order["buyer_name"],
        order["buyer_phone"],
        order["buyer_email"],
        order["tracking_number"],
        order["total_amount"],
        order.get("origin_address"),
        order["shipping_address"],
        order["shipping_status"],
        order["logistics_info"],
        order["status"]
    ))
conn.commit()
conn.close()
print("Seeded successfully")