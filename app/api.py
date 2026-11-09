from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from app.db import get_connection
from app.agent import build_reply

app = FastAPI(title="CargoGuard API")

class ChatRequest(BaseModel):
    order_id: str
    message: str

@app.get("/orders")
def get_orders():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM orders ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/orders/{order_id}")
def get_order(order_id: str):
    conn = get_connection()
    row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")
    return dict(row)

@app.post("/chat")
def chat(req: ChatRequest):
    order = get_order(req.order_id)
    reply = build_reply(req.message, order)

    conn = get_connection()
    conn.execute("""
        INSERT INTO conversations (order_id, user_message, agent_response)
        VALUES (?, ?, ?)
    """, (req.order_id, req.message, reply))
    conn.commit()
    conn.close()

    return {
        "order_id": req.order_id,
        "reply": reply,
        "intent": "general",
        "status": "processed"
    }

@app.get("/work-orders")
def get_work_orders():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM work_orders ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/work-orders")
def create_work_order(order_id: str, priority: str = "Medium", case_type: str = "General", assignee: str = "Support AI"):
    conn = get_connection()
    conn.execute("""
        INSERT INTO work_orders (order_id, priority, case_type, assignee, status)
        VALUES (?, ?, ?, ?, ?)
    """, (order_id, priority, case_type, assignee, "Open"))
    conn.commit()
    conn.close()
    return {"status": "created"}