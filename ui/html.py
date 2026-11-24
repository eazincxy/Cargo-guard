"""HTML 片段组装：把订单/商品数据渲染成自定义组件所需的 HTML 与 payload。

只做数据与标记拼装，不直接渲染 Streamlit 控件；界面语言取自 session_state。
"""

import html
import random
from datetime import datetime, timedelta

import streamlit as st

from ui.catalog import (
    DELISTED_ORDERS, MERCHANT_PROFILES, ORDER_SERVICES, ORDER_UX, PRODUCT_META,
    REVIEW_ORIG_LANGS, TIMELINE_OFFSETS, TIMELINE_PATHS, _PAY_BY_CURRENCY, _ml,
)
from ui.copy import (
    LOGISTICS_LABELS, MONTHS_ABBR, SHIPPING_LABELS, STATUS_BADGE_STYLE,
    STATUS_LABELS, T,
)


def is_delisted(order):
    return (order or {}).get("order_id") in DELISTED_ORDERS


def ux(key):
    return ORDER_UX.get(st.session_state.lang, ORDER_UX["en"])[key]


def product_meta(order):
    meta = PRODUCT_META.get(order.get("order_id"), {"cat": "generic", "spec": {}})
    spec = (meta.get("spec") or {}).get(st.session_state.lang) or meta.get("spec", {}).get("en") or ""
    return meta, spec


def order_services(order):
    return ORDER_SERVICES.get(order.get("order_id"), {"free_ship": False, "tax_in": False, "seven_day": False})


def product_risk_items(order, count=3):
    """每个订单稳定抽取若干条风险提示，模拟商家自行设置。"""
    risks = ux("risks")
    seed = sum(ord(c) for c in order.get("order_id", "")) + len(order.get("product_name", ""))
    idxs = random.Random(seed).sample(range(len(risks)), min(count, len(risks)))
    return [risks[i] for i in sorted(idxs)]


def _pick(value, lang):
    return value.get(lang, value.get("en", "")) if isinstance(value, dict) else value


def review_origin(author: str) -> str:
    """按作者名确定性分配原文语言，保证同一评论每次显示一致。"""
    return REVIEW_ORIG_LANGS[sum(ord(ch) for ch in str(author)) % len(REVIEW_ORIG_LANGS)]


def merchant_profile(name):
    """返回商家档案；订单表里没有档案的商家用通用档案兜底。"""
    if name in MERCHANT_PROFILES:
        return MERCHANT_PROFILES[name]
    return {
        "intro": _ml("独立跨境卖家，全球发货，通常两个工作日内发出。",
                     "Independent cross-border seller. Ships worldwide and usually dispatches within two business days.",
                     "独立系の越境セラー。世界中に発送し、通常2営業日以内に出荷します。",
                     "독립 크로스보더 판매자. 전 세계로 배송하며 보통 영업일 2일 이내에 발송합니다.",
                     "Vendeur transfrontalier indépendant. Expédition mondiale, généralement sous deux jours ouvrés."),
        "tags": [_ml("跨境", "Cross-border", "越境", "크로스보더", "Transfrontalier"),
                 _ml("综合", "General", "総合", "종합", "Général")],
        "rating": 4.2, "sold": 860,
        "products": [
            {"name": _ml("主打商品", "Featured Item", "注目商品", "주력 상품", "Article vedette"), "price": "USD 45.00", "sold": 320},
            {"name": _ml("日常好物", "Everyday Essential", "日用定番", "데일리 필수품", "Essentiel quotidien"), "price": "USD 22.00", "sold": 510},
            {"name": _ml("礼品套装", "Gift Bundle", "ギフトセット", "선물 세트", "Coffret cadeau"), "price": "USD 68.00", "sold": 180},
        ],
        "reviews": [
            {"author": "Ava R.", "rating": 5, "days": 5,
             "text": _ml("商品与描述一致，包装很仔细。",
                         "Item matched the description and arrived well packed.",
                         "説明通りの商品が丁寧に梱包されて届きました。",
                         "설명과 동일한 상품이 꼼꼼히 포장되어 도착했어요.",
                         "Article conforme à la description, bien emballé.")},
            {"author": "Leo M.", "rating": 4, "days": 15,
             "text": _ml("性价比不错，运输花了大约两周。",
                         "Good quality for the price, shipping took about two weeks.",
                         "価格の割に品質は良好。配送に約2週間かかりました。",
                         "가격 대비 품질이 좋고 배송은 약 2주 걸렸습니다.",
                         "Bonne qualité pour le prix, livraison en deux semaines environ.")},
            {"author": "Nina K.", "rating": 3, "days": 26,
             "text": _ml("沟通回复较慢，但最终解决了问题。",
                         "Communication was slow, but the seller resolved it in the end.",
                         "連絡は遅めでしたが、最終的には解決しました。",
                         "답변이 느렸지만 결국 해결해 줬습니다.",
                         "Communication lente, mais problème résolu au final.")},
        ],
    }


