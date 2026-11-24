import re
import os
import random
import html
import base64
import textwrap
import time
from datetime import datetime
import streamlit as st

import streamlit.components.v1 as components

from app.llm import describe_attachments
from app.after_sales_agent import chat as after_sales_chat
from app.after_sales_agent import chat_stream as after_sales_chat_stream
from app.after_sales_agent import resume as after_sales_resume
from app.ui_intents import is_exchange_rate_query
from ui.copy import T, LANG_CODES, LOG_T, CURRENCY_LABELS, LANG_NAMES
from ui.catalog import (
    DELISTED_ORDERS, _FALLBACK_ORDERS, EXCHANGE_RATES, CURRENCY_ALIASES,
)

st.set_page_config(page_title="CargoGuard", layout="wide")

from ui.html import (
    fmt_datetime, localize_status, order_views_payload, ux,
    _identity_row, _merchant_avatar_html,
)
from ui.components import (
    ai_extra_context, ai_prior_history, ai_thread_id, ai_user_id,
    clear_composer_attachments, goto, load_ai_sessions, nav_component,
    order_list_component, order_views_component, render_ai_empty_state,
    render_ai_history, render_approval_card, render_back_button, render_chat_composer,
    render_chat_panel, render_header, render_logistics, render_merchant_store,
    render_order_detail, render_product_detail, save_ai_sessions,
    sidebar_toggle_component, touch_ai_title, _now_ts,
    chat_scroll_html, empty_state_html, make_chat_drawer,
)


# =========================================================
# 启动开场动画（仅首次进入播放一次，3 秒后自动进入主界面）
# =========================================================
SPLASH_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "splash.svg")

if not st.session_state.get("has_booted"):
    with open(SPLASH_PATH, encoding="utf-8") as _f:
        _splash_svg = _f.read()
    # 必须压成单行：Markdown 遇到空行会中断 HTML 块，导致 SVG 被当成代码文本渲染
    _splash_html = (
        "<style>"
        ".cg-enter-input{position:fixed;width:0;height:0;opacity:0;pointer-events:none;}"
        ".cg-splash-overlay{position:fixed;inset:0;z-index:999999;background:#ffffff;"
        "display:grid;place-items:center;cursor:pointer;touch-action:manipulation;user-select:none;"
        "-webkit-tap-highlight-color:transparent;transition:opacity .32s ease-out;}"
        ".cg-splash-overlay svg{width:min(92vw,1040px);height:auto;display:block;}"
        ".cg-splash-label{position:absolute;inset:0;display:grid;place-items:center;cursor:pointer;}"
        ".cg-splash-hint{position:absolute;left:0;right:0;bottom:max(8%,env(safe-area-inset-bottom));"
        "text-align:center;font-size:14px;color:#000000;letter-spacing:1px;opacity:0;"
        "animation:cgHintIn .5s ease-out 2.6s forwards;pointer-events:none;}"
        ".cg-splash-hint span{display:inline-block;transform-origin:center;font-weight:500;"
        "cursor:pointer;pointer-events:auto;"
        "transition:transform 180ms ease-out,font-weight 180ms ease-out,text-shadow 180ms ease-out;}"
        ".cg-splash-hint span:hover{transform:scale(1.08);font-weight:600;"
        "text-shadow:0 0 10px rgba(17,24,39,.12);}"
        ".cg-splash-hint span:active{transform:scale(.97);font-weight:600;}"
        "@keyframes cgHintIn{to{opacity:1;}}"
        # 点击波纹：从点击位置向外扩散的圆形转场
        ".cg-click-ripple{position:fixed;left:0;top:0;width:0;height:0;border-radius:50%;"
        "pointer-events:none;z-index:999998;transform:translate(-50%,-50%);"
        "background:radial-gradient(circle,rgba(248,249,251,.98) 0%,rgba(232,234,238,.72) 38%,rgba(255,255,255,0) 72%);"
        "box-shadow:0 0 36px 8px rgba(210,214,222,.28);}"
        ".cg-ripple-anim{animation:cgRippleExpand .62s cubic-bezier(.2,.7,.2,1) forwards;}"
        "@keyframes cgRippleExpand{0%{width:0;height:0;opacity:1;}"
        "100%{width:260vmax;height:260vmax;opacity:0;}}"
        ".cg-enter-input:checked + .cg-splash-overlay{opacity:0;visibility:hidden;"
        "pointer-events:none;transition:opacity .32s ease-out,visibility 0s .32s;}"
        # 开屏期间隐藏侧栏/顶栏，避免网页内容从旁边透出
        'body:not(:has(#cgEnter:checked)) [data-testid="stSidebar"]'
        "{display:none !important;}"
        'body:not(:has(#cgEnter:checked)) [data-testid="stHeader"],'
        'body:not(:has(#cgEnter:checked)) [data-testid="stToolbar"],'
        'body:not(:has(#cgEnter:checked)) [data-testid="stDecoration"],'
        'body:not(:has(#cgEnter:checked)) [data-testid="stStatusWidget"]'
        "{visibility:hidden !important;}"
        'body:not(:has(#cgEnter:checked)) [data-testid="stMain"]'
        "{background:#ffffff !important;}"
        'body:not(:has(#cgEnter:checked)){overflow:hidden !important;}'
        'body:has(#cgEnter:checked) [data-testid="stMain"],'
        'body:has(#cgEnter:checked) [data-testid="stSidebar"]'
        "{animation:cgMainFade .42s ease-out both;}"
        "@keyframes cgMainFade{from{opacity:0;}to{opacity:1;}}"
        "@media(hover:none){.cg-splash-hint span:hover{transform:none;font-weight:500;}"
        ".cg-splash-hint span:active{transform:scale(.97);font-weight:600;}}"
        "@media(prefers-reduced-motion:reduce){"
        ".cg-splash-overlay,.cg-splash-hint,.cg-splash-hint span{"
        "animation:none!important;transition:none!important;}"
        ".cg-splash-hint{opacity:1;}"
        ".cg-splash-hint span:hover,.cg-splash-hint span:active{transform:none;font-weight:500;text-shadow:none!important;}"
        ".cg-click-ripple{display:none!important;}"
        'body:has(#cgEnter:checked) [data-testid="stMain"],'
        'body:has(#cgEnter:checked) [data-testid="stSidebar"]{animation:none!important;}'
        "}"
        "</style>"
        '<input type="checkbox" id="cgEnter" class="cg-enter-input">'
        '<div class="cg-splash-overlay"><div class="cg-splash-label">'
        + " ".join(_splash_svg.splitlines())
        + '<div class="cg-splash-hint"><span>Click</span></div>'
        + "</div></div>"
    )
    st.markdown(_splash_html, unsafe_allow_html=True)
    # 通过 components.html 注入可执行 JS：监听全屏点击，从点击位置扩散圆形波纹后勾选进入复选框
    components.html(
        "<script>"
        "(function(){"
        "function attach(){"
        "var doc=parent.document,overlay=doc.querySelector('.cg-splash-overlay'),box=doc.getElementById('cgEnter');"
        "if(!overlay||!box){setTimeout(attach,120);return;}"
        "if(doc._cgRippleBound)return;doc._cgRippleBound=true;"
        "var reduced=parent.matchMedia&&parent.matchMedia('(prefers-reduced-motion: reduce)').matches;"
        "overlay.addEventListener('pointerdown',function(e){"
        "if(box.checked)return;"
        "var pt=e;if(e.pointerType==='touch'&&e.touches&&e.touches[0])pt=e.touches[0];"
        "var x=pt.clientX,y=pt.clientY;"
        "if(reduced){box.checked=true;return;}"
        "var r=doc.createElement('div');r.className='cg-click-ripple';r.style.left=x+'px';r.style.top=y+'px';"
        "doc.body.appendChild(r);void r.offsetWidth;r.classList.add('cg-ripple-anim');"
        "setTimeout(function(){box.checked=true;},240);"
        "setTimeout(function(){r.remove();},900);"
        "},{passive:true});}"
        "attach();"
        "})();"
        "</script>",
        height=0,
    )
    st.session_state["has_booted"] = True


