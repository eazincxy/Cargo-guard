from app.data import orders, return_policies

currency_rates = {
    "USD": 1.0,
    "EUR": 0.92,
    "GBP": 0.78,
    "CNY": 7.15,
    "RMB": 7.15,
    "JPY": 157.0,
    "KRW": 1385.0,
    "THB": 35.5,
    "AED": 3.67,
}

shipping_fee_policy = {
    "US": {
        "standard": 7.99,
        "express": 14.99,
    },
    "DE": {
        "standard": 8.50,
        "express": 16.00,
    },
    "UK": {
        "standard": 9.50,
        "express": 17.50,
    },
    "CN": {
        "standard": 5.50,
        "express": 10.00,
    }
}

LANGUAGE_OPTIONS = {
    "en": "English",
    "zh": "中文",
    "ja": "日本語",
    "ko": "한국어",
    "th": "ไทย",
    "es": "Español",
    "fr": "Français",
    "de": "Deutsch",
}

def get_order(order_id: str):
    return orders.get(order_id)

def get_return_policy(product_category: str):
    return return_policies.get(product_category)

def get_tracking_status(tracking_number: str):
    info_map = {
        "TRK987654": {"status": "In transit", "last_update": "3 days ago"},
        "TRK123456": {"status": "Delivered", "last_update": "2 days ago"},
        "TRK555111": {"status": "Delivered", "last_update": "1 day ago"},
    }
    return info_map.get(tracking_number, {"status": "Unknown", "last_update": "No update"})

def create_ticket(order_id: str, ticket_type: str, reason: str):
    return {
        "ticket_id": "TKT-001",
        "order_id": order_id,
        "type": ticket_type,
        "reason": reason,
        "status": "created"
    }

def search_orders(query: str):
    if not query:
        return []

    q = query.strip().upper()
    results = []

    if q.startswith("ORD-"):
        order = orders.get(q)
        if order:
            return [order]

    import re
    m = re.fullmatch(r"\d{3,6}", q)
    if m:
        candidate_id = f"ORD-{q}"
        order = orders.get(candidate_id)
        if order:
            return [order]

    for oid, order in orders.items():
        if q in oid.upper():
            results.append(order)
            continue
        if q in order.get("customer_name", "").upper():
            results.append(order)
            continue
        if q in order.get("product", "").upper():
            results.append(order)
            continue
        if q in str(order.get("tracking_number", "")).upper():
            results.append(order)
            continue

    unique = {o["order_id"]: o for o in results}
    return list(unique.values())

def get_exchange_rate(from_currency: str, to_currency: str) -> float:
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()

    if from_currency == to_currency:
        return 1.0

    if from_currency not in currency_rates:
        raise ValueError(f"Unsupported currency: {from_currency}")
    if to_currency not in currency_rates:
        raise ValueError(f"Unsupported currency: {to_currency}")

    rate = (currency_rates[to_currency] / currency_rates[from_currency])
    return round(rate, 6)

def convert_amount(amount: float, from_currency: str, to_currency: str) -> float:
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()

    if from_currency == to_currency:
        return round(amount, 2)

    rate = get_exchange_rate(from_currency, to_currency)
    converted = amount * rate
    return round(converted, 2)

def estimate_shipping_fee(country: str, shipping_type: str = "standard"):
    country = country.upper()
    shipping_type = shipping_type.lower()

    fees = shipping_fee_policy.get(country)
    if not fees:
        return 0.0

    fee = fees.get(shipping_type, fees["standard"])
    return float(fee)

def compute_refund_amount(order: dict, shipping_type: str = "standard", include_shipping: bool = False):
    currency = order.get("currency", "USD")
    base_amount = float(order.get("price", 0))
    shipping_fee = estimate_shipping_fee(order.get("country", "US"), shipping_type)

    if include_shipping:
        refund_amount = base_amount + shipping_fee
    else:
        refund_amount = base_amount

    return {
        "currency": currency,
        "item_amount": round(base_amount, 2),
        "shipping_fee": round(shipping_fee, 2),
        "refund_amount": round(refund_amount, 2),
    }

def format_money(value: float, currency: str) -> str:
    return f"{value:.2f} {currency.upper()}"