def fmt_datetime(value, lang):
    """按界面语言格式化时间：英文/法文用月份缩写，中日韩用年月日。"""
    if not value:
        return ""
    if isinstance(value, str):
        txt = value.replace("T", " ")[:16]
        try:
            dt = datetime.strptime(txt, "%Y-%m-%d %H:%M")
        except ValueError:
            try:
                dt = datetime.strptime(txt, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return txt
    else:
        dt = value
    if lang in ("zh", "ja"):
        return f"{dt.year}年{dt.month}月{dt.day}日 {dt.hour:02d}:{dt.minute:02d}"
    if lang == "ko":
        return f"{dt.year}년 {dt.month}월 {dt.day}일 {dt.hour:02d}:{dt.minute:02d}"
    mon = MONTHS_ABBR[lang][dt.month - 1]
    if lang == "fr":
        return f"{dt.day} {mon} {dt.year} {dt.hour:02d}:{dt.minute:02d}"
    return f"{mon} {dt.day}, {dt.year} {dt.hour:02d}:{dt.minute:02d}"


def build_timeline(order_time, status):
    """由下单时间 + 状态倒推生成流转时间线（确定性，不随 rerun 变化）。"""
    if not order_time:
        return []
    base = datetime.strptime(str(order_time).replace("T", " ")[:16], "%Y-%m-%d %H:%M")
    keys = TIMELINE_PATHS.get(status, ["created", status])
    return [(k, base + timedelta(hours=TIMELINE_OFFSETS[k])) for k in keys]


def localize_status(status, lang):
    return STATUS_LABELS.get(lang, {}).get(status, status)


def localize_shipping(value, lang):
    if not value:
        return ""
    return SHIPPING_LABELS.get(lang, {}).get(value, value)


def localize_logistics(value, lang):
    if not value:
        return ""
    return LOGISTICS_LABELS.get(lang, {}).get(value, value)


def _merchant_avatar_html(order, size=34):
    if order.get("merchant_avatar") and order["merchant_avatar"].startswith("data:"):
        return f'<img src="{order["merchant_avatar"]}" style="width:{size}px;height:{size}px;border-radius:50%;object-fit:cover;" />'
    letter = (order.get("merchant") or "?")[0].upper()
    return (
        f'<div style="width:{size}px;height:{size}px;border-radius:50%;'
        f'background:linear-gradient(135deg,#f3f4f6,#e5e7eb);display:flex;align-items:center;'
        f'justify-content:center;font-weight:700;color:#4b5563;">{letter}</div>'
    )


def _identity_row(name, avatar_html):
    """返回键右侧的「头像 + 店铺名」一行。"""
    return (
        "<div style='margin:-34px 0 6px 44px;display:flex;align-items:center;gap:9px;'>"
        + avatar_html
        + "<span style='font-size:1.06rem;font-weight:700;color:#111111;"
        "letter-spacing:.2px;'>" + html.escape(name) + "</span></div>"
    )


def _product_thumb_html(order, size=72, radius=12):
    if order.get("product_image") and order["product_image"].startswith("data:"):
        return f'<img src="{order["product_image"]}" style="width:{size}px;height:{size}px;border-radius:{radius}px;object-fit:cover;" />'
    letter = (order.get("product_name") or "?")[0].upper()
    return (
        f'<div style="width:{size}px;height:{size}px;border-radius:{radius}px;'
        f'background:linear-gradient(135deg,#f3f4f6,#e5e7eb);display:flex;align-items:center;'
        f'justify-content:center;font-weight:800;color:#6b7280;font-size:{int(size * 0.3)}px;">{letter}</div>'
    )


def _status_badge_html(order, lang_code):
    status = order.get("status", "未发货")
    fg, bg = STATUS_BADGE_STYLE.get(status, ("#000000", "#f3f4f6"))
    label = localize_status(status, lang_code)
    return (
        f'<span style="display:inline-block;font-size:0.72rem;font-weight:700;'
        f'color:{fg};background:{bg};border-radius:999px;padding:3px 10px;">{label}</span>',
        fg,
    )


def order_card_html(order):
    lang_pack = T[st.session_state.lang]
    lang_code = st.session_state.lang
    merchant_name = html.escape(order.get("merchant") or "")
    product_name = html.escape(order.get("product_name") or "")
    badge_html, fg = _status_badge_html(order, lang_code)
    timeline = build_timeline(order.get("order_time"), order.get("status", "未发货"))
    if timeline:
        nodes = []
        for i, (key, node_time) in enumerate(timeline):
            node_label = lang_pack["node_created"] if key == "created" else localize_status(key, lang_code)
            is_last = i == len(timeline) - 1
            nodes.append(
                '<div style="margin-bottom:10px;">'
                f'<div style="font-size:0.72rem;color:#000000;">{fmt_datetime(node_time, lang_code)}</div>'
                f'<div style="font-size:0.85rem;font-weight:{700 if is_last else 600};'
                f'color:{fg if is_last else "#111827"};">{node_label}</div>'
                '</div>'
            )
        timeline_html = (
            '<details style="margin-top:12px;">'
            '<summary style="list-style:none;cursor:pointer;display:flex;'
            'justify-content:flex-end;align-items:center;gap:6px;">'
            f'{badge_html}</summary>'
            '<div style="margin-top:10px;border-left:2px solid #e5e7eb;padding-left:12px;">'
            f'<div style="font-size:0.7rem;color:#000000;margin-bottom:8px;">{lang_pack["timeline_title"]}</div>'
            + "".join(nodes) + '</div></details>'
        )
    else:
        timeline_html = f'<div style="margin-top:12px;text-align:right;">{badge_html}</div>'

    order_time_text = fmt_datetime(order.get("order_time"), lang_code)
    card = f"""
            <div id="order-card-{order['order_id']}" style="background:white;border:1px solid #e5e7eb;border-radius:18px;padding:16px;box-shadow:0 8px 18px rgba(15,23,42,0.03);flex-shrink:0;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                    <span style="font-size:0.72rem;color:#000000;text-transform:uppercase;letter-spacing:0.08em;">{lang_pack['order_id']}</span>
                    <strong>{order['order_id']}</strong>
                </div>
                <div style="display:flex;justify-content:space-between;font-size:0.78rem;color:#000000;margin-bottom:12px;">
                    <span>{lang_pack['order_time']}</span>
                    <span>{order_time_text}</span>
                </div>
                <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;">
                    {_merchant_avatar_html(order)}
                    <div style="flex:1;">
                        <div><span style="font-size:0.72rem;color:#000000;">{lang_pack['merchant_label']}</span> <strong>{merchant_name}</strong></div>
                    </div>
                </div>
                <div style="display:flex;gap:12px;align-items:center;">
                    {_product_thumb_html(order)}
                    <div style="flex:1;">
                        <div><span style="font-size:0.72rem;color:#000000;">{lang_pack['product_label']}</span> <strong>{product_name}</strong></div>
                        <div style="color:#000000;font-size:0.8rem;margin-top:4px;">{lang_pack['qty']}: {order.get('quantity',1)}</div>
                    </div>
                </div>
                <div style="margin-top:14px;display:flex;justify-content:space-between;color:#000000;">
                    <span>{lang_pack['unit_price']}</span>
                    <strong style="color:#111827;">{order.get('currency','USD')} {float(order.get('unit_price',0)):.2f}</strong>
                </div>
                <div style="display:flex;justify-content:space-between;margin-top:6px;">
                    <span style="color:#000000;">{lang_pack['total_price']}</span>
                    <strong style="font-size:1.08rem;">{order.get('currency','USD')} {float(order.get('total_price',0)):.2f}</strong>
                </div>
                {timeline_html}
            </div>
            """
    return "\n".join(line for line in card.splitlines() if line.strip())


def order_views_payload(orders):
    """组装订单列表组件所需的数据。"""
    lang = st.session_state.lang
    lang_pack = T[lang]
    items = []
    for order in orders:
        oid = order.get("order_id", "")
        meta = PRODUCT_META.get(oid, {"cat": "generic", "spec": {}})
        specs = meta.get("spec") or {}
        spec = specs.get(lang) or specs.get("en") or ""
        svc = order_services(order)
        tags = [
            {
                "text": ux("tag_free_ship" if svc["free_ship"] else "tag_paid_ship"),
                "kind": "pos" if svc["free_ship"] else "neg",
            }
        ]
        if oid != "ORD-1008":
            tags.append(
                {
                    "text": ux("tag_tax_in" if svc["tax_in"] else "tag_tax_ex"),
                    "kind": "pos" if svc["tax_in"] else "neg",
                }
            )
        tags.append(
            {
                "text": ux("tag_7d" if svc["seven_day"] else "tag_no_7d"),
                "kind": "pos" if svc["seven_day"] else "neg",
            }
        )
        currency = order.get("currency", "USD")
        unit = float(order.get("unit_price") or 0)
        total = float(order.get("total_price") or 0)
        merchant = order.get("merchant") or ""
        product = order.get("product_name") or ""
        avatar = order.get("merchant_avatar") or ""
        image = order.get("product_image") or ""
        timeline = build_timeline(order.get("order_time"), order.get("status", "未发货"))
        nodes = [
            {
                "time": fmt_datetime(node_time, lang),
                "label": lang_pack["node_created"]
                if key == "created"
                else localize_status(key, lang),
                "last": i == len(timeline) - 1,
            }
            for i, (key, node_time) in enumerate(timeline)
        ]
        items.append(
            {
                "id": oid,
                "shop": merchant,
                "shopInitial": merchant[:1].upper() if merchant else "?",
                "shopAvatar": avatar if avatar.startswith("data:") else "",
                "shopInfo": order.get("origin_address") or "",
                "title": product,
                "image": image if image.startswith("data:") else "",
                "imageInitial": product[:1].upper() if product else "?",
                "spec": spec,
                "unitPrice": f"{currency} {unit:.2f}",
                "totalPrice": f"{currency} {total:.2f}",
                "date": fmt_datetime(order.get("order_time"), lang),
                "qty": int(order.get("quantity") or 1),
                "status": localize_status(order.get("status"), lang),
                "timeline": nodes,
                "tags": tags,
            }
        )
    return items


def service_tags_html(order):
    svc = order_services(order)
    chips = []
    if svc["free_ship"]:
        chips.append(("tag_free_ship", "#166534", "#dcfce7"))
    else:
        chips.append(("tag_paid_ship", "#b91c1c", "#fee2e2"))
    if order.get("order_id") != "ORD-1008":
        if svc["tax_in"]:
            chips.append(("tag_tax_in", "#166534", "#dcfce7"))
        else:
            chips.append(("tag_tax_ex", "#b91c1c", "#fee2e2"))
    chips.append(("tag_7d", "#166534", "#dcfce7") if svc["seven_day"] else ("tag_no_7d", "#b91c1c", "#fee2e2"))
    tag_html = "".join(
        f'<span style="display:inline-block;margin:0 8px 8px 0;padding:5px 12px;border-radius:999px;'
        f'font-size:0.78rem;font-weight:700;color:{fg};background:{bg};">{ux(k)}</span>'
        for k, fg, bg in chips
    )
    limits = ""
    if svc["seven_day"]:
        limits = (
            f'<div style="margin-top:2px;padding:10px 12px;background:#f5f3ff;border-radius:10px;'
            f'font-size:0.76rem;color:#5b21b6;line-height:1.6;">{ux("tag_7d_limits")}</div>'
        )
    return tag_html + limits


def risk_block_html(order):
    items = product_risk_items(order, 3)
    rows = "".join(
        f'<div style="margin-top:12px;">'
        f'<div style="font-weight:800;color:#9a3412;font-size:0.86rem;">⚠ {html.escape(t)}</div>'
        f'<div style="margin-top:3px;color:#7c2d12;font-size:0.8rem;line-height:1.65;">{html.escape(b)}</div>'
        f'</div>'
        for t, b in items
    )
    return (
        '<div style="margin-top:18px;padding:14px 16px;background:#fff7ed;'
        'border:1px solid #fdba74;border-left:5px solid #ea580c;border-radius:14px;">'
        f'<div style="font-size:0.95rem;font-weight:800;color:#9a3412;">{ux("risk_title")}</div>'
        f'<div style="margin-top:4px;font-size:0.74rem;color:#a16207;">{ux("risk_intro")}</div>'
        f'{rows}</div>'
    )


def order_detail_payload(order):
    """组装订单详情组件的数据。"""
    lang = st.session_state.lang
    currency = order.get("currency", "USD")
    unit = float(order.get("unit_price") or 0)
    total = float(order.get("total_price") or 0)
    merchant = order.get("merchant") or ""
    product = order.get("product_name") or ""
    _meta, spec = product_meta(order)
    image = order.get("product_image") or ""
    avatar = order.get("merchant_avatar") or ""

    stamps = {
        "created": fmt_datetime(order.get("order_time"), lang),
        "paidAt": "",
        "shipped": "",
        "signed": "",
    }
    base = None
    try:
        base = datetime.strptime(
            str(order.get("order_time") or "").replace("T", " ")[:16], "%Y-%m-%d %H:%M"
        )
    except ValueError:
        base = None
    if base:
        stamps["paidAt"] = fmt_datetime(
            (base + timedelta(minutes=6)).strftime("%Y-%m-%d %H:%M"), lang
        )
        stamps["shipped"] = fmt_datetime(
            (base + timedelta(hours=20)).strftime("%Y-%m-%d %H:%M"), lang
        )
    for key, node_time in build_timeline(order.get("order_time"), order.get("status", "未发货")):
        stamp = fmt_datetime(node_time, lang)
        if key in ("shipped", "in_transit", "clearance"):
            stamps["shipped"] = stamp
        elif key in ("delivered", "signed"):
            stamps["signed"] = stamp
    if not stamps["signed"] and order.get("status") == "已签收" and base:
        stamps["signed"] = fmt_datetime(
            (base + timedelta(hours=72)).strftime("%Y-%m-%d %H:%M"), lang
        )

    phone = str(order.get("buyer_phone") or "")
    if len(phone) >= 7:
        phone = phone[:3] + "****" + phone[-4:]
    receiver = order.get("buyer_name") or ""
    address = order.get("shipping_address") or ""
    ship_to = " · ".join([p for p in (receiver, phone, address) if p])

    return {
        "id": order.get("order_id") or "",
        "status": localize_status(order.get("status"), lang),
        "statusGreen": order.get("status") == "已签收",
        "clearance": order.get("status") == "清关中",
        "address": address,
        "receiver": receiver,
        "phone": phone,
        "shop": merchant,
        "shipFrom": order.get("origin_address") or "-",
        "sender": merchant,
        "tracking": order.get("tracking") or "-",
        "shopInitial": merchant[:1].upper() if merchant else "?",
        "shopAvatar": avatar if avatar.startswith("data:") else "",
        "image": image if image.startswith("data:") else "",
        "imageInitial": product[:1].upper() if product else "?",
        "title": product,
        "spec": spec,
        "origPrice": f"{currency} {unit:.2f}",
        "qty": int(order.get("quantity") or 1),
        "paidPrice": f"{currency} {total:.2f}",
        "payMethod": order.get("payment_method")
        or _PAY_BY_CURRENCY.get(currency, "Visa •••• 4242"),
        "shipTo": ship_to or "—",
        "created": stamps["created"],
        "paidAt": stamps["paidAt"],
        "shipped": stamps["shipped"],
        "signed": stamps["signed"],
    }


def merchant_stars(rating):
    full = max(0, min(5, int(round(rating))))
    return ('<span class="cg-ms-star">' + "★" * full + "</span>"
            + '<span class="cg-ms-star off">' + "★" * (5 - full) + "</span>")