# 商家客服后台搜索区文案（五语言）
SEARCH_I18N = {
    "en": {
        "search": "Search", "reset": "Reset", "time_filter": "Order date", "any_time": "Any time",
        "last7": "Last 7 days", "last30": "Last 30 days", "this_month": "This month",
        "last_month": "Last month", "custom": "Custom range", "start": "Start date", "end": "End date",
        "no_result": "No matching records. Check the order ID, merchant or product name, or adjust the date range.",
        "recent": "Recent searches", "tab_orders": "Orders", "tab_merchants": "Merchants",
        "tab_products": "Products", "view_detail": "View details", "sku_label": "SKU",
        "amount_label": "Amount", "after_sales": "After-sales",
        "search_placeholder": "Search by order ID / merchant / product; set order date below",
        "orders_count": "{n} orders",
    },
    "zh": {
        "search": "搜索", "reset": "重置", "time_filter": "下单时间", "any_time": "不限时间",
        "last7": "近 7 天", "last30": "近 30 天", "this_month": "本月",
        "last_month": "上月", "custom": "自定义区间", "start": "开始日期", "end": "结束日期",
        "no_result": "未找到匹配数据，请核对订单号/商家名/商品名称，或调整下单时间范围。",
        "recent": "最近搜索", "tab_orders": "订单", "tab_merchants": "商家",
        "tab_products": "商品", "view_detail": "查看详情", "sku_label": "SKU",
        "amount_label": "金额", "after_sales": "售后",
        "search_placeholder": "支持订单号 / 商家名称 / 商品名称搜索，下单时间可在筛选区选择",
        "orders_count": "共 {n} 单",
    },
    "ja": {
        "search": "検索", "reset": "リセット", "time_filter": "注文日", "any_time": "期間指定なし",
        "last7": "過去7日", "last30": "過去30日", "this_month": "今月",
        "last_month": "先月", "custom": "カスタム期間", "start": "開始日", "end": "終了日",
        "no_result": "一致するデータがありません。注文番号・販売者名・商品名をご確認いただくか、注文日の範囲を調整してください。",
        "recent": "最近の検索", "tab_orders": "注文", "tab_merchants": "販売者",
        "tab_products": "商品", "view_detail": "詳細を見る", "sku_label": "SKU",
        "amount_label": "金額", "after_sales": "アフターサービス",
        "search_placeholder": "注文番号・販売者名・商品名で検索（注文日は下のフィルターで指定）",
        "orders_count": "全 {n} 件",
    },
    "ko": {
        "search": "검색", "reset": "초기화", "time_filter": "주문 시간", "any_time": "시간 제한 없음",
        "last7": "최근 7일", "last30": "최근 30일", "this_month": "이번 달",
        "last_month": "지난달", "custom": "사용자 지정 기간", "start": "시작일", "end": "종료일",
        "no_result": "일치하는 데이터가 없습니다. 주문번호/판매자명/상품명을 확인하거나 주문 시간 범위를 조정하세요.",
        "recent": "최근 검색", "tab_orders": "주문", "tab_merchants": "판매자",
        "tab_products": "상품", "view_detail": "상세 보기", "sku_label": "SKU",
        "amount_label": "금액", "after_sales": "애프터서비스",
        "search_placeholder": "주문번호·판매자명·상품명으로 검색(주문 시간은 아래 필터에서 선택)",
        "orders_count": "총 {n}건",
    },
    "fr": {
        "search": "Rechercher", "reset": "Réinitialiser", "time_filter": "Date de commande",
        "any_time": "Toutes dates", "last7": "7 derniers jours", "last30": "30 derniers jours",
        "this_month": "Ce mois", "last_month": "Mois dernier", "custom": "Période personnalisée",
        "start": "Date de début", "end": "Date de fin",
        "no_result": "Aucun résultat. Vérifiez le n° de commande, le vendeur ou le produit, ou ajustez la période.",
        "recent": "Recherches récentes", "tab_orders": "Commandes", "tab_merchants": "Vendeurs",
        "tab_products": "Produits", "view_detail": "Voir le détail", "sku_label": "SKU",
        "amount_label": "Montant", "after_sales": "SAV",
        "search_placeholder": "Rechercher par n° de commande / vendeur / produit ; la date se règle ci-dessous",
        "orders_count": "{n} commandes",
    },
}
for _code, _pack in SEARCH_I18N.items():
    T[_code].update(_pack)


def _preset_greeting(key, original_lang):
    """对方首条消息：保留原文，并附上人工预置的五语言译文。"""
    return {
        "role": "ai",
        "content": T[original_lang][key],
        "original_lang": original_lang,
        "translations": {code: T[code][key] for code in LANG_CODES},
        "ts": _now_ts(),
    }


PRESET_MESSAGES = {
    "merchant_default": _preset_greeting("merchant_default", "en"),
    "platform_default": _preset_greeting("platform_default", "zh"),
}


def ack_message(key, **fmt):
    """对方自动回复：原文按中文保存，并附五语言预置译文。"""
    translations = {code: T[code][key].format(**fmt) for code in LANG_CODES}
    return {
        "role": "ai",
        "content": translations["zh"],
        "original_lang": "zh",
        "translations": translations,
        "ts": _now_ts(),
    }


def load_orders():
    try:
        from app.db import get_connection, init_db
        init_db()
        conn = get_connection()
        rows = conn.execute(
            "SELECT order_id, seller_name, merchant_avatar, product_name, product_image, "
            "quantity, unit_price, total_amount, currency, shipping_status, tracking_number, "
            "shipping_fee, logistics_info, status, order_time, shipping_address, origin_address "
            "FROM orders ORDER BY order_id"
        ).fetchall()
        conn.close()
        out = []
        for r in rows:
            d = dict(r)
            d["merchant"] = d.pop("seller_name", "")
            d["total_price"] = d.pop("total_amount", 0)
            # 图片：路径则转 base64 data URI；否则当首字母占位
            for key in ("merchant_avatar", "product_image"):
                val = d.get(key)
                if val and os.path.exists(val):
                    with open(val, "rb") as _f:
                        b64 = base64.b64encode(_f.read()).decode()
                    ext = os.path.splitext(val)[1].lstrip(".").lower()
                    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
                    d[key] = f"data:{mime};base64,{b64}"
                elif val and val.startswith("data:"):
                    pass  # 已是 data URI
                else:
                    d[key] = None  # 标记为无图，渲染时用首字母占位
            d.setdefault("quantity", 1)
            d.setdefault("unit_price", 0.0)
            d.setdefault("currency", "USD")
            d.setdefault("shipping_fee", 0.0)
            d.setdefault("status", "未发货")
            d.setdefault("order_time", None)
            out.append(d)
        return out
    except Exception:
        return list(_FALLBACK_ORDERS)

orders = load_orders()
if not st.session_state.get("is_logged_in", True):
    orders = []

# 已注销（跑路/关店）的商家：这些店铺的客服入口只显示「该账户已注销」
CLOSED_MERCHANTS = {
    o.get("merchant", "") for o in orders if o.get("order_id") in DELISTED_ORDERS
}


# =========================================================
# 初始化状态
# =========================================================
if "lang" not in st.session_state:
    st.session_state.lang = "en"

if "page" not in st.session_state:
    st.session_state.page = "ai"

if "page_stack" not in st.session_state:
    st.session_state.page_stack = []


if "ai_sessions" not in st.session_state:
    restored = load_ai_sessions()
    if restored:
        st.session_state.ai_sessions, st.session_state.ai_active, st.session_state.ai_seq = restored
    else:
        st.session_state.ai_sessions = [{
            "id": "s1",
            "title": "",
            "created": datetime.now(),
            "messages": [{"role": "ai", "i18n": "default_ai", "ts": _now_ts()}],
        }]
        st.session_state.ai_active = "s1"
        st.session_state.ai_seq = 1

if "ai_messages" not in st.session_state:
    active_session = next(
        (s for s in st.session_state.ai_sessions if s["id"] == st.session_state.ai_active),
        st.session_state.ai_sessions[0],
    )
    st.session_state.ai_messages = active_session["messages"]

if "ai_hist_seq" not in st.session_state:
    st.session_state.ai_hist_seq = 0

if "merchant_search" not in st.session_state:
    st.session_state.merchant_search = ""

if "merchant_query" not in st.session_state:
    st.session_state.merchant_query = ""

if "merchant_search_history" not in st.session_state:
    st.session_state.merchant_search_history = []

if "selected_merchant" not in st.session_state:
    st.session_state.selected_merchant = orders[0]["merchant"] if orders else ""

if "merchant_messages" not in st.session_state:
    # 按数据库里实际存在的商家初始化，避免新商家没有会话
    st.session_state.merchant_messages = {
        o["merchant"]: [dict(PRESET_MESSAGES["merchant_default"])]
        for o in orders
        if o.get("merchant")
    }

if "platform_messages" not in st.session_state:
    st.session_state.platform_messages = [dict(PRESET_MESSAGES["platform_default"])]

# =========================================================
# helper functions
# =========================================================
def find_order_by_id(order_id):
    for o in orders:
        if o["order_id"].upper() == order_id.upper():
            return o
    return None

def resolve_order_id(text, order_list):
    """解析订单号：完整 ORD-xxxx 直接匹配；裸号(如1001)仅在唯一匹配已有订单时返回，否则 None。"""
    m = re.search(r"ORD-\d{3,}", text, flags=re.I)
    if m:
        oid = m.group(0).upper()
        if any(o["order_id"].upper() == oid for o in order_list):
            return oid
        return None
    m = re.search(r"(?<!\d)(\d{3,6})(?!\d)", text)
    if m:
        digits = m.group(1)
        candidates = [o["order_id"] for o in order_list if o["order_id"].upper() == f"ORD-{digits}"]
        if len(candidates) == 1:
            return candidates[0]
    return None

def parse_rate_query(question):
    """从自然语言中解析金额和币种。按币种在句中出现的先后顺序确定 from/to。"""
    q = question.lower().strip()
    amount_match = re.search(r"(\d+(?:\.\d+)?)", q)
    amount = float(amount_match.group(1)) if amount_match else 1.0

    mentions = []
    for code, aliases in CURRENCY_ALIASES.items():
        first_idx = None
        for alias in aliases:
            idx = q.find(alias)
            if idx != -1 and (first_idx is None or idx < first_idx):
                first_idx = idx
        if first_idx is not None:
            mentions.append((first_idx, code))
    mentions.sort(key=lambda x: x[0])

    from_code = mentions[0][1] if mentions else "USD"
    to_code = None
    for _, code in mentions[1:]:
        if code != from_code:
            to_code = code
            break
    if to_code is None:
        to_code = "CNY" if from_code != "CNY" else "USD"

    return amount, from_code, to_code

def rate_conversion(amount, from_code, to_code):
    if from_code == to_code:
        return amount
    usd_value = amount / EXCHANGE_RATES[from_code]
    return usd_value * EXCHANGE_RATES[to_code]

def get_rate_answer(question):
    amount, from_code, to_code = parse_rate_query(question)
    converted = rate_conversion(amount, from_code, to_code)
    ratio = EXCHANGE_RATES[to_code] / EXCHANGE_RATES[from_code]
    return T[st.session_state.lang]["rate_answer"].format(
        **{"from": from_code, "to": to_code, "ratio": ratio, "amount": amount, "converted": converted}
    )


