import re

def extract_order_id(text):
    match = re.search(r"ORD-\d{3,}", text, flags=re.I)
    if match:
        return match.group(0).upper()
    match = re.search(r"\b\d{4,}\b", text)
    if match:
        return "ORD-" + match.group(0)
    return "ORD-1001"

def detect_intent(text):
    s = text.lower()
    if any(k in s for k in ["refund", "退款", "退货", "退貨", "返现", "退钱"]):
        return "refund"
    if any(k in s for k in ["replace", "replacement", "换货", "更换", "换新", "替换"]):
        return "replacement"
    if any(k in s for k in ["track", "tracking", "物流", "where is", "在哪", "delivery", "shipping"]):
        return "tracking"
    if any(k in s for k in ["invoice", "发票", "receipt", "账单"]):
        return "invoice"
    if any(k in s for k in ["cancel", "取消", "撤销"]):
        return "cancel"
    return "general"

def build_reply(user_text, order_info):
    order_id = extract_order_id(user_text)
    intent = detect_intent(user_text)

    if intent == "refund":
        return f"We have received your refund request for {order_id}. We are checking the order details and will process the request soon."
    if intent == "replacement":
        return f"We have received your replacement request for {order_id}. If there is a product issue or packaging problem, we can help arrange a replacement."
    if intent == "tracking":
        status = order_info.get("shipping_status", "In transit")
        logistics = order_info.get("logistics_info", "Processing")
        return f"Your order {order_id} is currently in status: {status}. Logistics info: {logistics}."
    if intent == "invoice":
        return f"We can help provide the invoice for {order_id}. Please confirm if you need an electronic invoice."
    if intent == "cancel":
        return f"We have logged your cancellation request for {order_id}. If the order has not shipped yet, we can still process the cancellation."
    return f"We have received your message regarding {order_id}. We are reviewing the order details and will provide support shortly."