def strip_self_disclaimer(reply):
    """去掉模型自行追加的免责提示，避免与系统统一追加的那条重复。"""
    text = reply.strip()
    markers = (
        "免责提示：本内容仅为维权参考建议",
        "Disclaimer: This content is for reference only",
        "免責事項：本内容は参考情報",
        "면책 안내: 본 내용은 참고용",
        "Avertissement : ce contenu",
    )
    for marker in markers:
        idx = text.rfind(marker)
        if idx != -1:
            text = text[:idx].rstrip(" \n-\u2014")
    return text


# 用户报告实际问题或申请售后行动时，才在回复末尾追加免责声明；
# 纯状态/进度查询（“发货了吗”“到哪了”“退款进度”）不加，保持简短。
_PROBLEM_REPORT_WORDS = (
    "破损", "损坏", "发错", "错发", "货不对板", "没收到", "未收到", "丢件", "丢失",
    "停滞", "卡住", "不动", "没更新", "被扣", "查验", "扣货",
    "拒绝", "拒退", "不给退", "拖延", "不理", "不回", "已读不回", "敷衍",
    "投诉", "维权", "举报", "态度", "跑路", "关店", "失联",
    "申请退", "我要退", "退货", "取消订单", "退钱", "退运费",
    "damaged", "wrong item", "not received", "dispute", "complaint",
)


def _is_problem_report(text):
    low = (text or "").lower()
    return any(w.lower() in low for w in _PROBLEM_REPORT_WORDS)


# =========================================================
# CSS
# =========================================================
st.markdown("""
<style>
    html, body, [data-testid="stAppViewContainer"] {
        background: #ffffff;
        color: #111827;
        font-size: 16px;
        margin: 0 !important;
    }

    /* 左侧导航：浅灰底；右侧内容区：纯白、卡片白色 */
    [data-testid="stSidebar"],
    [data-testid="stSidebar"] > div,
    [data-testid="stSidebarContent"] {
        background: #f2f4f7 !important;
    }
    [data-testid="stSidebar"] {
        border-right: 1px solid #e3e7ee;
    }

    /* 隐藏 Streamlit 自带顶栏（Deploy 那一行），内容整体上移 */
    [data-testid="stHeader"],
    [data-testid="stToolbar"],
    [data-testid="stDecoration"],
    [data-testid="stStatusWidget"] {
        display: none !important;
        height: 0 !important;
    }
    [data-testid="stAppViewContainer"],
    [data-testid="stMain"],
    [data-testid="stMainBlockContainer"] {
        padding-top: 0 !important;
        margin-top: 0 !important;
        top: 0 !important;
    }

    main .block-container {
        padding-top: 0 !important;
        padding-bottom: 0 !important;
        padding-left: 0.6rem !important;
        padding-right: 0.6rem !important;
        margin-top: 0 !important;
    }

    div[data-testid="stVerticalBlock"] > div {
        padding: 0 !important;
        margin: 0 !important;
    }

    div[data-testid="stVerticalBlockBorderWrapper"] > div {
        margin: 0 !important;
        padding: 0 !important;
    }

    .brand {
        font-size: 2.4rem;
        font-weight: 800;
        letter-spacing: 0.5px;
        color: #111827;
        text-align: center;
        padding: 4px 0 14px 0;
        margin: 0;
    }

    .chat-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        background: #f8fafc;
        border: 1px solid #e5e7eb;
        border-radius: 14px;
        padding: 10px 12px;
        font-weight: 700;
    }

    .composer {
        display: flex;
        align-items: center;
        gap: 10px;
        background: white;
        border: 1px solid #e5e7eb;
        border-radius: 999px;
        padding: 7px 10px;
        min-height: 52px;
        margin: 0 !important;
        box-shadow: 0 3px 12px rgba(15,23,42,0.03);
    }

    .attachment {
        width: 38px;
        height: 38px;
        border-radius: 50%;
        border: 1px solid #dfe6f0;
        background: white;
        display: flex;
        justify-content: center;
        align-items: center;
        font-weight: 700;
        color: #000000;
    }

    .info-box {
        background: white;
        border: 1px solid #e5e7eb;
        border-radius: 18px;
        padding: 14px;
        box-shadow: 0 8px 18px rgba(15,23,42,0.03);
        margin: 0 !important;
    }

    .info-row {
        display: flex;
        justify-content: space-between;
        gap: 12px;
        padding: 8px 0;
        border-bottom: 1px solid #edf2f7;
    }

    .info-row:last-child { border-bottom: none; }

    div[data-testid="stTextInput"] {
        background: #ffffff !important;
        border: 1px solid #e5e7eb !important;
        border-radius: 999px !important;
        padding: 4px 12px !important;
        box-shadow: none !important;
        margin: 0 !important;
    }

    div[data-testid="stTextInput"] > div {
        background: #ffffff !important;
        border: none !important;
        box-shadow: none !important;
    }

    div[data-testid="stTextInput"] input {
        background: #ffffff !important;
        border: none !important;
        outline: none !important;
        box-shadow: none !important;
        font-size: 1rem !important;
        color: #111827 !important;
        -webkit-text-fill-color: #111827 !important;
        caret-color: #111827 !important;
        opacity: 1 !important;
    }

    div[data-testid="stTextInput"] input::placeholder {
        color: #000000 !important;
        -webkit-text-fill-color: #000000 !important;
        opacity: 1 !important;
    }

    div[data-testid="stTextInput"] label {
        display: none !important;
    }

    /* 发送等主按钮：浅灰底 + 深字，亮色/深色主题下对比度一致 */
    .stButton > button,
    .stButton > button:focus,
    .stButton > button:focus-visible,
    .stButton > button:disabled,
    .stButton > button[disabled] {
        width: 100%;
        border-radius: 12px;
        color: #111827 !important;
        -webkit-text-fill-color: #111827 !important;
        background-color: #e5e7eb !important;
        background-image: none !important;
        border: 1px solid #d1d5db !important;
        font-weight: 800;
        min-height: 40px;
        font-size: 0.95rem !important;
        box-shadow: none !important;
        opacity: 1 !important;
    }

    .stButton > button:hover {
        color: #111827 !important;
        -webkit-text-fill-color: #111827 !important;
        background-color: #dfe3e9 !important;
        border-color: #c9cfd8 !important;
    }

    .stButton > button:active {
        background-color: #d5dae1 !important;
        border-color: #c0c7d1 !important;
    }

    /* 「+」/表情按钮：亮色与深色主题下都强制白底浅灰边、深色图标 */
    div[data-testid="stPopover"] button,
    div[data-testid="stPopover"] > button,
    button[data-testid="stPopoverButton"],
    div[data-testid="stPopover"] [data-testid="stPopoverButton"] {
        width: 100%;
        border-radius: 50% !important;
        background: #ffffff !important;
        background-color: #ffffff !important;
        background-image: none !important;
        color: #111827 !important;
        -webkit-text-fill-color: #111827 !important;
        border: 1px solid #e5e7eb !important;
        font-size: 1.25rem !important;
        font-weight: 700 !important;
        min-height: 44px;
        box-shadow: none !important;
        opacity: 1 !important;
    }

    div[data-testid="stPopover"] button *,
    div[data-testid="stPopover"] > button *,
    button[data-testid="stPopoverButton"] * {
        color: #111827 !important;
        -webkit-text-fill-color: #111827 !important;
    }

    div[data-testid="stPopover"] button:hover,
    div[data-testid="stPopover"] button:focus,
    div[data-testid="stPopover"] button:focus-visible,
    div[data-testid="stPopover"] button:active,
    div[data-testid="stPopover"] button:disabled,
    div[data-testid="stPopover"] button[aria-expanded="true"],
    button[data-testid="stPopoverButton"]:hover,
    button[data-testid="stPopoverButton"]:focus,
    button[data-testid="stPopoverButton"]:focus-visible,
    button[data-testid="stPopoverButton"]:active,
    button[data-testid="stPopoverButton"]:disabled,
    button[data-testid="stPopoverButton"][aria-expanded="true"] {
        background: #ffffff !important;
        background-color: #ffffff !important;
        background-image: none !important;
        color: #111827 !important;
        -webkit-text-fill-color: #111827 !important;
        border: 1px solid #d1d5db !important;
        box-shadow: none !important;
        opacity: 1 !important;
    }

    /* 表情面板内的 emoji 按钮：白底深字，亮色/深色主题下都清晰 */
    div[data-testid="stPopover"] div[data-testid="stVerticalBlock"] .stButton > button {
        background: #ffffff !important;
        color: #111827 !important;
        -webkit-text-fill-color: #111827 !important;
        border: 1px solid #e5e7eb !important;
        border-radius: 10px !important;
        min-height: 38px !important;
        padding: 2px 0 !important;
        font-size: 1.15rem !important;
        font-weight: 500 !important;
    }

    div[data-testid="stPopover"] div[data-testid="stVerticalBlock"] .stButton > button:hover {
        background: #f9fafb !important;
        border-color: #d1d5db !important;
    }

    /* 表情面板 / 附件面板：强制白底，避免深色主题下浅字压浅底 */
    div[data-testid="stPopoverBody"] {
        background: #ffffff !important;
        color: #111827 !important;
    }

    /* 订单状态标签展开的 <details>：隐藏浏览器默认三角 */
    details summary { list-style: none; }
    details summary::-webkit-details-marker { display: none; }

    /* 下拉选择框（语言切换 / 汇率 / 搜索筛选）：统一浅色，避免深色底压抑 */
    div[data-baseweb="select"] > div {
        background-color: #ffffff !important;
        border: 1px solid #d1d5db !important;
        color: #111827 !important;
    }

    div[data-baseweb="select"] > div:hover {
        border-color: #9ca3af !important;
    }

    div[data-baseweb="select"] span,
    div[data-baseweb="select"] input,
    div[data-baseweb="select"] [data-testid="stSelectbox"] * {
        color: #111827 !important;
        -webkit-text-fill-color: #111827 !important;
    }

    div[data-baseweb="select"] svg {
        fill: #000000 !important;
        color: #000000 !important;
    }

    /* 下拉展开后的选项列表 */
    ul[data-testid="stSelectboxVirtualDropdown"],
    div[data-baseweb="popover"] ul,
    div[data-baseweb="popover"] div[role="listbox"] {
        background-color: #ffffff !important;
        border: 1px solid #e5e7eb !important;
    }

    div[data-baseweb="popover"] li,
    div[data-baseweb="popover"] div[role="option"] {
        background-color: #ffffff !important;
        color: #111827 !important;
    }

    div[data-baseweb="popover"] li:hover,
    div[data-baseweb="popover"] div[role="option"]:hover,
    div[data-baseweb="popover"] li[aria-selected="true"],
    div[data-baseweb="popover"] div[role="option"][aria-selected="true"] {
        background-color: #f3f4f6 !important;
        color: #111827 !important;
    }

    /* AI 页输入区：圆角卡片贴底（页面不滚动，只有对话区滚动） */
    .st-key-cg_chat_composer {
        /* 首帧就用 fixed 贴住底部，避免加载后被脚本挪位产生跳动；
           left/width 由 fit_chat 组件写入 CSS 变量，默认值作为兜底 */
        position: fixed !important;
        left: var(--cg-chat-left, 344px) !important;
        right: auto !important;
        width: var(--cg-chat-width, calc(100vw - 360px)) !important;
        bottom: 16px !important;
        margin: 0 !important;
        z-index: 999;
        background: #ffffff;
        border: 1px solid #cdd9ea;
        border-radius: 26px;
        padding: 10px 16px 8px 16px;
        box-sizing: border-box;
        box-shadow: 0 10px 28px rgba(15, 23, 42, 0.08);
    }
    /* 测量组件本身不占高度，把省下的空间让给对话区 */
    .st-key-cg_fit_chat {
        height: 0 !important;
        min-height: 0 !important;
        padding: 0 !important;
        margin: 0 !important;
        overflow: hidden !important;
    }
    /* 输入框内部：收紧间距，隐藏回车提示与聚焦描边 */
    .st-key-cg_chat_composer [data-testid="stVerticalBlock"] {
        gap: 4px !important;
    }
    .st-key-cg_chat_composer [data-testid="InputInstructions"] {
        display: none !important;
    }
    .st-key-cg_chat_composer [data-testid="stTextInputRootElement"] {
        border: 0 !important;
        box-shadow: none !important;
        background: transparent !important;
    }
    /* 隐藏右下角状态浮标与页脚，避免挤占底部间距 */
    footer, [data-testid="stStatusWidget"], #MainMenu {
        display: none !important;
    }
    .st-key-cg_chat_composer .stFormSubmitButton {
        display: none !important;
    }
    .st-key-cg_chat_composer [data-testid="stForm"] {
        border: 0 !important;
        padding: 0 !important;
        background: transparent !important;
    }
    .st-key-cg_chat_composer [data-testid="stTextInput"] div[data-baseweb="input"],
    .st-key-cg_chat_composer [data-testid="stTextInput"] div[data-baseweb="base-input"] {
        border: 0 !important;
        background: transparent !important;
        box-shadow: none !important;
        outline: none !important;
    }
    .st-key-cg_chat_composer [data-testid="stTextInput"] div[data-baseweb="input"]:focus-within,
    .st-key-cg_chat_composer [data-testid="stTextInput"] div[data-baseweb="base-input"]:focus-within {
        border: 0 !important;
        box-shadow: none !important;
        outline: none !important;
    }
    .st-key-cg_chat_composer [data-testid="stTextInput"] input {
        border: 0 !important;
        background: transparent !important;
        box-shadow: none !important;
        font-size: 1rem !important;
        color: #000000 !important;
        padding: 4px 2px !important;
    }
    .st-key-cg_chat_composer [data-testid="stPopover"] > div > button {
        width: 36px;
        height: 36px;
        min-height: 36px;
        padding: 0 !important;
        border-radius: 50% !important;
        border: 1px solid #e2e8f0 !important;
        background: #ffffff !important;
        color: #000000 !important;
        font-size: 1.05rem !important;
        line-height: 1 !important;
    }
    .st-key-cg_chat_composer [data-testid="stPopover"] > div > button:hover {
        background: #f3f6fb !important;
    }
    /* 聊天页撑满视口、输入框贴底的规则在 render_chat_composer 中按页注入 */
    [data-testid="stMain"] .block-container,
    section.main .block-container {
        padding-bottom: 0 !important;
    }

    /* AI 页去掉顶部大留白：让对话区上沿贴近右上角两个图标 */
    [data-testid="stMain"] .block-container:has(.st-key-cg_ai_topbar) {
        padding-top: 0 !important;
    }
    /* AI 页右上角：两个图标按钮（时钟 / 对话），相对主区域上移，与左侧 CargoGuard 品牌同一高度 */
    .st-key-cg_ai_topbar {
        position: relative !important;
        top: 0 !important;
        width: 100% !important;
        height: 34px !important;
        min-height: 34px !important;
        margin: 0 !important;
        z-index: 1000 !important;
        pointer-events: none !important;
    }
    .st-key-cg_ai_topbar > div {
        pointer-events: auto !important;
    }
    .st-key-cg_hist_btn,
    .st-key-cg_new_btn {
        position: absolute !important;
        /* 上移 2cm 后再下移 10px：图标略微离顶，对话区由脚本上拉到图标下方 */
        top: -84px !important;
        display: inline-flex !important;
        justify-content: center !important;
        align-items: center !important;
        width: 34px !important;
        min-width: 34px !important;
        max-width: 34px !important;
        height: 34px !important;
    }
    .st-key-cg_hist_btn {
        right: 58px !important;
    }
    .st-key-cg_new_btn {
        right: 16px !important;
    }
    .st-key-cg_hist_btn [data-testid="stPopoverButton"],
    .st-key-cg_hist_btn [data-testid="stPopover"] button,
    .st-key-cg_new_btn .stButton > button {
        width: 34px !important;
        height: 34px !important;
        min-height: 34px !important;
        padding: 0 !important;
        border-radius: 50% !important;
        background: transparent !important;
        background-color: transparent !important;
        background-image: none !important;
        border: 0 !important;
        box-shadow: none !important;
        color: #000000 !important;
        -webkit-text-fill-color: #000000 !important;
        font-size: 1.1rem !important;
        font-weight: 400 !important;
    }
    .st-key-cg_hist_btn [data-testid="stPopoverButton"]:hover,
    .st-key-cg_hist_btn [data-testid="stPopover"] button:hover,
    .st-key-cg_new_btn .stButton > button:hover,
    .st-key-cg_new_btn .stButton > button:focus,
    .st-key-cg_new_btn .stButton > button:active {
        background: #f2f4f7 !important;
        background-color: #f2f4f7 !important;
        border: 0 !important;
        color: #000000 !important;
    }
    /* 隐藏 popover 自带的折叠箭头 */
    .st-key-cg_hist_btn [data-testid="stPopoverButton"] svg,
    .st-key-cg_hist_btn [data-testid="stPopover"] button svg,
    .st-key-cg_hist_btn [data-testid="stIconMaterial"],
    .st-key-cg_hist_btn [data-testid="stPopoverButton"] [data-testid="stIconMaterial"] {
        display: none !important;
    }
    /* 悬停时在图标下方显示灰色提示框（文案由页面按语言注入） */
    .st-key-cg_hist_btn::after,
    .st-key-cg_new_btn::after {
        position: absolute;
        top: 100%;
        right: 0;
        margin-top: 4px;
        padding: 4px 10px;
        border-radius: 8px;
        background: #f2f4f7;
        color: #000000 !important;
        font-size: 0.72rem;
        font-weight: 600;
        white-space: nowrap;
        opacity: 0;
        pointer-events: none;
        transition: opacity 0.15s ease-out;
        z-index: 1000;
    }
    .st-key-cg_hist_btn:hover::after,
    .st-key-cg_new_btn:hover::after {
        opacity: 1;
    }

    /* ===== 统一按压反馈：hover 上浮 + 阴影加深，active 缩放到 0.97 ===== */
    button,
    [role="button"],
    [data-baseweb="select"] > div,
    [data-testid="stPopoverButton"] {
        transition: transform 140ms ease-out, box-shadow 140ms ease-out,
                    background-color 140ms ease-out, border-color 140ms ease-out !important;
        -webkit-tap-highlight-color: transparent;
        touch-action: manipulation;
    }

    @media (hover: hover) and (pointer: fine) {
        button:not(:disabled):not([disabled]):not([aria-disabled="true"]):hover,
        [role="button"]:not([aria-disabled="true"]):hover,
        [data-baseweb="select"] > div:hover {
            transform: translateY(-1px);
            box-shadow: 0 6px 16px rgba(17, 24, 39, 0.14) !important;
        }
    }

    button:not(:disabled):not([disabled]):not([aria-disabled="true"]):active,
    [role="button"]:not([aria-disabled="true"]):active,
    [data-baseweb="select"] > div:active {
        transform: scale(0.97);
        box-shadow: 0 2px 6px rgba(17, 24, 39, 0.12) !important;
    }

    button:disabled,
    button[disabled],
    [aria-disabled="true"] {
        transform: none !important;
        box-shadow: none !important;
    }

    /* 触屏设备：取消 hover 上浮，避免按压后高亮粘滞 */
    @media (hover: none) {
        button:hover,
        [role="button"]:hover,
        [data-baseweb="select"] > div:hover {
            transform: none;
            box-shadow: none !important;
        }
    }
</style>
""", unsafe_allow_html=True)

# =========================================================
# 语言切换（左侧栏）
# =========================================================
lang_options = ["en", "zh", "ja", "ko", "fr"]
lang_labels = {
    "en": "English",
    "zh": "中文",
    "ja": "日本語",
    "ko": "한국어",
    "fr": "Français",
}

# =========================================================
# 左侧导航（客服三类 + 订单 + 汇率）
# =========================================================
nav_labels = {
    "en": ["AI Agent", "Merchant Support", "Platform Support", "Orders", "Exchange Rate"],
    "zh": ["AI客服", "商家客服", "平台客服", "订单", "汇率"],
    "ja": ["AIエージェント", "販売者サポート", "プラットフォームサポート", "注文", "為替レート"],
    "ko": ["AI Agent", "판매자 고객지원", "플랫폼 고객지원", "주문", "환율"],
    "fr": ["Agent IA", "Support vendeur", "Support plateforme", "Commandes", "Taux de change"],
}

NAV_PAGES = ["ai", "merchant", "platform", "orders", "rate"]
PAGE_ALIAS = {"order_detail": "orders", "product_detail": "orders",
              "logistics": "orders", "merchant_store": "orders", "merchant_chat": "merchant"}

nav_descs = {
    "en": {
        "ai": "Ask about order status, shipping fees and exchange rates.",
        "merchant": "Report damaged or wrong items to the seller.",
        "platform": "Escalate when the merchant does not respond.",
        "orders": "Browse orders, details and product pages.",
        "rate": "Convert currencies with reference rates.",
    },
    "zh": {
        "ai": "订单状态、运费与汇率的智能问答",
        "merchant": "就破损、错发等问题联系商家",
        "platform": "商家不处理时升级到平台介入",
        "orders": "查看订单、订单详情与商品页",
        "rate": "按参考汇率换算货币",
    },
    "ja": {
        "ai": "注文・送料・為替をまとめて相談",
        "merchant": "破損や誤配送を販売者に連絡",
        "platform": "販売者が対応しない場合にエスカレーション",
        "orders": "注文・詳細・商品ページを確認",
        "rate": "参考レートで通貨を換算",
    },
    "ko": {
        "ai": "주문·배송비·환율 상담",
        "merchant": "파손·오배송을 판매자에게 문의",
        "platform": "판매자 미응답 시 플랫폼介入",
        "orders": "주문·상세·상품 페이지 보기",
        "rate": "참고 환율로 통화 환산",
    },
    "fr": {
        "ai": "Commandes, frais de port et taux de change.",
        "merchant": "Signaler un article endommagé ou erroné.",
        "platform": "Escalader si le vendeur ne répond pas.",
        "orders": "Consulter commandes, détails et produits.",
        "rate": "Convertir avec les taux de référence.",
    },
}

with st.sidebar:
    # 兼容旧会话里遗留的未支持语言，避免取文案时 KeyError
    if st.session_state.lang not in lang_options:
        st.session_state.lang = "en"
    st.markdown(
        f"<div style='font-size:1.55rem;font-weight:800;letter-spacing:.5px;color:#000000;"
        f"padding:6px 2px 14px 2px;'>{T[st.session_state.lang]['brand']}</div>",
        unsafe_allow_html=True,
    )
    _active_page = PAGE_ALIAS.get(st.session_state.page, st.session_state.page)
    if _active_page not in NAV_PAGES:
        _active_page = "ai"
    _selected_page = nav_component(
        active_tab=_active_page,
        tabs=NAV_PAGES,
        labels=dict(zip(NAV_PAGES, nav_labels.get(st.session_state.lang, nav_labels["en"]))),
        descriptions=nav_descs.get(st.session_state.lang, nav_descs["en"]),
        default=None,
        key="cg_nav",
    )

    _account_pack = {
        "en": {"manage": "Manage account", "language": "Language", "mode": "Language mode", "logout": "Sign out of this account", "login": "Sign in", "guest": "Not signed in"},
        "zh": {"manage": "管理账号", "language": "语言", "mode": "语言模式", "logout": "退出该账户", "login": "登录该账户", "guest": "未登录"},
        "ja": {"manage": "アカウント管理", "language": "言語", "mode": "言語モード", "logout": "このアカウントからログアウト", "login": "ログイン", "guest": "未ログイン"},
        "ko": {"manage": "계정 관리", "language": "언어", "mode": "언어 모드", "logout": "이 계정에서 로그아웃", "login": "로그인", "guest": "로그인하지 않음"},
        "fr": {"manage": "Gérer le compte", "language": "Langue", "mode": "Mode de langue", "logout": "Se déconnecter de ce compte", "login": "Se connecter", "guest": "Non connecté"},
    }[st.session_state.lang]
    _is_logged_in = st.session_state.get("is_logged_in", True)
    _display_name = "it's me" if _is_logged_in else _account_pack["guest"]
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "cinnamoroll_avatar.jpg"), "rb") as _avatar_file:
        _account_avatar = "data:image/jpeg;base64," + base64.b64encode(_avatar_file.read()).decode()
    if not _is_logged_in:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "ocean_guest_avatar.jpg"), "rb") as _avatar_file:
            _account_avatar = "data:image/jpeg;base64," + base64.b64encode(_avatar_file.read()).decode()
    st.markdown(
        "<style>"
        "[data-testid='stSidebarContent']{padding-bottom:86px !important;}"
        "[data-testid='stSidebar'] .st-key-cg_user_menu{position:fixed;left:30px;bottom:14px;"
        "width:240px;margin:0 !important;padding:0 !important;z-index:20;}"
        "[data-testid='stSidebar'][aria-expanded='false'] .st-key-cg_user_menu{display:none !important;}"
        ".st-key-cg_user_menu [data-testid='stPopover'] > div > button{width:100% !important;"
        "min-height:54px !important;height:54px !important;padding:8px 10px !important;"
        "display:flex !important;align-items:center !important;justify-content:flex-start !important;"
        "gap:10px !important;border:1px solid transparent !important;border-radius:12px !important;"
        "background:transparent !important;color:#111111 !important;"
        "transition:transform 140ms ease-out,box-shadow 140ms ease-out,background-color 140ms ease-out !important;"
        "-webkit-tap-highlight-color:transparent;touch-action:manipulation;}"
        ".st-key-cg_user_menu [data-testid='stPopover'] > div > button::before{content:'';"
        "width:34px;height:34px;flex:0 0 34px;border-radius:10px;border:1px solid #e5e7eb;"
        f"background:url(\"{_account_avatar}\") center/cover no-repeat #ffffff;"
        "box-shadow:0 1px 2px rgba(17,24,39,.06);}"
        ".st-key-cg_user_menu [data-testid='stPopover'] > div > button p{font-size:14px !important;"
        "font-weight:500 !important;color:#111111 !important;margin:0 !important;}"
        ".st-key-cg_user_menu [data-testid='stPopover'] > div > button svg{display:none !important;}"
        "@media(hover:hover) and (pointer:fine){"
        ".st-key-cg_user_menu [data-testid='stPopover'] > div > button:hover{background:#e6e9ee !important;"
        "transform:translateY(-1px);box-shadow:0 4px 12px rgba(17,24,39,.08) !important;}}"
        ".st-key-cg_user_menu [data-testid='stPopover'] > div > button:active{transform:scale(.98);}"
        "@media(hover:none){.st-key-cg_user_menu [data-testid='stPopover'] > div > button:hover{"
        "transform:none;box-shadow:none !important;}}"
        "[data-testid='stPopoverBody']:has(.cg-account-menu-marker){min-width:280px !important;padding:6px !important;}"
        # 无边框列表行（图1风格）：expander 的边框在 details 上，一并去掉
        "[data-testid='stPopoverBody']:has(.cg-account-menu-marker) [data-testid='stExpander'],"
        "[data-testid='stPopoverBody']:has(.cg-account-menu-marker) details{"
        "border:0 !important;background:transparent !important;box-shadow:none !important;}"
        "[data-testid='stPopoverBody']:has(.cg-account-menu-marker) summary{"
        "border-radius:10px;padding:10px 12px !important;}"
        "[data-testid='stPopoverBody']:has(.cg-account-menu-marker) summary:hover{background:#f2f4f7;}"
        # 管理账号行：箭头移到最右，标签居左
        "[data-testid='stPopoverBody']:has(.cg-account-menu-marker) summary > span{"
        "display:flex !important;align-items:center !important;width:100% !important;}"
        "[data-testid='stPopoverBody']:has(.cg-account-menu-marker) summary > span > span{order:2;margin-left:auto;}"
        "[data-testid='stPopoverBody']:has(.cg-account-menu-marker) summary > span > div{order:1;}"
        "[data-testid='stPopoverBody']:has(.cg-account-menu-marker) summary [data-testid='stMarkdownContainer'] p{"
        "display:flex;align-items:center;gap:9px;font-size:14px !important;}"
        "[data-testid='stPopoverBody']:has(.cg-account-menu-marker) summary [data-testid='stMarkdownContainer'] p::before{"
        "content:'';width:18px;height:18px;flex:0 0 18px;background:no-repeat center/contain "
        "url(\"data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23374151' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round'><circle cx='12' cy='8' r='3.4'/><path d='M5 20c1.4-3.6 4-5.2 7-5.2s5.6 1.6 7 5.2'/></svg>\");}"
        # 语言行（selectbox）：label 左、当前语言值右，去输入框边框
        "[data-testid='stPopoverBody']:has(.cg-account-menu-marker) [data-testid='stSelectbox']{"
        "display:flex !important;align-items:center !important;justify-content:space-between !important;"
        "gap:8px;padding:10px 12px;border-radius:10px;}"
        "[data-testid='stPopoverBody']:has(.cg-account-menu-marker) [data-testid='stSelectbox']:hover{background:#f2f4f7;}"
        "[data-testid='stPopoverBody']:has(.cg-account-menu-marker) [data-testid='stSelectbox'] > label{margin:0 !important;}"
        "[data-testid='stPopoverBody']:has(.cg-account-menu-marker) [data-testid='stSelectbox'] > label p{"
        "display:flex;align-items:center;gap:9px;font-size:14px !important;}"
        "[data-testid='stPopoverBody']:has(.cg-account-menu-marker) [data-testid='stSelectbox'] > label p::before{"
        "content:'';width:18px;height:18px;flex:0 0 18px;background:no-repeat center/contain "
        "url(\"data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23374151' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round'><circle cx='12' cy='12' r='8.4'/><path d='M3.6 12h16.8M12 3.6c3.2 3.6 3.2 13.2 0 16.8M12 3.6c-3.2 3.6-3.2 13.2 0 16.8'/></svg>\");}"
        "[data-testid='stPopoverBody']:has(.cg-account-menu-marker) [data-testid='stSelectbox'] .react-aria-ComboBox{flex:0 0 auto;}"
        "[data-testid='stPopoverBody']:has(.cg-account-menu-marker) [data-testid='stSelectbox'] [role='group']{"
        "border:0 !important;background:transparent !important;box-shadow:none !important;"
        "padding:0 !important;min-height:0 !important;gap:4px !important;}"
        "[data-testid='stPopoverBody']:has(.cg-account-menu-marker) [data-testid='stSelectbox'] input{"
        "border:0 !important;background:transparent !important;box-shadow:none !important;"
        "text-align:right;font-size:14px !important;color:#6b7280 !important;padding:0 !important;width:auto !important;flex:0 0 auto !important;}"
        "[data-testid='stPopoverBody']:has(.cg-account-menu-marker) [data-testid='stSelectbox'] input:focus{outline:none !important;}"
        "[data-testid='stPopoverBody']:has(.cg-account-menu-marker) [data-testid='stSelectbox'] [role='group'] button{"
        "display:inline-flex !important;align-items:center !important;justify-content:center !important;"
        "width:20px !important;min-width:20px !important;height:20px !important;"
        "color:#6b7280 !important;padding:0 !important;border:0 !important;background:transparent !important;}"
        "[data-testid='stPopoverBody']:has(.cg-account-menu-marker) [data-testid='stSelectbox'] [role='group'] button svg{display:none !important;}"
        "[data-testid='stPopoverBody']:has(.cg-account-menu-marker) [data-testid='stSelectbox'] [role='group'] button::after{"
        "content:'';width:6px;height:6px;border-top:1.5px solid #6b7280;border-right:1.5px solid #6b7280;"
        "transform:rotate(45deg);margin-left:-2px;}"
        "@media(prefers-reduced-motion:reduce){"
        ".st-key-cg_user_menu [data-testid='stPopover'] > div > button{transition:none !important;}"
        ".st-key-cg_user_menu [data-testid='stPopover'] > div > button:hover,"
        ".st-key-cg_user_menu [data-testid='stPopover'] > div > button:active{transform:none !important;}}"
        "</style>",
        unsafe_allow_html=True,
    )
    with st.container(key="cg_user_menu"):
        with st.popover(_display_name, use_container_width=True):
            st.markdown('<div class="cg-account-menu-marker"></div>', unsafe_allow_html=True)
            with st.expander(_account_pack["manage"], expanded=False):
                st.markdown(
                    "<div style='display:flex;align-items:center;gap:12px;padding:8px 4px 12px;'>"
                    f"<img class='cg-account-avatar' src='{html.escape(_account_avatar, quote=True)}' "
                    f"alt='{html.escape(_display_name, quote=True)}' "
                    "style='width:52px;height:52px;flex:0 0 52px;border-radius:12px;object-fit:cover;"
                    "border:1px solid #e5e7eb;box-shadow:0 1px 2px rgba(17,24,39,.06);'>"
                    "<div style='min-width:0;'>"
                    f"<div style='font-size:14px;font-weight:600;color:#111827;'>{html.escape(_display_name)}</div>"
                    "<div style='font-size:12px;color:#6b7280;margin-top:3px;'>CargoGuard Lite</div>"
                    "</div></div>",
                    unsafe_allow_html=True,
                )
                if st.button(
                    _account_pack["logout"] if _is_logged_in else _account_pack["login"],
                    key="cg_account_auth",
                    use_container_width=True,
                ):
                    st.session_state.is_logged_in = not _is_logged_in
                    st.session_state.page = "ai"
                    st.session_state.page_stack = []
                    st.session_state["last_order_id"] = ""
                    st.rerun()
            st.selectbox(
                _account_pack["language"],
                options=lang_options,
                index=lang_options.index(st.session_state.lang),
                format_func=lambda x: LANG_NAMES[x],
                key="lang",
            )

if isinstance(_selected_page, dict) and _selected_page.get("seq"): 
    # 组件回传的是 {page, seq}，只有新点击（seq 变化）才切页，
    # 避免旧值在 rerun 时把页面强制拉回导航页
    _nav_seq = _selected_page.get("seq")
    _nav_page = _selected_page.get("page")
    if _nav_seq != st.session_state.get("cg_nav_seq"):
        st.session_state["cg_nav_seq"] = _nav_seq
        if _nav_page in NAV_PAGES and _nav_page != _active_page:
            goto(_nav_page)
            # 再跑一轮，让侧栏导航拿到的 active_tab 与当前页一致（一次点击即选中）
            st.rerun()

# 侧栏收起时在左上角显示「>」，点击把导航拉出来
sidebar_toggle_component(key="cg_sidebar_toggle")

# 切页时内容区做一次轻淡入（输入卡片固定定位，需排除，避免被 transform 影响）
if st.session_state.pop("cg_page_fade", False):
    st.markdown(
        "<style>"
        "@keyframes cgPageIn{from{opacity:0;transform:translateY(6px);}"
        "to{opacity:1;transform:none;}}"
        "[data-testid='stMain'] div[data-testid='stElementContainer']{"
        "animation:cgPageIn .26s cubic-bezier(.22,.61,.36,1) both;}"
        "[data-testid='stMain'] div[data-testid='stElementContainer']:has(.st-key-cg_chat_composer){"
        "animation:none !important;}"
        "</style>",
        unsafe_allow_html=True,
    )

# =========================================================
# 页面分发
# =========================================================

# 页面切换不再做整体淡入：Streamlit 重渲染时整块从透明渐现会看起来像“闪一下”，
# 交给导航组件自身的展开动画做过渡即可。

if st.session_state.page == "ai":
    render_header(T[st.session_state.lang]["ai"], show_back=False)
    render_ai_history()
    # 聊天区放在占位符里，便于回答生成后原地逐字刷新
    chat_ph = st.empty()
    _stage_keys = {
        "plan": "stage_searching",
        "retrieve": "stage_searching",
        "answer": "stage_answering",
        "review": "stage_reviewing",
    }

    def _ai_stage_text(pack, node):
        return pack.get(_stage_keys.get(node, ""), pack.get("thinking", "Thinking…"))

    # 预渲染历史消息的绘制器：消息条数变化时才重建，逐字输出时只拼末尾气泡
    _drawer = {"count": -1, "fn": None}

    def _draw_ai_chat(live_status="", live_text=""):
        msgs = st.session_state.ai_messages
        if not any(m["role"] == "user" for m in msgs):
            chat_ph.markdown(empty_state_html(), unsafe_allow_html=True)
            return
        if _drawer["count"] != len(msgs):
            _drawer["fn"] = make_chat_drawer(chat_ph, msgs)
            _drawer["count"] = len(msgs)
        _drawer["fn"](live_status=live_status, live_text=live_text)

    _draw_ai_chat()

    # 审批卡片跟消息一起持久化；只处理当前会话、当前账号对应的 thread。
    _approval_message = next(
        (
            m for m in reversed(st.session_state.ai_messages)
            if m.get("approval")
            and m["approval"].get("session_id") == st.session_state.ai_active
            and m["approval"].get("thread_id") == ai_thread_id()
        ),
        None,
    )
    _approval_pending = bool(
        _approval_message
        and _approval_message["approval"].get("status") in {"pending", "processing"}
    )
    if _approval_message:
        _approval = _approval_message["approval"]
        with st.container(key="cg_chat_composer"):
            _decision = render_approval_card(_approval)
            user_input, send_clicked, attachments = render_chat_composer(
                "ai", disabled=_approval_pending, docked=True
            )
        if _decision:
            _approved, _reviewer, _note = _decision
            _approval.update({
                "status": "processing",
                "reviewer": _reviewer,
                "note": _note,
            })
            try:
                with st.spinner(T[st.session_state.lang]["hitl_processing"]):
                    _resume_result = after_sales_resume(
                        thread_id=_approval["thread_id"],
                        approved=_approved,
                        reviewer=_reviewer,
                        note=_note,
                    )
                if _resume_result.get("needs_approval"):
                    _next_request = _resume_result.get("approval") or {}
                    _approval["request"] = _next_request
                    _approval["thread_id"] = _next_request.get("thread_id") or _approval["thread_id"]
                    _approval["status"] = "pending"
                    _approval_message["content"] = _resume_result.get("answer") or ""
                    _approval_message["sources"] = []
                elif _resume_result.get("error") == "no_pending_action":
                    _approval["status"] = "stale"
                    _approval_message["content"] = T[st.session_state.lang]["hitl_stale_message"]
                    _approval_message["sources"] = []
                else:
                    _hitl = _resume_result.get("hitl") or {}
                    _approval["status"] = _hitl.get("status") or (
                        "approved" if _approved else "rejected"
                    )
                    _approval["summary"] = _hitl.get("summary") or ""
                    if _resume_result.get("network_error"):
                        _reply = T[st.session_state.lang]["network_error"]
                    else:
                        _reply = _resume_result.get("answer") or T[st.session_state.lang]["ai_fallback"]
                    _reply = strip_self_disclaimer(_reply)
                    _source_text = next(
                        (
                            m.get("content", "")
                            for m in reversed(st.session_state.ai_messages)
                            if m.get("role") == "user"
                        ),
                        "",
                    )
                    if _is_problem_report(_source_text):
                        _reply += "\n\n" + T[st.session_state.lang]["disclaimer"]
                    _approval_message["content"] = _reply
                    _approval_message["sources"] = _resume_result.get("sources") or []
                save_ai_sessions()
            except Exception:
                # 不自动重放写操作；恢复 pending 后由用户明确重试。
                _approval["status"] = "pending"
                st.error(T[st.session_state.lang]["hitl_error"])
            else:
                st.rerun()

    else:
        with st.container(key="cg_chat_composer"):
            user_input, send_clicked, attachments = render_chat_composer(
                "ai", disabled=False, docked=True
            )
    if send_clicked and not _approval_pending and (user_input.strip() or attachments):
        lang_pack = T[st.session_state.lang]
        text = user_input.strip()
        is_rate_query = is_exchange_rate_query(text) if text else False
        order_id = resolve_order_id(text, orders) if text else None
        explicit_ref = re.search(r"ORD-\d{3,}", text, flags=re.I) if text else None
        order_ref = explicit_ref.group(0).upper() if explicit_ref else None

        # 附件先做视觉识别：图片→事实摘要，视频明确说明需截帧
        vision_notes = None
        if attachments:
            with st.spinner(lang_pack["analyzing"]):
                vision_notes = describe_attachments(attachments)

        # 文本里没提到订单号时，从图片识别结果里兜底提取（截图含订单号的常见场景）
        if not order_id and vision_notes:
            order_id = resolve_order_id(vision_notes, orders)

        order_obj = find_order_by_id(order_id) if order_id else None
        sources = []
        needs_disclaimer = False
        full_reply = ""
        approval_request = None

        # 先落地用户消息并立即重绘，让买家看到自己的提问
        st.session_state.ai_messages.append(
            {"role": "user", "content": text, "attachments": attachments, "ts": _now_ts()}
        )
        touch_ai_title(text)
        _draw_ai_chat(live_status=lang_pack.get("thinking", "Thinking…"))

        try:
            # 汇率换算是纯计算工具，保留本地确定性实现
            if not attachments and is_rate_query:
                full_reply = get_rate_answer(text)
            # 明确写了订单号但系统里没有：直接说明，不让 Agent 继续推断
            elif not order_obj and order_ref and any(
                k in text.lower()
                for k in ["发货", "物流", "订单", "到哪", "状态", "签收", "ship", "track", "order", "deliver"]
            ):
                full_reply = lang_pack["order_not_found"].format(order_id=order_ref)
            else:
                # 其余全部交给 LangGraph 售后 Agent：
                # 读取长期记忆 → RAG 检索 → 生成回答 → 提取新记忆
                # 用流式接口拿节点进度，实时显示“正在查询/生成/审核”
                result = None
                for kind, *rest in after_sales_chat_stream(
                    user_id=ai_user_id(),
                    message=text or "（买家只上传了附件，没有文字说明）",
                    order_id=order_id or "",
                    thread_id=ai_thread_id(),
                    extra_context=ai_extra_context(order_obj, vision_notes),
                    history=ai_prior_history(),
                    # 游客态（退出登录后 orders 为空）不允许按订单号读取数据库
                    allow_order_lookup=bool(orders and st.session_state.get("is_logged_in", True)),
                    # 回答语言强制与当前界面语言一致
                    reply_language=LANG_NAMES[st.session_state.lang],
                ):
                    if kind == "node":
                        _draw_ai_chat(live_status=_ai_stage_text(lang_pack, rest[0]))
                    elif kind == "final":
                        result = rest[0]
                if result is None:
                    raise RuntimeError("agent stream ended without result")
                if result.get("network_error"):
                    # 断网时模型调用失败：给一句明确提示，而不是长篇知识库摘录
                    full_reply = lang_pack["network_error"]
                else:
                    full_reply = result["answer"] or lang_pack["ai_fallback"]
                    # 简单状态/进度查询不加免责声明；报告问题或申请行动时才追加
                    # 待人工确认的系统提示不是维权建议，也不加免责声明
                    needs_disclaimer = _is_problem_report(text) and not result.get("needs_approval")
                    sources = result.get("sources") or []
                    if result.get("needs_approval"):
                        approval_request = result.get("approval") or {}

            # 免责提示只在维权类回复末尾追加，简单订单/汇率查询不加
            full_reply = strip_self_disclaimer(full_reply)
            if needs_disclaimer:
                full_reply += "\n\n" + lang_pack["disclaimer"]

            # 逐字输出：每帧多显示几个字符，避免整段突然出现
            for end in range(8, len(full_reply) + 8, 8):
                _draw_ai_chat(live_text=full_reply[:end])
                time.sleep(0.02)
        except Exception:
            full_reply = lang_pack["ai_fallback"]
            sources = []
            approval_request = None
        finally:
            _ai_message = {
                "role": "ai",
                "content": full_reply or lang_pack["ai_fallback"],
                "sources": sources,
                "ts": _now_ts(),
            }
            if approval_request:
                _ai_message["approval"] = {
                    "id": f"{st.session_state.ai_active}:{time.time_ns()}",
                    "session_id": st.session_state.ai_active,
                    "thread_id": approval_request.get("thread_id") or ai_thread_id(),
                    "request": approval_request,
                    "status": "pending",
                }
            st.session_state.ai_messages.append(_ai_message)
            save_ai_sessions()
            clear_composer_attachments("ai")
            st.rerun()

elif st.session_state.page == "merchant":
    lang_pack = T[st.session_state.lang]
    lang_code = st.session_state.lang

    # 紧凑查询面板：搜索 / 日期区间 / 三标签表格，View Detail 进入商家客服
    _payload = [
        {
            "id": o.get("order_id") or "",
            "merchant": o.get("merchant") or "",
            "product": o.get("product_name") or "",
            "time": fmt_datetime(o.get("order_time"), lang_code),
            "amount": f"{o.get('currency', 'USD')} {float(o.get('total_price', 0)):.2f}",
            "status": localize_status(o.get("status", ""), lang_code),
        }
        for o in orders
    ]
    # 左侧留白清零，让查询面板整体左移、铺满宽度，表格右侧不再被裁掉
    st.markdown(
        "<style>"
        "[data-testid='stMain'] .block-container,"
        "[data-testid='stMainBlockContainer'],"
        "[data-testid='stAppViewBlockContainer']{padding-left:8px !important;"
        "padding-right:8px !important;max-width:none !important;}"
        "</style>",
        unsafe_allow_html=True,
    )
    _picked = order_list_component(
        orders=_payload,
        action_label=lang_pack["view_detail"],
        key="cg_merchants",
        default=None,
        height=560,
    )
    if isinstance(_picked, dict):
        _seq = _picked.get("seq")
        _oid = _picked.get("order_id")
        if _oid and _seq and st.session_state.get("cg_merchants_seq") != _seq:
            st.session_state["cg_merchants_seq"] = _seq
            _m = next(
                (o.get("merchant") for o in orders if o.get("order_id") == _oid), None
            )
            if _m:
                st.session_state.selected_merchant = _m
                goto("merchant_chat")
                st.rerun()


elif st.session_state.page == "merchant_chat":
    lang_pack = T[st.session_state.lang]
    merchant = st.session_state.selected_merchant
    st.session_state.merchant_messages.setdefault(merchant, [dict(PRESET_MESSAGES["merchant_default"])])
    render_header(merchant, show_back=True)
    render_back_button("merchant_chat")
    # 返回键旁边显示当前商家的头像与店名，明确是从哪个店铺进来的
    _merchant_order = next(
        (o for o in orders if o.get("merchant") == merchant), None
    )
    _avatar = (
        _merchant_avatar_html(_merchant_order, 30)
        if _merchant_order
        else _merchant_avatar_html({"merchant": merchant}, 30)
    )
    st.markdown(_identity_row(merchant, _avatar), unsafe_allow_html=True)

    # 已注销商家：不渲染会话与输入框，只提示账户已注销
    if merchant in CLOSED_MERCHANTS:
        st.markdown(
            "<div style='margin-top:26px;text-align:center;'>"
            "<div style='font-size:1.05rem;font-weight:700;color:#c0392b;'>"
            + html.escape(ux("account_closed"))
            + "</div>"
            "<div style='margin-top:10px;font-size:0.82rem;line-height:1.75;"
            "color:#8f8f8f;'>" + html.escape(ux("account_closed_note")) + "</div></div>",
            unsafe_allow_html=True,
        )
        st.stop()

    render_chat_panel(
        merchant,
        st.session_state.merchant_messages[merchant],
        show_read=True,
        translate=True,
        boxed=False,
    )

    merchant_input, send_clicked, attachments = render_chat_composer("merchant")
    if send_clicked and (merchant_input.strip() or attachments):
        msgs = st.session_state.merchant_messages[merchant]
        msgs.append({
            "role": "user",
            "content": merchant_input.strip(),
            "attachments": attachments,
            # 已读/未读在消息创建时随机定下并随消息保存，rerun 不再变化
            "read": random.choice([True, False]),
            "ts": _now_ts(),
        })
        msgs.append(ack_message("merchant_ack", merchant=merchant))
        clear_composer_attachments("merchant")
        st.rerun()

elif st.session_state.page == "platform":
    lang_pack = T[st.session_state.lang]
    render_header(lang_pack["platform"], show_back=True)
    render_back_button("platform")
    st.markdown(
        _identity_row(
            lang_pack["platform"],
            _merchant_avatar_html({"merchant": lang_pack["platform"]}, 30),
        ),
        unsafe_allow_html=True,
    )
    render_chat_panel(lang_pack["platform"], st.session_state.platform_messages, show_read=True, translate=True, boxed=False)

    platform_input, send_clicked, attachments = render_chat_composer("platform")
    if send_clicked and (platform_input.strip() or attachments):
        st.session_state.platform_messages.append({
            "role": "user",
            "content": platform_input.strip(),
            "attachments": attachments,
            "read": random.choice([True, False]),
            "ts": _now_ts(),
        })
        st.session_state.platform_messages.append(ack_message("platform_ack"))
        clear_composer_attachments("platform")
        st.rerun()

elif st.session_state.page == "orders":
    render_header(T[st.session_state.lang]["orders"], show_back=True)
    # 左侧留白清零，返回键贴左边界，订单卡片也铺满宽度
    st.markdown(
        "<style>"
        "[data-testid='stMain'] .block-container,"
        "[data-testid='stMainBlockContainer'],"
        "[data-testid='stAppViewBlockContainer']{padding-left:8px !important;"
        "padding-right:8px !important;max-width:none !important;}"
        "</style>",
        unsafe_allow_html=True,
    )

    _picked = order_views_component(
        orders=order_views_payload(orders),
        focus=st.session_state.get("last_order_id") or "",
        empty_label=T[st.session_state.lang]["no_orders"],
        key="cg_order_views",
        default=None,
        height=620,
    )
    # 焦点只消费一次，避免后续 rerun 反复滚动
    st.session_state["last_order_id"] = ""
    if isinstance(_picked, dict) and _picked.get("seq"):
        if _picked["seq"] != st.session_state.get("cg_order_views_seq"):
            st.session_state["cg_order_views_seq"] = _picked["seq"]
            _oid = _picked.get("order_id") or ""
            _action = _picked.get("action")
            if _action == "detail" and _oid:
                st.session_state.order_detail_id = _oid
                st.session_state["last_order_id"] = _oid
                goto("order_detail")
                st.rerun()
            elif _action == "product" and _oid:
                st.session_state.product_detail_id = _oid
                st.session_state["last_order_id"] = _oid
                goto("product_detail")
                st.rerun()

elif st.session_state.page == "order_detail":
    render_header(ux("order_detail"), show_back=True)
    st.markdown(
        "<style>"
        "[data-testid='stMain'] .block-container,[data-testid='stMainBlockContainer'],"
        "[data-testid='stAppViewBlockContainer']{padding:0 8px 6px !important;"
        "max-width:none !important;}"
        "[data-testid='stHeader'],[data-testid='stToolbar'],[data-testid='stDecoration']"
        "{display:none !important;height:0 !important;}"
        "[data-testid='stMainBlockContainer'] [data-testid='stVerticalBlock']{gap:0.35rem !important;}"
        "[data-testid='stMain'] .element-container{margin:0 !important;}"
        "[data-testid='stCustomComponentV1'],iframe{margin-top:0 !important;}"
        "</style>",
        unsafe_allow_html=True,
    )
    order = find_order_by_id(st.session_state.get("order_detail_id") or "")
    if order:
        render_order_detail(order)
    else:
        st.info(T[st.session_state.lang]["no_orders"])

elif st.session_state.page == "product_detail":
    render_header(ux("product_detail"), show_back=True)
    render_back_button("product_detail")
    st.markdown(
        "<style>"
        "[data-testid='stMain'] .block-container,[data-testid='stMainBlockContainer'],"
        "[data-testid='stAppViewBlockContainer']{padding-top:0 !important;"
        "padding-left:8px !important;padding-right:8px !important;max-width:none !important;}"
        "[data-testid='stHeader'],[data-testid='stToolbar'],[data-testid='stDecoration']"
        "{display:none !important;height:0 !important;}"
        # 返回箭头与左侧侧栏折叠按钮顶部对齐
        "[data-testid='stMain'] [data-testid='stElementContainer']:has(iframe[title*='back_arrow'])"
        "{margin-top:-26px !important;margin-left:2px !important;}"
        "</style>",
        unsafe_allow_html=True,
    )
    order = find_order_by_id(st.session_state.get("product_detail_id") or "")
    if order:
        render_product_detail(order)
    else:
        st.info(T[st.session_state.lang]["no_orders"])

elif st.session_state.page == "logistics":
    render_header(LOG_T[st.session_state.lang]["title"], show_back=True)
    render_back_button("logistics")
    st.markdown(
        "<style>"
        "[data-testid='stMain'] .block-container,[data-testid='stMainBlockContainer'],"
        "[data-testid='stAppViewBlockContainer']{padding-top:0 !important;"
        "padding-left:8px !important;padding-right:8px !important;max-width:none !important;}"
        "[data-testid='stHeader'],[data-testid='stToolbar'],[data-testid='stDecoration']"
        "{display:none !important;height:0 !important;}"
        # 返回箭头与左侧侧栏折叠按钮顶部对齐
        "[data-testid='stMain'] [data-testid='stElementContainer']:has(iframe[title*='back_arrow'])"
        "{margin-top:-26px !important;margin-left:2px !important;}"
        "</style>",
        unsafe_allow_html=True,
    )
    order = find_order_by_id(st.session_state.get("logistics_order_id") or "")
    if order:
        render_logistics(order)
    else:
        st.info(T[st.session_state.lang]["no_orders"])

elif st.session_state.page == "merchant_store":
    render_header(st.session_state.get("merchant_store_name") or "", show_back=True)
    render_back_button("merchant_store")
    st.markdown(
        "<style>"
        "[data-testid='stMain'] .block-container,[data-testid='stMainBlockContainer'],"
        "[data-testid='stAppViewBlockContainer']{padding-top:0 !important;"
        "padding-left:8px !important;padding-right:8px !important;"
        "max-width:880px !important;margin:0 !important;}"
        "[data-testid='stHeader'],[data-testid='stToolbar'],[data-testid='stDecoration']"
        "{display:none !important;height:0 !important;}"
        # 返回箭头固定在主内容区左上角（与订单详情页同一坐标，不随内容区居中偏移）
        "[data-testid='stMain']{position:relative !important;}"
        "[data-testid='stMain'] [data-testid='stElementContainer']:has(iframe[title*='back_arrow'])"
        "{position:absolute !important;top:48px !important;left:10px !important;"
        "z-index:30 !important;margin:0 !important;}"
        "</style>",
        unsafe_allow_html=True,
    )
    merchant = st.session_state.get("merchant_store_name") or ""
    if merchant:
        render_merchant_store(merchant)
    else:
        st.info(T[st.session_state.lang]["no_orders"])

elif st.session_state.page == "rate":
    render_header(T[st.session_state.lang]["rate"], show_back=True)

    # 下拉框与金额输入框：整个框灰色底、文字黑色；展开的选项列表保持白色
    # 仅作用于主内容区，避免影响侧栏顶部的语言选择框
    st.markdown(
        "<style>"
        '[data-testid="stMain"] [data-testid="stSelectbox"] > div:last-child,'
        '[data-testid="stMain"] [data-testid="stNumberInput"] > div:last-child{'
        "background-color:#f2f4f7 !important;border-radius:10px !important;}"
        '[data-testid="stMain"] [data-testid="stSelectbox"] > div:last-child *,'
        '[data-testid="stMain"] [data-testid="stNumberInput"] > div:last-child *{'
        "background-color:transparent !important;color:#000000 !important;}"
        '[data-testid="stMain"] [data-testid="stSelectbox"] > div:last-child svg,'
        '[data-testid="stMain"] [data-testid="stNumberInput"] > div:last-child svg{'
        "color:#000000 !important;fill:#000000 !important;}"
        'ul[role="listbox"],div[role="listbox"],li[role="option"],'
        'ul[role="listbox"] li,div[role="listbox"] li{'
        "background-color:#ffffff !important;color:#000000 !important;}"
        'li[role="option"]:hover,li[aria-selected="true"]{'
        "background-color:#f2f4f7 !important;}"
        "</style>",
        unsafe_allow_html=True,
    )

    from_currency = st.selectbox(T[st.session_state.lang]["from"], options=list(CURRENCY_LABELS.keys()), index=0, key="rate_from")
    to_currency = st.selectbox(T[st.session_state.lang]["to"], options=list(CURRENCY_LABELS.keys()), index=3, key="rate_to")
    amount = st.number_input(T[st.session_state.lang]["amount"], min_value=0.0, value=1.0, step=0.01, format="%.2f", key="rate_amount")

    if from_currency == to_currency:
        converted = amount
        ratio = 1.0
    else:
        ratio = EXCHANGE_RATES[to_currency] / EXCHANGE_RATES[from_currency]
        converted = amount * ratio

    st.markdown(
        textwrap.dedent(f"""
        <div class="info-box">
            <div style="font-weight:800; margin-bottom:12px;">{T[st.session_state.lang]['result']}</div>
            <div class="info-row">
                <span style="color:#000000;">{T[st.session_state.lang]['exchange_rate']}</span>
                <strong>1 {from_currency} = {ratio:.4f} {to_currency}</strong>
            </div>
            <div class="info-row">
                <span style="color:#000000;">{T[st.session_state.lang]['converted_amount']}</span>
                <strong>{amount:.2f} {from_currency} = {converted:.2f} {to_currency}</strong>
            </div>
            <div class="info-row">
                <span style="color:#000000;">{T[st.session_state.lang]['currency_name']}</span>
                <strong>{CURRENCY_LABELS[from_currency]} → {CURRENCY_LABELS[to_currency]}</strong>
            </div>
        </div>
        """),
        unsafe_allow_html=True
    )