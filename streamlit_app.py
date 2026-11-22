import re
import os
import json
import random
import html
import base64
import textwrap
from datetime import datetime, timedelta
import streamlit as st

import streamlit.components.v1 as components

from app.llm import describe_attachments, has_llm, cargoguard_answer

st.set_page_config(page_title="CargoGuard", layout="wide")


# 左侧导航（自定义组件，支持与 Python 双向通信）
@st.cache_resource
def _nav_component():
    _dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "components", "nav_panel"
    )
    return components.declare_component("cargoguard_nav", path=_dir)


nav_component = _nav_component()


# 订单查询面板（自定义组件：表格内点击 View Detail 可回传订单号）
@st.cache_resource
def _order_list_component():
    _dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "components", "order_inquiry"
    )
    return components.declare_component("cargoguard_orders", path=_dir)


order_list_component = _order_list_component()


# 聊天页自适应：用组件测量真实高度，把对话区撑到输入框正上方
@st.cache_resource
def _fit_chat_component():
    _dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "components", "fit_chat"
    )
    return components.declare_component("cargoguard_fit_chat", path=_dir)


fit_chat_component = _fit_chat_component()


# 订单卡片列表（自定义组件：点卡片进订单详情，点联系商家进客服）
@st.cache_resource
def _order_views_component():
    _dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "components", "order_views"
    )
    return components.declare_component("cargoguard_order_views", path=_dir)


order_views_component = _order_views_component()


# 返回箭头（自定义组件：纯灰色 chevron，不受 Streamlit 主题影响）
@st.cache_resource
def _back_arrow_component():
    _dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "components", "back_arrow"
    )
    return components.declare_component("cargoguard_back_arrow", path=_dir)


back_arrow_component = _back_arrow_component()


@st.cache_resource
def _order_detail_component():
    _dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "components", "order_detail"
    )
    return components.declare_component("cargoguard_order_detail", path=_dir)


order_detail_component = _order_detail_component()


# 商家评价：原文展示 + 点击展开当前语言翻译
@st.cache_resource
def _merchant_reviews_component():
    _dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "components", "merchant_reviews"
    )
    return components.declare_component("cargoguard_merchant_reviews", path=_dir)


merchant_reviews_component = _merchant_reviews_component()


# 侧栏收起时的「>」拉出按钮（在父页面里创建，因此能同步侧栏开合状态）
@st.cache_resource
def _sidebar_toggle_component():
    _dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "components", "sidebar_toggle"
    )
    return components.declare_component("cargoguard_sidebar_toggle", path=_dir)


sidebar_toggle_component = _sidebar_toggle_component()


# 历史记录列表（自定义组件：悬停变灰 + 「···」菜单：删除 / 重命名 / 顶置）
@st.cache_resource
def _ai_history_component():
    _dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "components", "ai_history"
    )
    return components.declare_component("cargoguard_ai_history", path=_dir)


ai_history_component = _ai_history_component()

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

# =========================================================
# 语言包
# =========================================================
T = {
    "en": {
        "brand": "CargoGuard",
        "ai": "AI Agent",
        "merchant": "Merchant Support",
        "platform": "Platform Support",
        "orders": "Orders",
        "rate": "Exchange Rate",
        "send": "Send",
        "search_merchant": "Search merchant, order ID, product or order date",
        "placeholder": "Please enter text",
        "status_online": "Online",
        "order_id": "Order ID",
        "unit_price": "Unit price",
        "total_price": "Total price",
        "qty": "Quantity",
        "from": "From",
        "to": "To",
        "amount": "Amount",
        "result": "Exchange result",
        "exchange_rate": "Exchange rate",
        "converted_amount": "Converted amount",
        "currency_name": "Currency name",
        "ai_fallback": "I can help with order status, shipping fees, exchange rates, refunds, or damaged/wrong items. For example, try \"1 USD to KRW\" or \"Where is order ORD-1004?\"",
        "order_not_found": "I could not find order {order_id}. Please check the order ID and try again.",
        "order_hint": " (To check a specific order, tell me the order ID, e.g. ORD-1004.)",
        "attachment_ack": "I received your {n} attachment(s). How can I help with them?",
        "escalate_merchant": "This sounds like a receiving issue (damaged or wrong item). Please contact **merchant support** first — describe what happened when you received the goods, and you can request an exchange, reshipment, or refund.",
        "escalate_platform": "This is a case of the merchant failing to fulfil their obligations (refusing or delaying a refund, poor attitude, or no reply). I recommend escalating to **platform support**, which can intervene and follow up.",
        "escalate_platform_materials": "Please prepare the order ID, refund application records, and screenshots of your chat with the merchant as escalation evidence.",
        "escalate_order_context": "Order context: {order_id} is currently {status}, {refund}.",
        "refund_in_progress": "with a refund/return in progress",
        "refund_done": "with the refund/return already completed",
        "refund_none_now": "with no refund process in progress",
        "order_not_found_bare": "No matching order found. Please provide the full order ID (e.g. ORD-1004).",
        "status_ship_no": "{order_id} has not been shipped yet.",
        "status_ship_yes": "{order_id} has been shipped (current status: {status}).",
        "status_ship_after": "{order_id} is currently {status} and has entered the after-sales process.",
        "status_refund_active": "{order_id} current status: {status}.",
        "status_refund_none": "{order_id} is currently {status}, with no refund process in progress.",
        "status_logistics": "{order_id} · {status}. Shipping: {shipping_status}. {logistics_info}. Tracking: {tracking}.",
        "order_time": "Order time",
        "merchant_label": "Merchant",
        "product_label": "Product",
        "read": "Read",
        "unread": "Unread",
        "timeline_title": "Status timeline",
        "no_orders": "No orders yet.",
        "no_merchants": "No merchant or order matched.",
        "attach_caption": "Images (png/jpg/jpeg/gif/webp) and videos (mp4/mov/webm), max {mb}MB each",
        "attach_too_big": "\"{name}\" exceeds {mb}MB and was skipped.",
        "merchant_ack": "Message received. {merchant} support will handle it shortly.",
        "platform_ack": "Feedback received. Platform support will follow up.",
        "status_no_tracking": "none",
        "node_created": "Order placed",
        "translated": "Translation: ",
        "no_translation": "No translation available",
        "analyzing": "Reading your attachments…",
        "history": "History",
        "new_chat": "New chat",
        "untitled": "Untitled",
        "today": "Today",
        "yesterday": "Yesterday",
        "history_empty": "No history yet",
        "delete": "Delete",
        "rename": "Rename",
        "pin": "Pin to top",
        "unpin": "Unpin",
        "pinned": "Pinned",
        "disclaimer": "Disclaimer: This content is for reference only and cannot guarantee any outcome. All communication and submissions must be done by you, in compliance with platform rules and local law.",
        "rate_answer": "Current reference rate: 1 {from} = {ratio:.4f} {to}. Therefore, {amount:.2f} {from} = {converted:.2f} {to}.",
        "emoji_smile": "Smileys",
        "emoji_gesture": "Gestures",
        "emoji_item": "Objects",
        "emoji_mood": "Moods",
        "default_ai": "Hello, I am CargoGuard, your AI buyer-rights advisor. You can ask about order status, shipping fees and exchange rates, or report after-sales issues such as damaged or wrong items. I will provide compliant, reference-only guidance to protect your rights as a buyer and help you get a better cross-border shopping experience.",
        "merchant_default": "Hello, I am merchant support. Welcome to contact us.",
        "platform_default": "Hello, I am platform support. If the merchant does not respond or the issue is not resolved, I can help escalate.",
    },
    "zh": {
        "brand": "CargoGuard",
        "ai": "AI 客服",
        "merchant": "商家客服",
        "platform": "平台客服",
        "orders": "订单",
        "rate": "汇率",
        "send": "发送",
        "search_merchant": "搜索商家名称、订单编号、商品名称或下单时间",
        "placeholder": "请输入文本",
        "status_online": "在线",
        "order_id": "订单编号",
        "unit_price": "单价",
        "total_price": "总价",
        "qty": "数量",
        "from": "从",
        "to": "到",
        "amount": "金额",
        "result": "汇率结果",
        "exchange_rate": "兑换比率",
        "converted_amount": "换算金额",
        "currency_name": "货币名称",
        "ai_fallback": "我可以帮你查询订单状态、运费、汇率换算，也可以处理退款、商品损坏或发错货等问题。比如试试「1美元等于多少韩币」或「ORD-1004 到哪了」。",
        "order_not_found": "没有找到订单 {order_id}，请检查订单编号是否正确。",
        "order_hint": "（如需查询具体订单，请告诉我订单编号，如 ORD-1004。）",
        "attachment_ack": "已收到您发送的 {n} 个附件，请告诉我需要怎么处理。",
        "escalate_merchant": "这看起来是收货问题（商品损坏或发错货）。建议先联系**商家客服**处理——说明收货时的情况，可以要求换货、补发或退款。",
        "escalate_platform": "这类情况属于商家未履行义务（拒绝或拖延退款、态度差、不回复等），建议升级到**平台客服**介入处理，平台可以协调并督办。",
        "escalate_platform_materials": "请准备好订单号、退款申请记录、与商家的聊天记录截图，作为升级凭证。",
        "escalate_order_context": "订单背景：{order_id} 当前{status}，{refund}。",
        "refund_in_progress": "退款/退货流程进行中",
        "refund_done": "退款/退货已完成",
        "refund_none_now": "没有进行中的退款流程",
        "order_not_found_bare": "没有找到匹配的订单，请提供完整订单号（如 ORD-1004）。",
        "status_ship_no": "{order_id} 未发货。",
        "status_ship_yes": "{order_id} 已发货（当前状态：{status}）。",
        "status_ship_after": "{order_id} 当前状态为{status}，已进入售后流程。",
        "status_refund_active": "{order_id} 当前状态：{status}。",
        "status_refund_none": "{order_id} 当前状态为{status}，暂无退款流程。",
        "status_logistics": "{order_id} · {status}。物流：{shipping_status}，{logistics_info}。物流单号：{tracking}。",
        "order_time": "下单时间",
        "merchant_label": "商家",
        "product_label": "商品",
        "read": "已读",
        "unread": "未读",
        "timeline_title": "状态时间线",
        "no_orders": "暂无订单。",
        "no_merchants": "没有匹配的商家或订单。",
        "attach_caption": "支持图片（png/jpg/jpeg/gif/webp）和视频（mp4/mov/webm），单个文件 ≤ {mb}MB",
        "attach_too_big": "「{name}」超过 {mb}MB 上限，已跳过。",
        "merchant_ack": "已收到您的消息，{merchant} 客服将尽快为您处理。",
        "platform_ack": "已收到您的反馈，平台客服会进一步协调并处理。",
        "status_no_tracking": "暂无",
        "node_created": "下单成功",
        "translated": "译：",
        "no_translation": "暂无翻译",
        "analyzing": "正在读取附件…",
        "history": "历史记录",
        "new_chat": "新对话",
        "untitled": "未命名",
        "today": "今天",
        "yesterday": "昨天",
        "history_empty": "暂无历史记录",
        "delete": "删除",
        "rename": "重命名",
        "pin": "顶置",
        "unpin": "取消顶置",
        "pinned": "置顶",
        "disclaimer": "免责提示：本内容仅为维权参考建议，无法保证维权结果，所有沟通、提交操作请由您本人完成，请遵守平台规则与当地相关法律。",
        "rate_answer": "当前参考汇率：1 {from} = {ratio:.4f} {to}，所以 {amount:.2f} {from} ≈ {converted:.2f} {to}。",
        "emoji_smile": "笑脸",
        "emoji_gesture": "手势",
        "emoji_item": "物品",
        "emoji_mood": "心情",
        "default_ai": "您好，我是 CargoGuard AI 维权参谋。您可以咨询订单状态、运费、汇率，也可以反馈商品损坏、发错货等售后问题。我会为您提供合规的维权参考方案，维护您的买家权益，帮您获得更好的跨境购物体验。",
        "merchant_default": "您好，我是商家客服，欢迎咨询订单情况。",
        "platform_default": "您好，我是平台客服。若商家沟通不佳、商品损坏或发错货未及时处理，我可以帮助您升级处理。",
    },
    "ja": {
        "brand": "CargoGuard",
        "ai": "AIエージェント",
        "merchant": "販売者サポート",
        "platform": "プラットフォームサポート",
        "orders": "注文",
        "rate": "為替レート",
        "send": "送信",
        "search_merchant": "販売者名・注文番号・商品名・注文日時で検索",
        "placeholder": "テキストを入力",
        "status_online": "オンライン",
        "order_id": "注文番号",
        "unit_price": "単価",
        "total_price": "合計金額",
        "qty": "数量",
        "from": "元の通貨",
        "to": "変換先",
        "amount": "金額",
        "result": "換算結果",
        "exchange_rate": "為替レート",
        "converted_amount": "換算後金額",
        "currency_name": "通貨名",
        "ai_fallback": "注文状況、送料、為替換算、返金、商品破損や誤配送についてお手伝いできます。例：「1ドルは何ウォン？」や「ORD-1004 はどこ？」と聞いてみてください。",
        "order_not_found": "注文 {order_id} が見つかりません。注文番号をご確認ください。",
        "order_hint": "（特定の注文を調べるには、ORD-1004 のような注文番号を教えてください。）",
        "attachment_ack": "添付ファイルを {n} 件受け取りました。どのように対応しましょうか？",
        "escalate_merchant": "商品の破損や誤配送など、受け取り時の問題のようです。まず**販売者サポート**に連絡し、受け取り時の状況を説明して、交換・再送・返金を依頼してください。",
        "escalate_platform": "販売者が義務を果たしていないケース（返金の拒否・遅延、横柄な対応、無返答など）です。**プラットフォームサポート**へのエスカレーションをお勧めします。プラットフォームが介入し督励します。",
        "escalate_platform_materials": "注文番号、返金申請の記録、販売者とのチャット記録のスクリーンショットを証拠としてご用意ください。",
        "escalate_order_context": "注文情報：{order_id} は現在 {status}、{refund}。",
        "refund_in_progress": "返金/返品手続きが進行中です",
        "refund_done": "返金/返品は完了しています",
        "refund_none_now": "進行中の返金手続きはありません",
        "order_not_found_bare": "一致する注文が見つかりません。完全な注文番号（ORD-1004 など）を入力してください。",
        "status_ship_no": "{order_id} はまだ発送されていません。",
        "status_ship_yes": "{order_id} は発送済みです（現在の状態：{status}）。",
        "status_ship_after": "{order_id} は現在 {status} で、アフターサービス手続きに入っています。",
        "status_refund_active": "{order_id} の現在の状態：{status}。",
        "status_refund_none": "{order_id} は現在 {status} で、返金手続きは行われていません。",
        "status_logistics": "{order_id} · {status}。配送状況：{shipping_status}。{logistics_info}。追跡番号：{tracking}。",
        "order_time": "注文日時",
        "merchant_label": "販売者",
        "product_label": "商品",
        "read": "既読",
        "unread": "未読",
        "timeline_title": "ステータス履歴",
        "no_orders": "注文はまだありません。",
        "no_merchants": "該当する販売者または注文がありません。",
        "attach_caption": "画像（png/jpg/jpeg/gif/webp）と動画（mp4/mov/webm）、1ファイル {mb}MB まで",
        "attach_too_big": "「{name}」は {mb}MB を超えるためスキップしました。",
        "merchant_ack": "メッセージを受け取りました。{merchant} サポートが対応します。",
        "platform_ack": "フィードバックを受け取りました。プラットフォームサポートが引き続き対応します。",
        "status_no_tracking": "なし",
        "node_created": "注文作成",
        "translated": "訳：",
        "no_translation": "翻訳はありません",
        "analyzing": "添付ファイルを解析中…",
        "history": "履歴",
        "new_chat": "新しい会話",
        "untitled": "無題",
        "today": "今日",
        "yesterday": "昨日",
        "history_empty": "履歴はまだありません",
        "delete": "削除",
        "rename": "名前を変更",
        "pin": "上部に固定",
        "unpin": "固定を解除",
        "pinned": "固定済み",
        "disclaimer": "免責事項：本内容は参考情報であり、結果を保証するものではありません。すべての連絡・申請はご本人がプラットフォーム規約および現地法に従って行ってください。",
        "rate_answer": "現在の参考レート：1 {from} = {ratio:.4f} {to}。したがって {amount:.2f} {from} = {converted:.2f} {to}。",
        "emoji_smile": "笑顔",
        "emoji_gesture": "ジェスチャー",
        "emoji_item": "アイテム",
        "emoji_mood": "気持ち",
        "default_ai": "こんにちは、CargoGuard AI バイヤー権利アドバイザーです。注文状況・送料・為替レートのほか、商品の破損や誤配送などのアフターサービスについてもご相談いただけます。バイヤーの権利を守るため、コンプライアンスに沿った参考方案をご提案し、より良い越境ショッピング体験をお手伝いします。",
        "merchant_default": "こんにちは、販売者サポートです。注文に関するご相談をどうぞ。",
        "platform_default": "こんにちは、プラットフォームサポートです。販売者との連絡が不十分な場合や解決できない場合はサポートを上げます。",
    },
    "ko": {
        "brand": "CargoGuard",
        "ai": "AI Agent",
        "merchant": "판매자 고객지원",
        "platform": "플랫폼 고객지원",
        "orders": "주문",
        "rate": "환율",
        "send": "전송",
        "search_merchant": "판매자명, 주문번호, 상품명, 주문 시간으로 검색",
        "placeholder": "텍스트 입력",
        "status_online": "온라인",
        "order_id": "주문 번호",
        "unit_price": "단가",
        "total_price": "총액",
        "qty": "수량",
        "from": "출발 통화",
        "to": "도착 통화",
        "amount": "금액",
        "result": "환산 결과",
        "exchange_rate": "환율",
        "converted_amount": "환산 금액",
        "currency_name": "통화명",
        "ai_fallback": "주문 상태, 배송비, 환율 계산, 환불, 상품 손상/오배송 문제를 도와드릴 수 있습니다. 예: 「1달러는 몇 원?」 또는 「ORD-1004 어디 있어?」라고 물어보세요.",
        "order_not_found": "주문 {order_id}을(를) 찾을 수 없습니다. 주문 번호를 확인해 주세요.",
        "order_hint": "（특정 주문을 확인하려면 ORD-1004 같은 주문 번호를 알려주세요.）",
        "attachment_ack": "첨부 파일 {n}개를 받았습니다. 어떻게 도와드릴까요?",
        "escalate_merchant": "상품 파손이나 오배송 등 수령 문제로 보입니다. 먼저 **판매자 고객지원**에 연락하여 수령 당시 상황을 설명하고 교환·재발송·환불을 요청하세요.",
        "escalate_platform": "판매자가 의무를 이행하지 않은 사례(환불 거부·지연, 불친절, 무응답 등)입니다. **플랫폼 고객지원**으로 에스컬레이션하는 것을 권장합니다. 플랫폼이 중재하고 독려합니다.",
        "escalate_platform_materials": "주문 번호, 환불 신청 기록, 판매자와의 채팅 기록 스크린샷을 증거로 준비해 주세요.",
        "escalate_order_context": "주문 정보: {order_id}은(는) 현재 {status}, {refund}.",
        "refund_in_progress": "환불/반품 절차가 진행 중입니다",
        "refund_done": "환불/반품이 완료되었습니다",
        "refund_none_now": "진행 중인 환불 절차가 없습니다",
        "order_not_found_bare": "일치하는 주문을 찾을 수 없습니다. 전체 주문 번호(예: ORD-1004)를 입력해 주세요.",
        "status_ship_no": "{order_id}은(는) 아직 발송되지 않았습니다.",
        "status_ship_yes": "{order_id}은(는) 발송되었습니다(현재 상태: {status}).",
        "status_ship_after": "{order_id}은(는) 현재 {status}이며 A/S 절차가 진행 중입니다.",
        "status_refund_active": "{order_id} 현재 상태: {status}.",
        "status_refund_none": "{order_id}은(는) 현재 {status}이며 환불 절차가 진행 중이 아닙니다.",
        "status_logistics": "{order_id} · {status}. 배송 상황: {shipping_status}. {logistics_info}. 추적 번호: {tracking}.",
        "order_time": "주문 시간",
        "merchant_label": "판매자",
        "product_label": "상품",
        "read": "읽음",
        "unread": "읽지 않음",
        "timeline_title": "상태 타임라인",
        "no_orders": "주문이 없습니다.",
        "no_merchants": "일치하는 판매자나 주문이 없습니다.",
        "attach_caption": "이미지(png/jpg/jpeg/gif/webp)와 영상(mp4/mov/webm), 파일당 최대 {mb}MB",
        "attach_too_big": "\"{name}\"은(는) {mb}MB를 초과하여 건너뛰었습니다.",
        "merchant_ack": "메시지를 받았습니다. {merchant} 고객지원이 곧 처리합니다.",
        "platform_ack": "피드백을 받았습니다. 플랫폼 고객지원이 계속 처리하겠습니다.",
        "status_no_tracking": "없음",
        "node_created": "주문 접수",
        "translated": "번역: ",
        "no_translation": "번역 없음",
        "analyzing": "첨부 파일을 확인하는 중…",
        "history": "기록",
        "new_chat": "새 대화",
        "untitled": "제목 없음",
        "today": "오늘",
        "yesterday": "어제",
        "history_empty": "기록이 없습니다",
        "delete": "삭제",
        "rename": "이름 변경",
        "pin": "상단 고정",
        "unpin": "고정 해제",
        "pinned": "고정됨",
        "disclaimer": "면책 안내: 본 내용은 참고용이며 결과를 보장하지 않습니다. 모든 연락과 제출은 본인이 플랫폼 규칙과 현지 법률을 준수하여 직접 진행하세요.",
        "rate_answer": "현재 참고 환율: 1 {from} = {ratio:.4f} {to}. 따라서 {amount:.2f} {from} = {converted:.2f} {to}.",
        "emoji_smile": "웃는 얼굴",
        "emoji_gesture": "손동작",
        "emoji_item": "물건",
        "emoji_mood": "기분",
        "default_ai": "안녕하세요, CargoGuard AI 구매자 권익 자문입니다. 주문 상태, 배송비, 환율을 문의하시거나 상품 파손·오배송 등 애프터서비스 문제를 알려주실 수 있습니다. 구매자 권익을 지키기 위해 규정에 맞는 참고 방안을 제공하고, 더 나은 크로스보더 쇼핑 경험을 돕겠습니다.",
        "merchant_default": "안녕하세요, 판매자 고객지원입니다. 주문 관련 문의를 환영합니다.",
        "platform_default": "안녕하세요, 플랫폼 고객지원입니다. 판매자와의 소통이 원활하지 않거나 문제가 해결되지 않을 때 지원해드립니다.",
    },
    "fr": {
        "brand": "CargoGuard",
        "ai": "Agent IA",
        "merchant": "Support vendeur",
        "platform": "Support plateforme",
        "orders": "Commandes",
        "rate": "Taux de change",
        "send": "Envoyer",
        "search_merchant": "Rechercher par vendeur, n° de commande, produit ou date",
        "placeholder": "Saisissez du texte",
        "status_online": "En ligne",
        "order_id": "Numéro de commande",
        "unit_price": "Prix unitaire",
        "total_price": "Prix total",
        "qty": "Quantité",
        "from": "De",
        "to": "Vers",
        "amount": "Montant",
        "result": "Résultat du calcul",
        "exchange_rate": "Taux de change",
        "converted_amount": "Montant converti",
        "currency_name": "Nom de la devise",
        "ai_fallback": "Je peux vous aider avec le statut de commande, les frais de livraison, les taux de change, les remboursements ou les articles endommagés/erronés. Essayez par exemple « 1 USD en KRW » ou « Où est la commande ORD-1004 ? ».",
        "order_not_found": "Commande {order_id} introuvable. Veuillez vérifier le numéro de commande.",
        "order_hint": " (Pour vérifier une commande précise, indiquez le numéro, ex. ORD-1004.)",
        "attachment_ack": "J'ai bien reçu vos {n} pièce(s) jointe(s). Comment puis-je vous aider ?",
        "escalate_merchant": "Cela semble être un problème à la réception (article endommagé ou erroné). Veuillez d'abord contacter le **support vendeur** — décrivez la situation à la réception, vous pouvez demander un échange, un réenvoi ou un remboursement.",
        "escalate_platform": "Il s'agit d'un cas où le vendeur ne remplit pas ses obligations (refus ou retard de remboursement, manque de courtoisie, absence de réponse). Je recommande de passer au **support plateforme**, qui peut intervenir et relancer.",
        "escalate_platform_materials": "Veuillez préparer le numéro de commande, les demandes de remboursement et des captures des échanges avec le vendeur comme preuves.",
        "escalate_order_context": "Contexte de la commande : {order_id} est actuellement {status}, {refund}.",
        "refund_in_progress": "avec un remboursement/retour en cours",
        "refund_done": "avec un remboursement/retour déjà effectué",
        "refund_none_now": "sans remboursement en cours",
        "order_not_found_bare": "Aucune commande correspondante trouvée. Veuillez fournir le numéro complet (ex. ORD-1004).",
        "status_ship_no": "{order_id} n'a pas encore été expédiée.",
        "status_ship_yes": "{order_id} a été expédiée (statut actuel : {status}).",
        "status_ship_after": "{order_id} est actuellement {status} et a entré dans la procédure après-vente.",
        "status_refund_active": "Statut actuel de {order_id} : {status}.",
        "status_refund_none": "{order_id} est actuellement {status}, aucune procédure de remboursement en cours.",
        "status_logistics": "{order_id} · {status}. Expédition : {shipping_status}. {logistics_info}. Suivi : {tracking}.",
        "order_time": "Heure de commande",
        "merchant_label": "Vendeur",
        "product_label": "Produit",
        "read": "Lu",
        "unread": "Non lu",
        "timeline_title": "Chronologie du statut",
        "no_orders": "Aucune commande pour le moment.",
        "no_merchants": "Aucun vendeur ou commande correspondant.",
        "attach_caption": "Images (png/jpg/jpeg/gif/webp) et vidéos (mp4/mov/webm), {mb}MB max par fichier",
        "attach_too_big": "« {name} » dépasse {mb}MB et a été ignoré.",
        "merchant_ack": "Message reçu. Le support de {merchant} va traiter votre demande.",
        "platform_ack": "Retour bien reçu. Le support plateforme va poursuivre le traitement.",
        "status_no_tracking": "aucun",
        "node_created": "Commande passée",
        "translated": "Traduction : ",
        "no_translation": "Traduction indisponible",
        "analyzing": "Analyse des pièces jointes…",
        "history": "Historique",
        "new_chat": "Nouvelle conversation",
        "untitled": "Sans titre",
        "today": "Aujourd'hui",
        "yesterday": "Hier",
        "history_empty": "Aucun historique",
        "delete": "Supprimer",
        "rename": "Renommer",
        "pin": "Épingler en haut",
        "unpin": "Désépingler",
        "pinned": "Épinglé",
        "disclaimer": "Avertissement : ce contenu est fourni à titre indicatif et ne garantit aucun résultat. Toute communication ou soumission doit être effectuée par vous-même, dans le respect des règles de la plateforme et du droit local.",
        "rate_answer": "Taux de référence actuel : 1 {from} = {ratio:.4f} {to}. Donc {amount:.2f} {from} = {converted:.2f} {to}.",
        "emoji_smile": "Visages",
        "emoji_gesture": "Gestes",
        "emoji_item": "Objets",
        "emoji_mood": "Humeurs",
        "default_ai": "Bonjour, je suis CargoGuard, votre conseiller IA pour les droits des acheteurs. Vous pouvez poser des questions sur le statut de la commande, les frais de port et les taux de change, ou signaler des problèmes après-vente (produit endommagé, article erroné). Je vous fournirai des conseils conformes, à titre indicatif, pour défendre vos droits d'acheteur et améliorer votre expérience d'achat transfrontalier.",
        "merchant_default": "Bonjour, je suis le support vendeur. Nous sommes heureux de vous aider.",
        "platform_default": "Bonjour, je suis le support plateforme. Si le vendeur ne répond pas ou si le problème n'est pas réglé, nous pouvons escalader le cas.",
    }
}

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

# =========================================================
# 商家/平台（对方）消息：原文 + 五语言预设译文
# =========================================================
LANG_CODES = ["en", "zh", "ja", "ko", "fr"]

# =========================================================
# 订单详情 / 商品详情：五语言文案 + 跨境风险提示
# =========================================================
ORDER_UX = {
    "en": {
        "order_detail": "Order details", "product_detail": "Product details",
        "view_detail": "View details", "view_product": "View product details",
        "item_title": "Item", "service_title": "Service terms", "specs_title": "Specifications",
        "desc_title": "Product description", "risk_title": "Cross-border risk notice",
        "risk_intro": "These notices are set by the merchant. Please read before ordering.",
        "order_no": "Order No.", "merchant": "Merchant", "order_time": "Order time",
        "status": "Status", "total": "Order total", "shipping_fee": "Shipping fee",
        "tracking": "Tracking No.", "origin_address": "Ship from", "shipping_address": "Ship to", "qty": "Quantity", "unit_price": "Unit price",
        "subtotal": "Item subtotal", "spec": "Spec",
        "delisted_notice": "This item has been removed. The product page is no longer available — the store may have been closed or is unreachable. Please contact support via your order or payment channel. Keep your order screenshot and payment receipt as evidence.",
        "account_closed": "This account has been deactivated",
        "account_closed_note": "The merchant has closed this store and can no longer receive messages. Please go back to your order and escalate to platform support for a refund or after-sales handling.",
        "tag_free_ship": "Free shipping", "tag_paid_ship": "Shipping charged",
        "tag_tax_in": "Tax included", "tag_tax_ex": "Tax not included",
        "tag_7d": "7-day no-reason return", "tag_no_7d": "No 7-day return",
        "tag_7d_limits": "Cross-border limits: return shipping is paid by the buyer; the item must be unused with tags, packaging and accessories intact; some categories cannot be returned across borders; refunds are subject to platform review.",
        "risks": [
            ("Logistics risk", "Cross-border routes are long with multiple transfers, so timing varies. Parcels may stall, be lost, arrive late, or show delayed tracking updates."),
            ("Delivery risk", "Overseas couriers often leave parcels at the door, a pickup point or with a neighbor, which carries theft or mix-up risk. A \"delivered\" status does not mean you personally received it."),
            ("Damage & after-sales", "Long-distance shipping can cause dents or breakage. Cross-border returns are complex and costly, and some items cannot be returned internationally."),
            ("Customs & tax", "Parcels may be inspected, held or require extra documents. Items without tax-included service may incur duty or VAT, borne by the responsible party and subject to actual customs assessment."),
            ("Other notes", "Local regulations apply. Sizes, voltage, plugs and certification standards may differ from your country. After-sales disputes usually take longer than domestic orders."),
        ],
    },
    "zh": {
        "order_detail": "订单详情", "product_detail": "商品详情",
        "view_detail": "查看详情", "view_product": "查看商品详情",
        "item_title": "商品条目", "service_title": "服务说明", "specs_title": "规格参数",
        "desc_title": "商品介绍", "risk_title": "跨境风险提示",
        "risk_intro": "以下为商家设置的跨境通用风险提示，请下单前留意。",
        "order_no": "订单编号", "merchant": "商家", "order_time": "下单时间",
        "status": "订单状态", "total": "订单总额", "shipping_fee": "运费",
        "tracking": "物流单号", "origin_address": "寄件地", "shipping_address": "收件地", "qty": "数量", "unit_price": "单价",
        "subtotal": "商品小计", "spec": "规格",
        "delisted_notice": "该商品已下架，商品页面已无法打开，店铺可能已关闭或失联。请通过订单或支付渠道联系客服处理，并保留订单截图与付款凭证作为证据。",
        "account_closed": "该账户已注销",
        "account_closed_note": "该商家已关闭店铺，无法再接收消息。请返回订单页面，向平台客服发起售后或退款处理。",
        "tag_free_ship": "包邮", "tag_paid_ship": "不包邮",
        "tag_tax_in": "包税", "tag_tax_ex": "不包税",
        "tag_7d": "支持 7 天无理由退货退款", "tag_no_7d": "不支持 7 天无理由",
        "tag_7d_limits": "跨境限制：退回运费由买家承担；商品需不影响二次销售（吊牌、包装、配件完整）；部分品类不支持跨国退货；退款以平台审核为准。",
        "risks": [
            ("物流风险", "跨境链路长、中转多，时效波动大，存在包裹停滞、丢件、派送延迟、物流更新滞后的可能。"),
            ("签收风险", "海外派送常放置门口、驿站或邻居代收，存在被盗、错拿风险；包裹显示签收不等于买家实际收到货。"),
            ("破损与售后风险", "长途运输易出现商品磕碰破损；跨境退货流程复杂、国际运费高昂，部分商品不支持跨国退货。"),
            ("清关税费风险", "包裹可能被海关查验扣货、需要补充资料；非包税商品可能产生关税、增值税，由对应责任方承担，以海关实际征收为准。"),
            ("其他提示", "商品受海外当地法规约束；尺码、电压、插头、认证标准与国内商品存在差异；售后维权周期通常比国内电商更长。"),
        ],
    },
    "ja": {
        "order_detail": "注文詳細", "product_detail": "商品詳細",
        "view_detail": "詳細を見る", "view_product": "商品詳細を見る",
        "item_title": "商品", "service_title": "サービス条件", "specs_title": "仕様",
        "desc_title": "商品説明", "risk_title": "越境リスクのご案内",
        "risk_intro": "以下は販売者が設定した越境共通の注意事項です。ご注文前にご確認ください。",
        "order_no": "注文番号", "merchant": "販売者", "order_time": "注文日時",
        "status": "注文状況", "total": "合計金額", "shipping_fee": "送料",
        "tracking": "追跡番号", "origin_address": "発送元", "shipping_address": "お届け先", "qty": "数量", "unit_price": "単価",
        "subtotal": "商品小計", "spec": "仕様",
        "delisted_notice": "この商品は削除されました。商品ページは表示できません。ショップが閉店または連絡不通の可能性があります。注文または決済チャネル経由でサポートにご連絡ください。注文のスクリーンショットと支払い証明は証拠として保管してください。",
        "account_closed": "このアカウントは削除されました",
        "account_closed_note": "このショップは閉店したため、メッセージを受け取れません。注文ページに戻り、プラットフォームサポートへ返金・アフターサービスをご依頼ください。",
        "tag_free_ship": "送料無料", "tag_paid_ship": "送料有料",
        "tag_tax_in": "税込", "tag_tax_ex": "税別",
        "tag_7d": "7日間返品可（理由不問）", "tag_no_7d": "7日間返品不可",
        "tag_7d_limits": "越境制限：返送料は購入者負担、商品は未使用でタグ・包装・付属品が揃っている必要があります。一部カテゴリは越境返品不可、返金はプラットフォーム審査によります。",
        "risks": [
            ("物流リスク", "越境物流は経路が長く中継が多いため、遅延しやすく、停滞・紛失・配達遅延・追跡更新の遅れが起こる可能性があります。"),
            ("受け取りリスク", "海外では玄関先・集配所・近隣宅への代理受け渡しが多く、盗難や取り違えのリスクがあります。配達完了表示は本人受領を意味しません。"),
            ("破損・アフターサービス", "長距離輸送で傷や破損が起こりやすく、越境返品は複雑で送料も高額です。一部商品は越境返品不可です。"),
            ("通関・税費リスク", "通関検査・保留・追加書類の提出が必要な場合があります。税込でない商品は関税・付加価値税が発生し、責任者が負担します（実際の徴収によります）。"),
            ("その他", "現地法規が適用されます。サイズ・電圧・プラグ・認証基準は国内と異なる場合があり、紛争解決には通常より長い時間がかかります。"),
        ],
    },
    "ko": {
        "order_detail": "주문 상세", "product_detail": "상품 상세",
        "view_detail": "상세 보기", "view_product": "상품 상세 보기",
        "item_title": "상품", "service_title": "서비스 조건", "specs_title": "사양",
        "desc_title": "상품 설명", "risk_title": "크로스보더 위험 안내",
        "risk_intro": "아래 내용은 판매자가 설정한 크로스보더 공통 주의사항입니다. 주문 전 확인하세요.",
        "order_no": "주문 번호", "merchant": "판매자", "order_time": "주문 시간",
        "status": "주문 상태", "total": "총 결제 금액", "shipping_fee": "배송비",
        "tracking": "운송장 번호", "origin_address": "발송지", "shipping_address": "수령지", "qty": "수량", "unit_price": "단가",
        "subtotal": "상품 소계", "spec": "사양",
        "delisted_notice": "해당 상품은 삭제되었습니다. 상품 페이지를 열 수 없으며, 스토어가 폐점되었거나 연락이 두절되었을 수 있습니다. 주문 또는 결제 채널을 통해 고객센터에 문의하시고, 주문 캡처와 결제 증빙을 보관하세요.",
        "account_closed": "해당 계정은 탈퇴되었습니다",
        "account_closed_note": "이 판매자는 스토어를 폐쇄하여 메시지를 받을 수 없습니다. 주문 페이지로 돌아가 플랫폼 고객센터에 환불·애프터서비스를 요청하세요.",
        "tag_free_ship": "무료 배송", "tag_paid_ship": "배송비 유료",
        "tag_tax_in": "세금 포함", "tag_tax_ex": "세금 별도",
        "tag_7d": "7일 무이유 반품", "tag_no_7d": "7일 무이유 반품 불가",
        "tag_7d_limits": "크로스보더 제한: 반송비는 구매자 부담, 상품은 미사용 상태로 택·포장·부속품이 완전해야 하며, 일부 카테고리는 국제 반품이 불가합니다. 환불은 플랫폼 심사에 따릅니다.",
        "risks": [
            ("물류 위험", "크로스보더 경로는 길고 중계가 많아 지연이 잦으며, 물량 정체·분실·배송 지연·추적 정보 지연이 발생할 수 있습니다."),
            ("수령 위험", "해외 배송은 현관, 집배소, 인근 주택에 맡기는 경우가 많아 도난·혼동 위험이 있습니다. 배송 완료 표시가 본인 수령을 의미하지 않습니다."),
            ("파손·AS 위험", "장거리 운송 중 파손이 발생할 수 있고, 크로스보더 반품은 절차가 복잡하며 비용이 높습니다. 일부 상품은 국제 반품이 불가합니다."),
            ("통관·세금 위험", "세관 검사·보류·추가 서류 요구가 있을 수 있습니다. 세금 포함이 아닌 상품은 관세·부가세가 발생하며 책임 주체가 부담하고 실제 과세 기준을 따릅니다."),
            ("기타 안내", "현지 법규가 적용됩니다. 사이즈·전압·플러그·인증 기준이 국내와 다를 수 있으며, 분쟁 해결은 국내보다 오래 걸립니다."),
        ],
    },
    "fr": {
        "order_detail": "Détails de la commande", "product_detail": "Détails du produit",
        "view_detail": "Voir les détails", "view_product": "Voir le produit",
        "item_title": "Article", "service_title": "Conditions de service", "specs_title": "Caractéristiques",
        "desc_title": "Description du produit", "risk_title": "Risques transfrontaliers",
        "risk_intro": "Ces avis sont définis par le vendeur. À lire avant de commander.",
        "order_no": "N° de commande", "merchant": "Vendeur", "order_time": "Date de commande",
        "status": "Statut", "total": "Total", "shipping_fee": "Frais de port",
        "tracking": "N° de suivi", "origin_address": "Expédié depuis", "shipping_address": "Livré à", "qty": "Quantité", "unit_price": "Prix unitaire",
        "subtotal": "Sous-total", "spec": "Caractéristique",
        "delisted_notice": "Cet article a été retiré. La page produit n'est plus accessible — la boutique est peut-être fermée ou injoignable. Contactez l'assistance via votre commande ou votre canal de paiement, et conservez la capture de commande et le justificatif de paiement comme preuves.",
        "account_closed": "Ce compte a été désactivé",
        "account_closed_note": "Ce marchand a fermé sa boutique et ne peut plus recevoir de messages. Revenez à votre commande et contactez l'assistance de la plateforme pour un remboursement ou un service après-vente.",
        "tag_free_ship": "Livraison gratuite", "tag_paid_ship": "Livraison payante",
        "tag_tax_in": "Taxes incluses", "tag_tax_ex": "Taxes non incluses",
        "tag_7d": "Retour sous 7 jours", "tag_no_7d": "Pas de retour sous 7 jours",
        "tag_7d_limits": "Limites transfrontalières : frais de retour à la charge de l'acheteur ; article non utilisé, étiquettes, emballage et accessoires intacts ; certaines catégories ne peuvent pas être retournées à l'international ; remboursement soumis à validation de la plateforme.",
        "risks": [
            ("Risque logistique", "Les trajets transfrontaliers sont longs avec plusieurs transferts : retards, blocages, pertes et mises à jour de suivi différées sont possibles."),
            ("Risque de livraison", "À l'étranger, les colis sont souvent déposés devant la porte, en point relais ou chez un voisin, avec un risque de vol ou d'erreur. Un statut « livré » ne signifie pas que vous l'avez reçu en main propre."),
            ("Dommages et SAV", "Le transport longue distance peut provoquer des chocs ou des cassures. Les retours transfrontaliers sont complexes et coûteux, et certains articles ne sont pas repris à l'international."),
            ("Douane et taxes", "Le colis peut être inspecté, retenu ou nécessiter des documents. Sans service taxes incluses, des droits de douane ou une TVA peuvent s'appliquer, à la charge de la partie responsable, selon l'évaluation réelle de la douane."),
            ("Autres", "La réglementation locale s'applique. Tailles, tension, prises et certifications peuvent différer de votre pays. Les litiges prennent généralement plus de temps qu'une commande nationale."),
        ],
    },
}

# 商品详情元数据：按订单号（规格本地化 + 描述分类）
PRODUCT_META = {
    "ORD-1001": {"cat": "beauty", "spec": {"en": "30 ml · 1 pc", "zh": "30 毫升 · 1 件", "ja": "30ml・1個", "ko": "30ml · 1개", "fr": "30 ml · 1 pièce"}},
    "ORD-1002": {"cat": "electronics", "spec": {"en": "Wired · 3.5 mm · 100 pcs", "zh": "有线 · 3.5mm · 100 件", "ja": "有線・3.5mm・100個", "ko": "유선 · 3.5mm · 100개", "fr": "Filaire · 3,5 mm · 100 pièces"}},
    "ORD-1003": {"cat": "accessory", "spec": {"en": "1 pair · Mini bow", "zh": "1 对 · 迷你蝴蝶结", "ja": "1ペア・ミニリボン", "ko": "1쌍 · 미니 리본", "fr": "1 paire · nœud mini"}},
    "ORD-1004": {"cat": "premium", "spec": {"en": "Standard", "zh": "标准规格", "ja": "標準", "ko": "표준", "fr": "Standard"}},
    "ORD-1005": {"cat": "luxury_set", "spec": {"en": "Set · 2 pcs", "zh": "套装 · 2 件", "ja": "セット・2点", "ko": "세트 · 2개", "fr": "Ensemble · 2 pièces"}},
    "ORD-1006": {"cat": "drinkware", "spec": {"en": "350 ml · 1 pc", "zh": "350 毫升 · 1 件", "ja": "350ml・1個", "ko": "350ml · 1개", "fr": "350 ml · 1 pièce"}},
    "ORD-1007": {"cat": "decor", "spec": {"en": "40×60 cm · Canvas · 1 pc", "zh": "40×60 厘米 · 帆布画 · 1 件", "ja": "40×60cm・キャンバス・1枚", "ko": "40×60cm · 캔버스 · 1점", "fr": "40×60 cm · toile · 1 pièce"}},
    "ORD-1008": {"cat": "apparel", "spec": {"en": "Size M · Wool blend · 1 pc", "zh": "M 码 · 羊毛混纺 · 1 件", "ja": "Mサイズ・ウール混・1枚", "ko": "M 사이즈 · 울 혼방 · 1벌", "fr": "Taille M · laine mélangée · 1 pièce"}},
}

PRODUCT_DESC = {
    "apparel": {
        "en": "Cross-border direct-ship wool-blend trench coat with a classic trench silhouette; the fabric is structured and warm. Due to production batches and overseas packaging standards, the actual appearance and packaging may differ slightly from the images; product specifications on this page prevail. If you file an after-sales request, keep the original packaging and record an unboxing video to facilitate review.",
        "zh": "跨境直邮羊毛混纺风衣，经典战壕版型，面料挺括保暖。受生产批次、海外包装标准影响，实物外观、包装可能与图片略有差异，商品规格以本页信息为准。如发起售后，请留存原包装并录制开箱视频，方便审核。",
        "ja": "越境直送のウール混紡トレンチコート。クラシックなトレンチシルエットで、生地はハリがあり保温性に優れます。生産ロットや海外の梱包基準により、実物の外観・包装が画像と多少異なる場合があります。商品仕様は本ページの情報を優先します。アフターサービスを申請する場合は、元の梱包を保管し、開封動画を撮影して審査にご協力ください。",
        "ko": "크로스보더 직배송 울 혼방 트렌치코트로 클래식 트렌치 실루엣이며 원단이 탄탄하고 보온성이 좋습니다. 생산 배치와 해외 포장 기준에 따라 실물의 외관과 포장이 이미지와 조금 다를 수 있으며, 상품 사양은 본 페이지 정보를 기준으로 합니다. AS를 신청하실 경우 원포장을 보관하고 개봉 영상을 촬영해 주세요.",
        "fr": "Trench-coat en laine mélangée expédié en direct transfrontalier, coupe trench classique, tissu structuré et chaud. En raison des lots de production et des normes d'emballage à l'étranger, l'aspect et l'emballage réels peuvent différer légèrement des photos ; les caractéristiques de cette page prévalent. En cas de demande SAV, conservez l'emballage d'origine et filmez le déballage pour faciliter l'examen.",
    },
    "beauty": {
        "en": "Estée Lauder Advanced Night Repair eye cream with a fresh gel texture that absorbs easily, cares for the eye area day and night, brightens dark circles, softens fine lines around the eyes, and defends against environmental and blue-light damage. This item is shipped directly from overseas supply, so packaging and details may differ slightly by batch from the domestic version. Sensitive skin should do a patch test first; for after-sales service, please keep the original outer packaging and leave it unopened where possible.",
        "zh": "雅诗兰黛小棕瓶眼霜，凝露质地清爽易吸收，日夜修护眼周，焕亮黑眼圈、淡化眼周细纹，抵御外界环境与蓝光损伤。本品属于跨境直供，不同批次包装、细节会和国内版本略有差别。敏感肌使用前建议先行皮测；售后请留存原外包装，尽量保持未拆封。",
        "ja": "エスティローダー アドバンスド ナイトリペア アイクリーム。みずみずしいジェル状でなじみがよく、昼夜を通じて目元をケアし、くすみを明るくし、目元の小じわを目立たなくし、環境やブルーライトによるダメージを防ぎます。越境直供のため、ロットにより包装や細部が国内版と多少異なる場合があります。敏感肌の方は使用前にパッチテストを行ってください。アフターサービスには元の外包装を保管し、できれば未開封のままにしてください。",
        "ko": "에스티로더 어드밴스드 나이트 리페어 아이크림. 산뜻한 젤 텍스처로 흡수가 빠르고 밤낮으로 눈가를 케어하며, 눈가 다크서클을 밝게 하고 잔주름을 완화하며 외부 환경과 블루라이트 손상을 방어합니다. 해외 직공급 상품으로 배치에 따라 포장과 세부 사항이 국내판과 조금 다를 수 있습니다. 민감성 피부는 사용 전 패치 테스트를 권장하며, AS 신청 시 원래 외포장을 보관하고 가능하면 미개봉 상태를 유지하세요.",
        "fr": "Crème contour des yeux Estée Lauder Advanced Night Repair, texture gel fraîche à absorption rapide, qui prend soin du contour des yeux jour et nuit, illumine les cernes, atténue les ridules et protège des agressions environnementales et de la lumière bleue. Produit approvisionné directement à l'étranger : l'emballage et les détails peuvent varier légèrement selon le lot par rapport à la version nationale. Peau sensible : faites un test avant usage. Pour toute demande SAV, conservez l'emballage d'origine et, si possible, laissez-le non ouvert.",
    },
    "electronics": {
        "en": "Wired in-ear earphones with a standard 3.5 mm round jack, suitable for bulk purchase. Plug specifications and device compatibility vary, so please confirm they fit your device before ordering. Failures caused by improper human use, water damage, or unauthorized disassembly or modification are not covered by after-sales service. To request after-sales service, keep the original product packaging.",
        "zh": "有线入耳耳机，标准 3.5mm 圆孔接口，适合批量采购。插头规格、设备兼容性存在差异，请下单前确认可适配自身设备。人为使用不当、进水、私自拆解改装造成的故障，不在售后保障范围。如需申请售后，请保留商品原包装。",
        "ja": "有線インイヤーイヤホン、標準 3.5mm 丸型ジャック、まとめ買いに適しています。プラグ仕様や機器との互換性には差があるため、ご注文前にご自身の機器に適合するかご確認ください。人為的な不適切使用、水濡れ、無断の分解・改造による故障はアフターサービスの対象外です。アフターサービスをご希望の場合は、商品の元の梱包を保管してください。",
        "ko": "유선 인이어 이어폰, 표준 3.5mm 원형 잭, 대량 구매에 적합합니다. 플러그 규격과 기기 호환성에 차이가 있으므로 주문 전에 사용 중인 기기에 맞는지 확인하세요. 인위적인 부적절한 사용, 침수, 임의 분해·개조로 인한 고장은 애프터서비스 보장 범위가 아닙니다. 애프터서비스를 신청하려면 상품 원포장을 보관하세요.",
        "fr": "Écouteurs intra-auriculaires filaires avec jack rond standard de 3,5 mm, adaptés à l'achat en gros. Les spécifications de prise et la compatibilité avec les appareils varient ; veuillez confirmer l'adaptation à votre appareil avant de commander. Les pannes dues à un usage humain inapproprié, à l'eau ou à un démontage ou une modification non autorisés ne sont pas couvertes par le service après-vente. Pour toute demande de SAV, conservez l'emballage d'origine du produit.",
    },
    "accessory": {
        "en": "Dior mini bow earrings with a classic, elegant bow silhouette that is delicate and lively; the signature design softly accents everyday outfits, and refined craftsmanship traces gentle lines, making it a light-luxury accessory for many occasions. This is a cross-border fashion accessory, so dimensions, material details and finish may differ slightly between overseas batches; please confirm the specifications before ordering. Metal materials may cause contact allergies in a small number of people; stop wearing them immediately if discomfort occurs. For a return, keep the full original packaging and the item unworn and free of wear.",
        "zh": "Dior 迷你蝴蝶结耳环，经典优雅的蝴蝶结造型精致灵动，品牌标志性设计柔和点缀日常穿搭，细腻工艺勾勒柔美线条，是适配多种场合的轻奢配饰。本品为跨境时尚配饰，尺寸、材质细节与做工会随海外批次存在细微差别，下单前请确认规格信息。金属材质可能引发少数人群接触过敏，若佩戴后产生不适请立刻取下停用。如需申请退货，请保留全套原装包装，商品保持未佩戴、无磨损的全新状态。",
        "ja": "ディオール ミニ リボン イヤリング。クラシックで優雅なリボンシルエットが繊細で軽やかで、ブランドを象徴するデザインが日常の装いにさりげなく映え、繊細な職人技がやわらかなラインを描く、幅広い場面に合うライトデラックスアクセサリーです。越境ファッションアクセサリーのため、サイズ・素材の細部・仕上げは海外ロットにより多少異なる場合があります。ご注文前に仕様をご確認ください。金属素材はごく一部の方に接触アレルギーを引き起こす場合があり、装着後に違和感があれば直ちに外してください。返品には元の付属品を含む完全な梱包と、未装着・摩耗のない新品状態が必要です。",
        "ko": "디올 미니 리본 이어링. 클래식하고 우아한 리본 실루엣이 정교하고 생동감 있으며, 브랜드 시그니처 디자인이 일상 룩에 부드럽게 포인트를 주고 섬세한 공정이 부드러운 라인을 그려 다양한 자리에 어울리는 라이트 럭셔리 액세서리입니다. 해외 패션 액세서리로 사이즈, 소재 디테일, 마감이 해외 배치에 따라 조금 다를 수 있으니 주문 전 사양을 확인하세요. 금속 소재는 일부 사용자에게 접촉 알레르기를 유발할 수 있으며 착용 후 불편함이 있으면 즉시 벗어 주세요. 반품 시 전체 원포장을 보관하고 착용하지 않은 마모 없는 새 상태를 유지해야 합니다.",
        "fr": "Boucles d'oreilles Dior mini nœud, silhouette nœud classique et élégante, délicate et vive ; le design signature du label agrémente discrètement les tenues du quotidien, et un travail raffiné dessine des lignes douces : un accessoire de luxe léger adapté à de nombreuses occasions. Accessoire de mode transfrontalier, les dimensions, les détails de matière et la finition peuvent varier légèrement selon les lots étrangers ; vérifiez les caractéristiques avant de commander. Les matières métalliques peuvent provoquer des allergies de contact chez certaines personnes ; retirez-les immédiatement en cas d'inconfort. Pour un retour, conservez l'emballage d'origine complet et l'article non porté, sans usure.",
    },
    "drinkware": {
        "en": "Cross-border portable travel thermos with a 350 ml capacity; the body is light and easy to carry on the go. Affected by overseas production batches and local packaging standards, the actual packaging and colour details may differ slightly from the product images; the specifications on this page prevail. Please check the sealing performance before use; for any after-sales request, keep the full original packaging, keep the item with all accessories complete and free of use wear, and record an unboxing video.",
        "zh": "跨境直邮便携随行保温杯，容量 350ml，杯身轻巧适合出行携带。受海外生产批次、当地包装标准影响，实物包装、配色细节可能与商品图片存在细微差异，规格以本页信息为准。使用前建议确认密封性能；如需申请售后，请保留全套原包装，商品保持配件齐全、无使用磨损状态，并录制开箱视频。",
        "ja": "越境直送の携帯用ステンレスボトル、容量 350ml、軽量なボディで外出時の持ち運びに適しています。海外の生産ロットや現地の梱包基準により、実物の梱包やカラーの細部が商品画像と多少異なる場合があります。仕様は本ページの情報を優先します。ご使用前に密封性をご確認いただくことをおすすめします。アフターサービスをご希望の場合は、セットの元の梱包をすべて保管し、付属品が揃った使用による摩耗のない状態を保ち、開封の様子を録画してください。",
        "ko": "크로스보더 직배송 휴대용 보온병, 용량 350ml, 가벼운 바디로 외출 시 휴대하기 적합합니다. 해외 생산 배치와 현지 포장 기준의 영향으로 실제 포장과 색상 세부 사항이 상품 이미지와 조금 다를 수 있으며, 사양은 본 페이지 정보를 기준으로 합니다. 사용 전에 밀봉 성능을 확인하시길 권장합니다. 애프터서비스를 신청하려면 전체 원포장을 보관하고, 구성품이 모두 갖춰진 사용 흔적 없는 상태를 유지하며 개봉 영상을 촬영하세요.",
        "fr": "Thermos portable de voyage expédié en transfrontalier, contenance 350 ml, corps léger adapté au transport en déplacement. En raison des lots de production étrangers et des normes d'emballage locales, l'emballage et les détails de couleur réels peuvent différer légèrement des images du produit ; les caractéristiques indiquées sur cette page prévalent. Il est conseillé de vérifier l'étanchéité avant usage ; pour toute demande SAV, conservez l'emballage d'origine complet, gardez l'article avec tous ses accessoires et sans trace d'usure, et filmez le déballage.",
    },
    "premium": {
        "en": "Premium item shipped cross-border. Affected by overseas production batches and local packaging standards, the actual packaging and appearance details may differ slightly from the product images; the specifications marked on this page prevail. Please confirm the item meets your needs before use; for any after-sales request, keep the original packaging and record a complete unboxing video for verification.",
        "zh": "跨境直邮精品货品，受海外生产批次、当地包装标准影响，实物包装、外观细节可能和商品图片存在细微差别，产品规格以本页标注信息为准。请在使用前确认商品符合自身使用需求；如需发起售后，请妥善留存原包装，并录制完整开箱视频用于核验。",
        "ja": "越境直送のプレミアム商品です。海外の生産ロットや現地の梱包基準により、実物の梱包や外観の細部が商品画像と多少異なる場合があります。製品仕様は本ページの記載情報を優先します。ご使用前にご自身の用途に合うかご確認ください。アフターサービスをご希望の場合は、元の梱包を大切に保管し、確認用に開封の様子を最初から最後まで録画してください。",
        "ko": "크로스보더 직배송 프리미엄 상품입니다. 해외 생산 배치와 현지 포장 기준의 영향으로 실제 포장과 외관 세부 사항이 상품 이미지와 조금 다를 수 있으며, 제품 사양은 본 페이지에 표기된 정보를 기준으로 합니다. 사용 전에 상품이 본인의 사용 목적에 맞는지 확인하세요. 애프터서비스를 신청하려면 원포장을 잘 보관하고 검증용으로 개봉 과정 전체를 영상으로 촬영하세요.",
        "fr": "Article premium expédié en transfrontalier. En raison des lots de production étrangers et des normes d'emballage locales, l'emballage et les détails d'aspect réels peuvent différer légèrement des images du produit ; les caractéristiques indiquées sur cette page prévalent. Veuillez confirmer avant usage que l'article correspond à vos besoins ; pour toute demande SAV, conservez soigneusement l'emballage d'origine et filmez un déballage complet à des fins de vérification.",
    },
    "luxury_set": {
        "en": "Luxury set shipped cross-border, containing two items. Affected by overseas production batches and local packaging regulations, the actual packaging and appearance details may differ slightly from the product images; the specifications on this page prevail. Please confirm the item meets your needs before use; for any after-sales request, keep the full original packaging and record a complete unboxing video.",
        "zh": "跨境直邮奢华套装，内含两件单品。受海外生产批次、当地包装规范影响，实物包装、外观细节可能与商品图片存在细微差别，规格以本页信息为准。使用前请确认商品符合使用需求；如需申请售后，请保留全套原包装并录制完整开箱视频。",
        "ja": "越境直送のラグジュアリーセットで、2 点のアイテムが含まれます。海外の生産ロットや現地の梱包基準により、実物の梱包や外観の細部が商品画像と多少異なる場合があります。仕様は本ページの情報を優先します。ご使用前にご自身の用途に合うかご確認ください。アフターサービスをご希望の場合は、セットの元の梱包をすべて保管し、開封の様子を最初から最後まで録画してください。",
        "ko": "크로스보더 직배송 럭셔리 세트로 두 개의 아이템이 포함되어 있습니다. 해외 생산 배치와 현지 포장 규정의 영향으로 실제 포장과 외관 세부 사항이 상품 이미지와 조금 다를 수 있으며, 사양은 본 페이지 정보를 기준으로 합니다. 사용 전에 상품이 사용 목적에 맞는지 확인하세요. 애프터서비스를 신청하려면 전체 원포장을 보관하고 개봉 과정 전체를 영상으로 촬영하세요.",
        "fr": "Coffret de luxe expédié en transfrontalier, contenant deux articles. En raison des lots de production étrangers et des normes d'emballage locales, l'emballage et les détails d'aspect réels peuvent différer légèrement des images du produit ; les caractéristiques indiquées sur cette page prévalent. Veuillez confirmer avant usage que l'article correspond à vos besoins ; pour toute demande SAV, conservez l'emballage d'origine complet et filmez un déballage intégral.",
    },
    "generic": {
        "en": "Item shipped cross-border. Packaging, batch and appearance may differ slightly from product images; specs on this page prevail. Check compatibility before use and keep the packaging plus an unboxing video for any after-sales request.",
        "zh": "跨境直邮商品，包装、批次与外观可能与商品图片存在细微差异，规格以本页信息为准。使用前请确认适配性；申请售后请保留包装并录制开箱视频。",
        "ja": "越境直送品です。梱包・ロット・外観は商品画像と多少異なる場合があり、仕様は本ページの情報を優先します。使用前に適合性をご確認いただき、アフターサービスのため梱包と開封動画を保管してください。",
        "ko": "크로스보더 직배송 상품입니다. 포장, 배치, 외관이 상품 이미지와 조금 다를 수 있으며 사양은 본 페이지 정보를 기준으로 합니다. 사용 전 호환성을 확인하고 AS를 위해 포장과 개봉 영상을 보관하세요.",
        "fr": "Article expédié en transfrontalier. L'emballage, le lot et l'aspect peuvent différer légèrement des photos ; les caractéristiques de cette page prévalent. Vérifiez la compatibilité avant usage et conservez l'emballage ainsi qu'une vidéo de déballage pour tout SAV.",
    },
}

# 服务标签：按订单号固定（包邮 / 包税 / 7 天无理由）
ORDER_SERVICES = {
    "ORD-1001": {"free_ship": True, "tax_in": True, "seven_day": True},
    "ORD-1002": {"free_ship": False, "tax_in": False, "seven_day": False},
    "ORD-1003": {"free_ship": True, "tax_in": False, "seven_day": True},
    "ORD-1004": {"free_ship": False, "tax_in": False, "seven_day": False},
    "ORD-1005": {"free_ship": True, "tax_in": True, "seven_day": False},
    "ORD-1006": {"free_ship": True, "tax_in": False, "seven_day": True},
    "ORD-1007": {"free_ship": True, "tax_in": False, "seven_day": False},
    "ORD-1008": {"free_ship": True, "tax_in": False, "seven_day": True},
}

# 商品已下架（商家跑路/关店）的订单：商品详情页不可打开
DELISTED_ORDERS = {"ORD-1007"}


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



def _now_ts():
    """消息时间戳：HH:MM，随消息保存。"""
    return datetime.now().strftime("%H:%M")


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


# =========================================================
# 订单数据：从 data.db 读取，DB 不可用时回退到内置样例
# =========================================================
_FALLBACK_ORDERS = [
    {"order_id": "ORD-1004", "merchant": "Northwind Store", "merchant_avatar": "N",
     "product_name": "Premium Product", "product_image": "P", "quantity": 1,
     "unit_price": 89.99, "total_price": 89.99, "shipping_status": "In transit",
     "tracking_number": "TRK123456", "shipping_fee": 12.50, "currency": "USD",
     "logistics_info": "Warehouse -> Local hub -> Final delivery", "status": "正在运输中",
     "order_time": "2026-10-05 08:30"},
]

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

# 九种订单状态 + 标签配色（语义分组，柔和不刺眼）
ORDER_STATUSES = ["正在运输中", "未发货", "已发货", "申请退款中", "申请退货中", "已退款", "已退货", "待签收", "已签收"]
STATUS_BADGE_STYLE = {
    "未发货":     ("#000000", "#f3f4f6"),   # 灰
    "已发货":     ("#4b5563", "#f3f4f6"),   # 灰
    "正在运输中": ("#1f2937", "#e5e7eb"),   # 深灰
    "待签收":     ("#0d9488", "#ccfbf1"),   # 青
    "已签收":     ("#059669", "#d1fae5"),   # 绿
    "申请退款中": ("#d97706", "#fef3c7"),   # 琥珀
    "申请退货中": ("#ea580c", "#ffedd5"),   # 橙
    "已退款":     ("#059669", "#d1fae5"),   # 绿
    "已退货":     ("#059669", "#d1fae5"),   # 绿
}

# 状态枚举 -> 各语言展示标签（展示层不再直接输出中文状态值）
STATUS_LABELS = {
    "en": {"未发货": "Not shipped", "已发货": "Shipped", "正在运输中": "In transit",
           "待签收": "Out for delivery", "已签收": "Delivered", "申请退款中": "Refund requested",
           "申请退货中": "Return requested", "已退款": "Refunded", "已退货": "Returned",
           "清关中": "Customs clearance", "待缴税": "Duties pending",
           "待补件": "Documents required", "查验扣留": "Held for inspection",
           "已完成": "Completed"},
    "zh": {s: s for s in ORDER_STATUSES},
    "ja": {"未发货": "未発送", "已发货": "発送済み", "正在运输中": "輸送中",
           "待签收": "受け取り待ち", "已签收": "受け取り済み", "申请退款中": "返金申請中",
           "申请退货中": "返品申請中", "已退款": "返金済み", "已退货": "返品済み",
           "清关中": "通関中", "待缴税": "関税支払い待ち",
           "待补件": "書類追加待ち", "查验扣留": "税関検査保留",
           "已完成": "完了"},
    "ko": {"未发货": "미발송", "已发货": "발송됨", "正在运输中": "배송 중",
           "待签收": "수령 대기", "已签收": "수령 완료", "申请退款中": "환불 신청 중",
           "申请退货中": "반품 신청 중", "已退款": "환불 완료", "已退货": "반품 완료",
           "清关中": "통관 중", "待缴税": "관세 납부 대기",
           "待补件": "서류 보완 필요", "查验扣留": "세관 검사 보류",
           "已完成": "완료"},
    "fr": {"未发货": "Non expédiée", "已发货": "Expédiée", "正在运输中": "En transit",
           "待签收": "En attente de réception", "已签收": "Livrée", "申请退款中": "Remboursement demandé",
           "申请退货中": "Retour demandé", "已退款": "Remboursée", "已退货": "Retournée",
           "清关中": "Dédouanement", "待缴税": "Droits à payer",
           "待补件": "Documents requis", "查验扣留": "Retenu en douane",
           "已完成": "Terminée"},
}

# 数据库里的英文物流节点 -> 本地化展示
SHIPPING_LABELS = {
    "en": {"In transit": "In transit", "Customs clearance": "Customs clearance",
           "Delivered": "Delivered", "Processing": "Processing"},
    "zh": {"In transit": "运输中", "Customs clearance": "清关中",
           "Delivered": "已送达", "Processing": "处理中"},
    "ja": {"In transit": "輸送中", "Customs clearance": "通関中",
           "Delivered": "配達済み", "Processing": "処理中"},
    "ko": {"In transit": "배송 중", "Customs clearance": "통관 중",
           "Delivered": "배달 완료", "Processing": "처리 중"},
    "fr": {"In transit": "En transit", "Customs clearance": "Dédouanement",
           "Delivered": "Livré", "Processing": "En traitement"},
}

# 数据库里的英文物流描述 -> 本地化展示
LOGISTICS_LABELS = {
    "zh": {
        "Warehouse -> Local hub -> Final delivery": "仓库 → 本地中转 → 末端配送",
        "International logistics center -> local warehouse -> final delivery": "国际物流中心 → 本地仓库 → 最终配送",
        "Export warehouse -> customs -> destination hub -> local courier": "出口仓 → 海关 → 目的地枢纽 → 当地快递",
        "Factory -> air freight -> city distribution center -> doorstep delivery": "工厂 → 空运 → 城市分拨中心 → 上门配送",
        "New York warehouse -> air freight -> Shanghai customs -> clearance in progress (DDP, duties prepaid by seller)": "纽约仓库 → 空运 → 上海海关 → 清关中（DDP，关税由卖家预付）",
    },
    "ja": {
        "Warehouse -> Local hub -> Final delivery": "倉庫 → 地域ハブ → 最終配送",
        "International logistics center -> local warehouse -> final delivery": "国際物流センター → 現地倉庫 → 最終配送",
        "Export warehouse -> customs -> destination hub -> local courier": "輸出倉庫 → 通関 → 目的地ハブ → 現地配送",
        "Factory -> air freight -> city distribution center -> doorstep delivery": "工場 → 航空便 → 都市配送センター → 宅配",
        "New York warehouse -> air freight -> Shanghai customs -> clearance in progress (DDP, duties prepaid by seller)": "ニューヨーク倉庫 → 航空便 → 上海税関 → 通関中（DDP、関税は販売者前払い）",
    },
    "ko": {
        "Warehouse -> Local hub -> Final delivery": "창고 → 지역 허브 → 최종 배송",
        "International logistics center -> local warehouse -> final delivery": "국제 물류 센터 → 현지 창고 → 최종 배송",
        "Export warehouse -> customs -> destination hub -> local courier": "수출 창고 → 세관 → 목적지 허브 → 현지 배송",
        "Factory -> air freight -> city distribution center -> doorstep delivery": "공장 → 항공 운송 → 도시 분배 센터 → 방문 배송",
        "New York warehouse -> air freight -> Shanghai customs -> clearance in progress (DDP, duties prepaid by seller)": "뉴욕 창고 → 항공 운송 → 상하이 세관 → 통관 중 (DDP, 관세 판매자 선납)",
    },
    "fr": {
        "Warehouse -> Local hub -> Final delivery": "Entrepôt → hub local → livraison finale",
        "International logistics center -> local warehouse -> final delivery": "Centre logistique international → entrepôt local → livraison finale",
        "Export warehouse -> customs -> destination hub -> local courier": "Entrepôt d'export → douane → hub de destination → transporteur local",
        "Factory -> air freight -> city distribution center -> doorstep delivery": "Usine → fret aérien → centre de distribution urbain → livraison à domicile",
        "New York warehouse -> air freight -> Shanghai customs -> clearance in progress (DDP, duties prepaid by seller)": "Entrepôt de New York → fret aérien → douane de Shanghai → dédouanement en cours (DDP, droits payés par le vendeur)",
    },
}

# 物流动态页（点击「清关中」状态卡进入）的页面文案
LOG_T = {
    "en": {"title": "Shipment tracking",
           "tracking": "Tracking No.", "route": "Shipping route",
           "movement": "Logistics updates", "now": "Current",
           "no_tracking": "No tracking information yet."},
    "zh": {"title": "物流动态",
           "tracking": "物流单号", "route": "运输路线",
           "movement": "物流动向", "now": "当前",
           "no_tracking": "暂无物流信息"},
    "ja": {"title": "物流状況",
           "tracking": "追跡番号", "route": "配送ルート",
           "movement": "物流の動き", "now": "現在",
           "no_tracking": "物流情報はまだありません"},
    "ko": {"title": "배송 현황",
           "tracking": "운송장 번호", "route": "배송 경로",
           "movement": "물류 동향", "now": "현재",
           "no_tracking": "배송 정보가 없습니다"},
    "fr": {"title": "Suivi logistique",
           "tracking": "N° de suivi", "route": "Itinéraire",
           "movement": "Étapes du suivi", "now": "Actuel",
           "no_tracking": "Aucune information de suivi"},
}

# 时间轴节点下的一句说明
LOG_NODE_DESC = {
    "en": {
        "created": "Order placed, the seller is preparing your item",
        "未发货": "Not shipped yet, waiting for carrier pickup",
        "已发货": "Handed over to the carrier",
        "正在运输中": "In international transit",
        "清关中": "Arrived at customs, clearance is in progress",
        "待签收": "Out for delivery from the local hub",
        "已签收": "Delivered and signed for",
        "待缴税": "Customs released, duties pending payment",
        "查验扣留": "Held for customs inspection",
        "待补件": "Additional documents requested by customs",
        "申请退款中": "Refund requested, waiting for the seller",
        "申请退货中": "Return requested, waiting for the seller",
        "已退款": "Refund completed",
        "已退货": "Return completed",
        "已完成": "Order completed",
    },
    "zh": {
        "created": "订单已提交，商家正在准备商品",
        "未发货": "商家尚未发货，等待揽收",
        "已发货": "商家已发货，包裹已交给承运商",
        "正在运输中": "包裹已离开发货地，正在国际运输途中",
        "清关中": "包裹已到达海关，正在办理清关手续",
        "待签收": "包裹已到达本地网点，正在派送",
        "已签收": "包裹已签收",
        "待缴税": "海关已放行，需缴纳关税",
        "查验扣留": "包裹被海关查验扣留",
        "待补件": "海关要求补充申报材料",
        "申请退款中": "退款申请已提交，等待商家处理",
        "申请退货中": "退货申请已提交，等待商家处理",
        "已退款": "退款已完成",
        "已退货": "退货已完成",
        "已完成": "订单已完成",
    },
    "ja": {
        "created": "注文済み、販売者が商品を準備しています",
        "未发货": "未発送、集荷待ちです",
        "已发货": "販売者から発送され、配送業者に引き渡されました",
        "正在运输中": "国際輸送中です",
        "清关中": "税関に到着、通関手続き中です",
        "待签收": "最寄りの拠点から配達中です",
        "已签收": "配達完了、受領済みです",
        "待缴税": "通関許可済み、関税の支払い待ちです",
        "查验扣留": "税関検査で保留中です",
        "待补件": "税関から追加書類の提出が求められています",
        "申请退款中": "返金申請中、販売者の対応待ちです",
        "申请退货中": "返品申請中、販売者の対応待ちです",
        "已退款": "返金完了",
        "已退货": "返品完了",
        "已完成": "注文完了",
    },
    "ko": {
        "created": "주문 접수, 판매자가 상품을 준비 중입니다",
        "未发货": "미발송, 수거 대기 중입니다",
        "已发货": "판매자가 발송하여 운송사에 인계했습니다",
        "正在运输中": "국제 운송 중입니다",
        "清关中": "세관에 도착하여 통관 절차가 진행 중입니다",
        "待签收": "현지 허브에서 배송 중입니다",
        "已签收": "배송 완료 및 수령 확인",
        "待缴税": "통관 허가 완료, 관세 납부 대기 중입니다",
        "查验扣留": "세관 검사로 보류 중입니다",
        "待补件": "세관에서 추가 서류를 요청했습니다",
        "申请退款中": "환불 신청 중, 판매자 처리 대기",
        "申请退货中": "반품 신청 중, 판매자 처리 대기",
        "已退款": "환불 완료",
        "已退货": "반품 완료",
        "已完成": "주문 완료",
    },
    "fr": {
        "created": "Commande passée, le vendeur prépare votre article",
        "未发货": "Pas encore expédiée, en attente d'enlèvement",
        "已发货": "Remise au transporteur",
        "正在运输中": "En transit international",
        "清关中": "Arrivée à la douane, dédouanement en cours",
        "待签收": "En cours de livraison depuis le hub local",
        "已签收": "Livrée et signée",
        "待缴税": "Dédouanée, droits de douane à payer",
        "查验扣留": "Retenue pour contrôle douanier",
        "待补件": "Documents complémentaires demandés par la douane",
        "申请退款中": "Remboursement demandé, en attente du vendeur",
        "申请退货中": "Retour demandé, en attente du vendeur",
        "已退款": "Remboursement effectué",
        "已退货": "Retour effectué",
        "已完成": "Commande terminée",
    },
}

# 商家主页（从订单详情的店铺栏进入）页面文案
MERCHANT_T = {
    "zh": {"about": "商家介绍", "products": "店铺商品", "reviews": "客户评价",
           "write": "发表评价", "placeholder": "说说你的购物体验…", "submit": "发表",
           "posted": "评价已发表，感谢你的反馈！", "report": "举报商家",
           "reason": "举报原因", "detail": "补充说明（选填）", "reportSubmit": "提交举报",
           "reportDone": "举报已提交，平台将在 24 小时内核实处理。", "reportOkTitle": "举报成功",
           "contact": "联系商家客服", "sold": "已售", "verified": "认证商家",
           "empty": "暂无评价", "you": "我", "count": "{n} 条评价", "reviewsTitle": "评论",
           "needRating": "请选择星级并填写评价内容",
           "translation": "翻译", "sameLang": "该评论原文即为当前语言",
           "clickTrans": "点击查看翻译",
           "reasons": ["假冒商品", "商品与描述不符", "服务态度差", "诱导私下交易"]},
    "en": {"about": "About the store", "products": "Products in store", "reviews": "Customer reviews",
           "write": "Write a review", "placeholder": "Share your experience with this store…", "submit": "Publish",
           "posted": "Your review has been published. Thank you!", "report": "Report store",
           "reason": "Reason", "detail": "Details (optional)", "reportSubmit": "Submit report",
           "reportDone": "Report submitted. Platform support will review it within 24 hours.",
           "reportOkTitle": "Report submitted",
           "contact": "Contact merchant support", "sold": "sold", "verified": "Verified merchant",
           "empty": "No reviews yet", "you": "You", "count": "{n} reviews", "reviewsTitle": "Reviews",
           "needRating": "Please choose a star rating and write your review.",
           "translation": "Translation",
           "sameLang": "This review was originally written in your current language.",
           "clickTrans": "Click to see translation",
           "reasons": ["Counterfeit goods", "Item not as described", "Poor customer service", "Off-platform payment request"]},
    "ja": {"about": "ストア紹介", "products": "ストアの商品", "reviews": "カスタマー評価",
           "write": "評価を投稿", "placeholder": "買い物の感想を書いてください…", "submit": "投稿",
           "posted": "評価を投稿しました。ありがとうございます！", "report": "ストアを報告",
           "reason": "報告理由", "detail": "詳細（任意）", "reportSubmit": "報告を送信",
           "reportDone": "報告を受け付けました。24時間以内に確認します。", "reportOkTitle": "報告を送信しました",
           "contact": "販売者サポートに連絡", "sold": "販売済み", "verified": "認証ストア",
           "empty": "評価はまだありません", "you": "自分", "count": "{n} 件の評価", "reviewsTitle": "レビュー",
           "needRating": "星の数を選び、評価内容を入力してください。",
           "translation": "翻訳", "sameLang": "このレビューは現在の言語で書かれています。",
           "clickTrans": "クリックで翻訳を表示",
           "reasons": ["偽造品", "説明と異なる商品", "対応が悪い", "外部取引の誘導"]},
    "ko": {"about": "스토어 소개", "products": "스토어 상품", "reviews": "고객 평가",
           "write": "평가 작성", "placeholder": "쇼핑 경험을 남겨 주세요…", "submit": "게시",
           "posted": "평가가 게시되었습니다. 감사합니다!", "report": "스토어 신고",
           "reason": "신고 사유", "detail": "상세 설명(선택)", "reportSubmit": "신고 제출",
           "reportDone": "신고가 접수되었습니다. 24시간 내에 확인됩니다.", "reportOkTitle": "신고 접수 완료",
           "contact": "판매자 고객센터", "sold": "판매", "verified": "인증 스토어",
           "empty": "아직 평가가 없습니다", "you": "나", "count": "평가 {n}개", "reviewsTitle": "리뷰",
           "needRating": "별점을 선택하고 평가 내용을 입력해 주세요.",
           "translation": "번역", "sameLang": "이 리뷰는 현재 언어로 작성되었습니다.",
           "clickTrans": "클릭하여 번역 보기",
           "reasons": ["위조 상품", "설명과 다른 상품", "불친절한 응대", "외부 거래 유도"]},
    "fr": {"about": "À propos de la boutique", "products": "Produits de la boutique", "reviews": "Avis clients",
           "write": "Rédiger un avis", "placeholder": "Partagez votre expérience…", "submit": "Publier",
           "posted": "Votre avis a été publié. Merci !", "report": "Signaler la boutique",
           "reason": "Motif", "detail": "Détails (facultatif)", "reportSubmit": "Envoyer le signalement",
           "reportDone": "Signalement envoyé. Le support examinera sous 24 heures.",
           "reportOkTitle": "Signalement envoyé",
           "contact": "Contacter le support vendeur", "sold": "vendus", "verified": "Boutique vérifiée",
           "empty": "Aucun avis", "you": "Vous", "count": "{n} avis", "reviewsTitle": "Avis",
           "needRating": "Choisissez une note et rédigez votre avis.",
           "translation": "Traduction",
           "sameLang": "L'avis original est déjà dans votre langue actuelle.",
           "clickTrans": "Cliquez pour voir la traduction",
           "reasons": ["Produits contrefaits", "Article non conforme", "Service client médiocre", "Paiement hors plateforme"]},
}

# 商家档案：介绍、标签、店铺商品、顾客评价（内容随界面语言切换，缺省回退英文）
def _ml(zh, en, ja, ko, fr):
    return {"zh": zh, "en": en, "ja": ja, "ko": ko, "fr": fr}


def _pick(value, lang):
    return value.get(lang, value.get("en", "")) if isinstance(value, dict) else value


# 评价原文语言与用户所在地：原文语言按作者名确定性分配，展示"原本发的语言"
REVIEW_ORIG_LANGS = ["en", "ja", "ko", "fr", "zh"]

REVIEW_LOCATIONS = {
    "en": _ml("伦敦，英国", "London, UK", "ロンドン、イギリス", "런던, 영국", "Londres, Royaume-Uni"),
    "ja": _ml("东京，日本", "Tokyo, Japan", "東京、日本", "도쿄, 일본", "Tokyo, Japon"),
    "ko": _ml("首尔，韩国", "Seoul, South Korea", "ソウル、韓国", "서울, 대한민국", "Séoul, Corée du Sud"),
    "fr": _ml("巴黎，法国", "Paris, France", "パリ、フランス", "파리, 프랑스", "Paris, France"),
    "zh": _ml("广州，中国", "Guangzhou, China", "広州、中国", "광저우, 중국", "Canton, Chine"),
}

REVIEW_LANG_NAMES = {
    "en": _ml("英语", "English", "英語", "영어", "anglais"),
    "ja": _ml("日语", "Japanese", "日本語", "일본어", "japonais"),
    "ko": _ml("韩语", "Korean", "韓国語", "한국어", "coréen"),
    "fr": _ml("法语", "French", "フランス語", "프랑스어", "français"),
    "zh": _ml("中文", "Chinese", "中国語", "중국어", "chinois"),
}


def review_origin(author: str) -> str:
    """按作者名确定性分配原文语言，保证同一评论每次显示一致。"""
    return REVIEW_ORIG_LANGS[sum(ord(ch) for ch in str(author)) % len(REVIEW_ORIG_LANGS)]


MERCHANT_PROFILES = {
    "Estée Lauder": {
        "intro": _ml("源自纽约的美妆品牌，始于 1946 年。护肤与彩妆官方跨境旗舰店，美国仓库发货，DDP 关税由卖家预付。",
                     "New York beauty house since 1946. Authorised cross-border flagship for skincare and makeup, "
                     "shipped from our US warehouse with DDP duties prepaid by the seller.",
                     "1946年創業のニューヨーク発ビューティーブランド。スキンケアとメイクの公式越境旗艦店。米国倉庫から発送し、DDP（関税は販売者負担）でお届けします。",
                     "1946년에 시작된 뉴욕 뷰티 하우스. 스킨케어·메이크업 공식 크로스보더 플래그십으로 미국 창고에서 발송하며 DDP(관세 판매자 부담)입니다.",
                     "Maison de beauté new-yorkaise depuis 1946. Boutique officielle transfrontalière de soins et maquillage, expédiée depuis notre entrepôt américain en DDP (droits payés par le vendeur)."),
        "tags": [_ml("护肤", "Skincare", "スキンケア", "스킨케어", "Soins"),
                 _ml("彩妆", "Makeup", "メイク", "메이크업", "Maquillage"),
                 _ml("香水", "Fragrance", "フレグランス", "향수", "Parfum")],
        "rating": 4.8, "sold": 12800,
        "products": [
            {"name": _ml("特润修护眼霜", "Advanced Night Repair Eye Cream", "アドバンスト ナイト リペア アイクリーム", "어드밴스드 나이트 리페어 아이크림", "Crème yeux Advanced Night Repair"), "price": "USD 25.00", "sold": 6320},
            {"name": _ml("微精华原生液", "Micro Essence Treatment Lotion", "マイクロ エッセンス ローション", "마이크로 에센스 로션", "Lotion Micro Essence"), "price": "USD 62.00", "sold": 2100},
            {"name": _ml("持妆粉底液", "Double Wear Foundation", "ダブル ウェア ファンデーション", "더블웨어 파운데이션", "Fond de teint Double Wear"), "price": "USD 45.00", "sold": 1840},
            {"name": _ml("红石榴面膜", "Super-Pomegranate Mask", "ザクロ マスク", "석류 마스크", "Masque grenade"), "price": "USD 32.00", "sold": 960},
        ],
        "reviews": [
            {"author": "Sophie L.", "rating": 5, "days": 2,
             "text": _ml("眼霜密封完好，和描述一致。关税由卖家预付，清关很顺利。",
                         "Eye cream arrived sealed and exactly as described. Customs was smooth because duties were prepaid.",
                         "アイクリームは密封された状態で届き、説明通りでした。関税前払いで通関もスムーズでした。",
                         "아이크림이 밀봉 상태로 도착했고 설명과 동일했어요. 관세가 선납되어 통관이 순조로웠습니다.",
                         "Crème pour les yeux arrivée scellée et conforme. Dédouanement facile, droits prépayés.")},
            {"author": "Daniel K.", "rating": 5, "days": 7,
             "text": _ml("空运到上海总共九天，速度很快。正品，批号可查。",
                         "Fast air-freight delivery to Shanghai, nine days in total. Authentic, batch code verifiable.",
                         "上海まで航空便で合計9日でした。正規品で、バッチコードも確認できました。",
                         "상하이까지 항공 배송 총 9일. 정품이고 배치 코드도 확인됩니다.",
                         "Livraison aérienne rapide vers Shanghai, neuf jours au total. Authentique, code vérifiable.")},
            {"author": "Mia W.", "rating": 3, "days": 14,
             "text": _ml("产品没问题，但外盒有点压痕。客服一天内回复并给了部分退款。",
                         "Product is fine but the outer box was slightly dented. Support replied within a day and offered a partial refund.",
                         "商品は問題ありませんが、外箱が少しへこんでいました。サポートは1日以内に返信し、一部返金してくれました。",
                         "제품은 괜찮지만 외箱이 살짝 찌그러졌어요. 하루 만에 답변하고 부분 환불을 해줬습니다.",
                         "Produit conforme mais boîte légèrement cabossée. Support réactif, remboursement partiel proposé.")},
            {"author": "Hannah R.", "rating": 4, "days": 21,
             "text": _ml("大促价格很划算，寄到深圳比承诺慢了一点。",
                         "Good value during the sale. Shipping to Shenzhen took a little longer than promised.",
                         "セール中はお得でした。深圳への配送が約束より少し遅れました。",
                         "세일 기간 가격이 좋았어요. 선전 배송이 약속보다 조금 늦었습니다.",
                         "Bon rapport qualité-prix pendant les soldes. Livraison vers Shenzhen un peu plus lente que prévu.")},
            {"author": "Kenji T.", "rating": 5, "days": 30,
             "text": _ml("第三次回购，品质稳定，清关进度很透明。",
                         "Third repurchase. Consistent quality and the clearance tracking is very transparent.",
                         "3回目のリピートです。品質が安定していて、通関状況の追跡がとても透明です。",
                         "세 번째 재구매. 품질이 일정하고 통관 추적이 투명해요.",
                         "Troisième achat. Qualité constante et suivi du dédouanement très transparent.")},
        ],
    },
    "义乌": {
        "intro": _ml("义乌消费电子配件批发档口。起订量低，浙江发货快，可按需定制 OEM 标志。",
                     "Yiwu wholesale stall for consumer electronics accessories. Small minimum order, fast dispatch "
                     "from Zhejiang, OEM logos available on request.",
                     "義烏の家電アクセサリー卸売店。小ロット対応、浙江省から迅速発送、OEMロゴも相談可能です。",
                     "이우 소비재 전자 액세서리 도매상. 소량 주문 가능, 저장성에서 빠른 발송, OEM 로고 요청 가능.",
                     "Stand de gros d'accessoires électroniques à Yiwu. Petites commandes acceptées, expédition rapide depuis le Zhejiang, logos OEM sur demande."),
        "tags": [_ml("数码电子", "Electronics", "電子機器", "전자제품", "Électronique"),
                 _ml("配件", "Accessories", "アクセサリー", "액세서리", "Accessoires"),
                 _ml("批发", "Wholesale", "卸売", "도매", "Gros")],
        "rating": 4.5, "sold": 9640,
        "products": [
            {"name": _ml("有线耳机（3.5mm）", "Wired Earphones (3.5mm)", "有線イヤホン（3.5mm）", "유선 이어폰(3.5mm)", "Écouteurs filaires (3,5 mm)"), "price": "CNY 18.00", "sold": 4200},
            {"name": _ml("USB-C 快充数据线", "USB-C Fast Charging Cable", "USB-C 急速充電ケーブル", "USB-C 고속 충전 케이블", "Câble USB-C charge rapide"), "price": "CNY 12.00", "sold": 3650},
            {"name": _ml("蓝牙 5.3 耳机", "Bluetooth 5.3 Earbuds", "Bluetooth 5.3 イヤホン", "블루투스 5.3 이어버드", "Écouteurs Bluetooth 5.3"), "price": "CNY 89.00", "sold": 820},
            {"name": _ml("手机指环支架", "Phone Ring Holder", "スマホリング", "폰 링 홀더", "Anneau support téléphone"), "price": "CNY 6.50", "sold": 5300},
        ],
        "reviews": [
            {"author": "Chen Y.", "rating": 5, "days": 3,
             "text": _ml("给店里进了 50 副耳机，全部测试通过，卖家还多送了两副备用。",
                         "Ordered 50 earphones for our shop, all tested and working. Seller even included two spares.",
                         "店舗用にイヤホン50個を注文。全て動作確認済みで、予備2個も同梱されていました。",
                         "매장용 이어폰 50개 주문, 모두 정상 작동합니다. 예비 2개도 넣어줬어요.",
                         "Commandé 50 écouteurs pour notre boutique, tous testés et fonctionnels. Deux pièces de rechange offertes.")},
            {"author": "Ali R.", "rating": 5, "days": 8,
             "text": _ml("同类里最便宜的价格，批发单发货也很快。",
                         "Cheapest price I could find and dispatch was quick for a wholesale order.",
                         "最安値でした。卸注文でも発送が速かったです。",
                         "찾아본 중 최저가였고, 도매 주문인데 발송도 빨랐습니다.",
                         "Le meilleur prix trouvé, expédition rapide même en gros.")},
            {"author": "Wang H.", "rating": 3, "days": 16,
             "text": _ml("音质对得起价格，但 50 副里有 3 副线材松动，协商了部分退款。",
                         "Sound quality is average for the price, and 3 of 50 units had loose wiring. Partial refund agreed.",
                         "音質は価格相応ですが、50個中3個の配線が緩んでいました。一部返金で合意しました。",
                         "가격 대비 음질은 보통이고, 50개 중 3개 배선이 헐거웠어요. 부분 환불에 합의했습니다.",
                         "Son correct pour le prix, mais 3 unités sur 50 avec câblage lâche. Remboursement partiel accepté.")},
            {"author": "Fatima S.", "rating": 4, "days": 35,
             "text": _ml("沟通顺畅，包装可以再结实些，总体是靠谱的供应商。",
                         "Good communication, packing could be stronger. Overall a reliable supplier.",
                         "連絡はスムーズでした。梱包はもう少し頑丈だと良いですが、全体的に信頼できる業者です。",
                         "소통은 원활했고, 포장은 조금 더 튼튼하면 좋겠습니다. 전반적으로 믿을 만한 공급처입니다.",
                         "Bonne communication, emballage perfectible. Fournisseur fiable dans l'ensemble.")},
        ],
    },
    "Dior": {
        "intro": _ml("巴黎高级时装屋。珠宝与小皮具官方跨境精品店，法国发货，保价运输并附防伪卡。",
                     "Parisian couture house. Official cross-border boutique for jewellery and small leather goods, "
                     "shipped from France with insured delivery and authenticity cards.",
                     "パリのクチュールメゾン。ジュエリーとスモールレザーグッズの公式越境ブティック。フランスから保険付き配送、保証カード付き。",
                     "파리 꾸뛰르 하우스. 주얼리와 스몰 레더 굿즈 공식 크로스보더 부티크. 프랑스에서 보험 배송, 정품 카드 동봉.",
                     "Maison de couture parisienne. Boutique officielle transfrontalière de bijoux et petite maroquinerie, expédiée de France avec livraison assurée et carte d'authenticité."),
        "tags": [_ml("珠宝", "Jewellery", "ジュエリー", "주얼리", "Bijoux"),
                 _ml("奢侈品", "Luxury", "ラグジュアリー", "럭셔리", "Luxe"),
                 _ml("配饰", "Accessories", "アクセサリー", "액세서리", "Accessoires")],
        "rating": 4.7, "sold": 5210,
        "products": [
            {"name": _ml("CD 蝴蝶结耳钉", "CD Mini Bow Earrings", "CD ミニ リボン ピアス", "CD 미니 보우 귀걸이", "Boucles nœud CD Mini"), "price": "EUR 49.00", "sold": 640},
            {"name": _ml("J'Adior 手镯套装", "J'Adior Bracelet Set", "J'Adior ブレスレット セット", "쟈디오르 브레이슬릿 세트", "Set de bracelets J'Adior"), "price": "EUR 62.00", "sold": 410},
            {"name": _ml("30 Montaigne 戒指", "30 Montaigne Ring", "30 モンテーニュ リング", "30 몽테뉴 반지", "Bague 30 Montaigne"), "price": "EUR 55.00", "sold": 380},
            {"name": _ml("Oblique 真丝丝巾", "Oblique Silk Scarf", "オブリーク シルク スカーフ", "오블리크 실크 스카프", "Carré de soie Oblique"), "price": "EUR 78.00", "sold": 520},
        ],
        "reviews": [
            {"author": "Camille D.", "rating": 5, "days": 4,
             "text": _ml("耳钉配有原装收纳袋和防伪卡，做工精致。",
                         "Earrings came in the original pouch with the authenticity card. Beautiful finish.",
                         "オリジナルポーチと保証カード付きで届きました。仕上がりが美しいです。",
                         "오리지널 파우치와 정품 카드가 함께 왔어요. 마감이 훌륭합니다.",
                         "Boucles livrées dans leur pochette d'origine avec carte d'authenticité. Finition superbe.")},
            {"author": "Yuki M.", "rating": 5, "days": 9,
             "text": _ml("海关要求补充材料，卖家几小时内就发来了，服务出色。",
                         "Customs asked for extra documents, but the seller sent them within hours. Excellent service.",
                         "税関から追加書類を求められましたが、販売者が数時間で送ってくれました。素晴らしい対応です。",
                         "세관에서 추가 서류를 요청했는데 판매자가 몇 시간 내로 보내줬습니다. 훌륭한 서비스.",
                         "La douane a demandé des documents, le vendeur les a envoyés en quelques heures. Excellent service.")},
            {"author": "Lena F.", "rating": 2, "days": 18,
             "text": _ml("收到时一只耳钉弯了，虽然补发了但等了十二天。",
                         "One earring was bent on arrival. A replacement was offered but it took twelve days.",
                         "到着時に片方のピアスが曲がっていました。交換品は提案されましたが12日かかりました。",
                         "도착했을 때 귀걸이 한쪽이 휘어 있었어요. 교체를 제안받았지만 12일이 걸렸습니다.",
                         "Une boucle était tordue à l'arrivée. Remplacement proposé mais douze jours d'attente.")},
            {"author": "Grace C.", "rating": 5, "days": 28,
             "text": _ml("礼品包装很完美，妹妹非常喜欢。",
                         "Gift-wrapped perfectly. My sister loved it.",
                         "ギフト包装が完璧で、妹が大喜びでした。",
                         "선물 포장이 완벽했고 여동생이 아주 좋아했어요.",
                         "Emballage cadeau parfait, ma sœur a adoré.")},
        ],
    },
    "Northwind Store": {
        "intro": _ml("来自温哥华的户外与日用装备店。每件商品都经过实地测试，自营仓库全球发货。",
                     "Outdoor and everyday gear from Vancouver. We field-test everything we sell and ship worldwide "
                     "from our own warehouse.",
                     "バンクーバー発のアウトドア・日用品ブランド。全商品を実地テストし、自社倉庫から世界へ発送します。",
                     "밴쿠버의 아웃도어·라이프스타일 숍. 판매하는 모든 제품을 실전 테스트하며 자체 창고에서 전 세계로 발송합니다.",
                     "Boutique outdoor et lifestyle de Vancouver. Chaque article est testé sur le terrain et expédié depuis notre propre entrepôt."),
        "tags": [_ml("户外", "Outdoor", "アウトドア", "아웃도어", "Plein air"),
                 _ml("生活方式", "Lifestyle", "ライフスタイル", "라이프스타일", "Lifestyle"),
                 _ml("装备", "Gear", "ギア", "장비", "Équipement")],
        "rating": 4.6, "sold": 3120,
        "products": [
            {"name": _ml("精选商品", "Premium Product", "プレミアム商品", "프리미엄 상품", "Produit premium"), "price": "USD 89.99", "sold": 520},
            {"name": _ml("保温露营水壶", "Insulated Camping Bottle", "保温キャンプボトル", "보온 캠핑 보틀", "Gourde isotherme camping"), "price": "USD 34.00", "sold": 640},
            {"name": _ml("可折叠日用背包 22L", "Packable Daypack 22L", "パッカブル デイパック 22L", "패커블 데이팩 22L", "Sac à dos pliable 22 L"), "price": "USD 59.00", "sold": 310},
            {"name": _ml("美利奴徒步袜", "Merino Hiking Socks", "メリノ ハイキングソックス", "메리노 하이킹 양말", "Chaussettes rando mérinos"), "price": "USD 18.00", "sold": 880},
        ],
        "reviews": [
            {"author": "Ethan B.", "rating": 5, "days": 2,
             "text": _ml("徒步一整天水都是凉的，做工非常扎实。",
                         "The bottle keeps water cold through a full day of hiking. Really solid build.",
                         "ハイキング中ずっと冷たさをキープできました。作りがとても頑丈です。",
                         "하이킹 내내 물이 시원하게 유지됩니다. 제작이 정말 튼튼해요.",
                         "La gourde garde l'eau froide toute une journée de rando. Construction très solide.")},
            {"author": "Nora P.", "rating": 4, "days": 9,
             "text": _ml("背包很轻，做工不错，拉链刚开始有点紧。",
                         "Daypack is light and well made. The zips feel a bit stiff at first.",
                         "デイパックは軽くて作りも良いです。ファスナーは最初少し硬めでした。",
                         "백팩은 가볍고 잘 만들어졌지만 지퍼가 처음엔 뻑뻑합니다.",
                         "Sac léger et bien fait, zips un peu durs au début.")},
            {"author": "Marc T.", "rating": 5, "days": 20,
             "text": _ml("周日联系客服也有回复，还免费补发了背带。",
                         "Support answered on a Sunday and shipped a replacement strap for free.",
                         "日曜でもサポートが返信し、交換ストラップを無料で送ってくれました。",
                         "일요일에도 고객센터가 답변하고 교체 스트랩을 무료로 보내줬습니다.",
                         "Support joignable un dimanche, sangle de remplacement offerte.")},
            {"author": "Ivy L.", "rating": 3, "days": 32,
             "text": _ml("袜子偏小一码，建议买大一码。寄到亚洲用了三周。",
                         "Socks run small - order one size up. Shipping to Asia took three weeks.",
                         "靴下は小さめなので、ワンサイズ上をおすすめします。アジアへの配送に3週間かかりました。",
                         "양말이 작게 나왔어요. 한 사이즈 크게 주문하세요. 아시아 배송에 3주 걸렸습니다.",
                         "Chaussettes petites, prenez une taille au-dessus. Trois semaines vers l'Asie.")},
        ],
    },
    "Ocean Commerce": {
        "intro": _ml("伦敦生活方式精品店，主营礼盒、家居香氛与织物。从英国出口仓发货，全程可追踪。",
                     "London lifestyle boutique curating gift sets, home fragrance and textiles. Dispatched from our "
                     "UK export warehouse with tracked international shipping.",
                     "ロンドンのライフスタイルブティック。ギフトセット、ホームフレグランス、テキスタイルを厳選。英国の輸出倉庫から追跡付き国際配送で発送します。",
                     "런던 라이프스타일 부티크. 기프트 세트, 홈 프래그런스, 텍스타일을 큐레이션합니다. 영국 수출 창고에서 추적 가능한 국제 배송으로 발송합니다.",
                     "Boutique lifestyle londonienne : coffrets cadeaux, parfums d'intérieur et textiles. Expédition suivie depuis notre entrepôt britannique."),
        "tags": [_ml("礼盒", "Gift sets", "ギフトセット", "기프트 세트", "Coffrets"),
                 _ml("家居", "Home", "ホーム", "홈", "Maison"),
                 _ml("生活方式", "Lifestyle", "ライフスタイル", "라이프스타일", "Lifestyle")],
        "rating": 4.4, "sold": 4870,
        "products": [
            {"name": _ml("臻选礼盒", "Luxury Set", "ラグジュアリー セット", "럭셔리 세트", "Coffret luxe"), "price": "GBP 54.00", "sold": 730},
            {"name": _ml("海岸香薰蜡烛三件套", "Coastal Candle Trio", "コースタル キャンドル トリオ", "코스탈 캔들 트리오", "Trio de bougies Coastal"), "price": "GBP 38.00", "sold": 620},
            {"name": _ml("亚麻盖毯", "Linen Throw Blanket", "リネン ブランケット", "린넨 스로우 블랭킷", "Plaid en lin"), "price": "GBP 46.00", "sold": 410},
            {"name": _ml("陶瓷香薰机", "Ceramic Diffuser", "セラミック ディフューザー", "세라믹 디퓨저", "Diffuseur en céramique"), "price": "GBP 29.00", "sold": 540},
        ],
        "reviews": [
            {"author": "Olivia H.", "rating": 5, "days": 5,
             "text": _ml("礼盒包装精美，和照片一模一样。",
                         "Gift set was beautifully packed, exactly like the photos.",
                         "ギフトセットは写真通り美しく梱包されていました。",
                         "선물 세트 포장이 사진 그대로 아주 예뻐요.",
                         "Coffret magnifiquement emballé, fidèle aux photos.")},
            {"author": "Jack W.", "rating": 4, "days": 12,
             "text": _ml("蜡烛很好闻，不过盒子到货时有点磨损。",
                         "The candle smells great, though the box arrived a little scuffed.",
                         "キャンドルの香りは良いですが、箱が少し擦れて届きました。",
                         "캔들 향은 좋지만 상자가 조금 긁혀 도착했습니다.",
                         "La bougie sent très bon, boîte un peu abîmée à l'arrivée.")},
            {"author": "Amara N.", "rating": 5, "days": 24,
             "text": _ml("订了三套作婚礼回礼，卖家还帮我们逐套贴了标签。",
                         "Ordered three sets as wedding favours and the seller labelled each one for us.",
                         "結婚式の引き出物に3セット注文。一つずつラベルを貼ってくれました。",
                         "결혼 답례품으로 세 세트 주문했는데 각각 라벨을 붙여줬어요.",
                         "Trois coffrets commandés comme cadeaux de mariage, chacun étiqueté par le vendeur.")},
            {"author": "Tom S.", "rating": 2, "days": 33,
             "text": _ml("付款后才告知缺货，退款等了九天。",
                         "Item was out of stock after I paid, and the refund took nine days.",
                         "支払い後に在庫切れと判明し、返金に9日かかりました。",
                         "결제 후 품절 통보를 받았고 환불까지 9일 걸렸습니다.",
                         "Rupture de stock après paiement, remboursement en neuf jours.")},
        ],
    },
    "Sunrise Goods": {
        "intro": _ml("大阪日常杯壶品牌。不锈钢材质、可进洗碗机，为在意细节的通勤者设计。",
                     "Osaka maker of everyday drinkware. Stainless steel, dishwasher safe, designed for commuters "
                     "who care about small details.",
                     "大阪の日常ドリンクウェアブランド。ステンレス製で食洗機対応。細部にこだわる通勤者のための設計です。",
                     "오사카의 데일리 드링크웨어 브랜드. 스테인리스 스틸, 식기세척기 사용 가능, 디테일을 중시하는 통근족을 위한 디자인입니다.",
                     "Marque de gourdes d'Osaka. Inox, compatible lave-vaisselle, pensée pour les navetteurs attentifs aux détails."),
        "tags": [_ml("杯壶", "Drinkware", "ドリンクウェア", "드링크웨어", "Gourdes"),
                 _ml("厨房", "Kitchen", "キッチン", "주방", "Cuisine"),
                 _ml("日常", "Everyday", "日用", "데일리", "Quotidien")],
        "rating": 4.8, "sold": 7630,
        "products": [
            {"name": _ml("随行杯 350ml", "Travel Mug 350ml", "トラベルマグ 350ml", "트래블 머그 350ml", "Mug de voyage 350 ml"), "price": "JPY 1,200", "sold": 2100},
            {"name": _ml("保温杯 500ml", "Vacuum Flask 500ml", "真空ボトル 500ml", "보온 플라스크 500ml", "Gourde isotherme 500 ml"), "price": "JPY 1,600", "sold": 1450},
            {"name": _ml("樱花杯", "Sakura Tumbler", "さくらタンブラー", "벚꽃 텀블러", "Tumbler sakura"), "price": "JPY 1,400", "sold": 980},
            {"name": _ml("替换杯盖", "Replacement Lid", "交換用フタ", "교체용 뚜껑", "Couvercle de rechange"), "price": "JPY 300", "sold": 1260},
        ],
        "reviews": [
            {"author": "Haruto S.", "rating": 5, "days": 3,
             "text": _ml("咖啡六小时还烫，放包里从不漏水。",
                         "Keeps coffee hot for six hours and never leaks in my bag.",
                         "コーヒーが6時間保温され、カバンに入れても漏れません。",
                         "커피가 6시간 동안 뜨겁게 유지되고 가방에서 새지 않아요.",
                         "Garde le café chaud six heures, jamais de fuite dans le sac.")},
            {"author": "Elena V.", "rating": 5, "days": 10,
             "text": _ml("第二次购买，樱花图案很好看，杯盖完全贴合。",
                         "Second purchase. The sakura print is lovely and the lid fits perfectly.",
                         "2回目の購入です。桜柄が可愛く、蓋もぴったり合います。",
                         "두 번째 구매. 벚꽃 프린트가 예쁘고 뚜껑이 딱 맞습니다.",
                         "Deuxième achat. Le motif sakura est ravissant et le couvercle s'ajuste parfaitement.")},
            {"author": "Ben K.", "rating": 4, "days": 17,
             "text": _ml("杯子很棒，但 350ml 比想象中小。",
                         "Great mug, but the 350ml is smaller than I expected.",
                         "マグは素晴らしいですが、350mlは思ったより小さいです。",
                         "머그는 훌륭하지만 350ml는 생각보다 작아요.",
                         "Excellent mug, mais 350 ml, c'est plus petit que prévu.")},
            {"author": "Mei L.", "rating": 3, "days": 29,
             "text": _ml("杯底有一道小划痕，卖家补偿了 10% 退款。",
                         "Arrived with a small scratch on the base. Seller sent a 10% partial refund.",
                         "底に小さな傷がありましたが、10%の部分返金がありました。",
                         "바닥에 작은 흠집이 있었지만 10% 부분 환불을 받았습니다.",
                         "Petite rayure sur la base, remboursement partiel de 10 % reçu.")},
        ],
    },
    "Hunter Home Decor": {
        "intro": _ml("阿姆斯特丹工作室，出售手工完成的墙画与家居饰品。博物馆级画布，抗褪色颜料印刷。",
                     "Amsterdam studio selling hand-finished wall art and home decor, printed on museum-grade "
                     "canvas with fade-resistant pigment inks.",
                     "アムステルダムのスタジオ。手仕上げのウォールアートとインテリア雑貨。ミュージアムグレードのキャンバスに耐退色性インクで印刷しています。",
                     "암스테르담 스튜디오. 수작업으로 마감한 벽 장식과 홈 데코를 판매합니다. 뮤지엄급 캔버스에 내구성 안료 잉크로 인쇄.",
                     "Studio d'Amsterdam : art mural et déco finis à la main, imprimés sur toile musée avec encres résistantes à la décoloration."),
        "tags": [_ml("墙面装饰", "Wall art", "ウォールアート", "월 아트", "Art mural"),
                 _ml("家居装饰", "Home decor", "インテリア", "홈 데코", "Décoration"),
                 _ml("版画", "Prints", "プリント", "프린트", "Prints")],
        "rating": 4.3, "sold": 2140,
        "products": [
            {"name": _ml("抽象风景帆布画", "Abstract Landscape Canvas", "抽象風景キャンバス", "추상 풍경 캔버스", "Toile paysage abstrait"), "price": "EUR 40.00", "sold": 380},
            {"name": _ml("植物线条艺术画", "Botanical Line Art Print", "ボタニカル ラインアート プリント", "보태니컬 라인 아트 프린트", "Print botanique ligne"), "price": "EUR 32.00", "sold": 450},
            {"name": _ml("极简装裱海报", "Framed Minimal Poster", "ミニマル 額装ポスター", "미니멀 액자 포스터", "Affiche minimaliste encadrée"), "price": "EUR 28.00", "sold": 610},
            {"name": _ml("画廊帆布画三件套", "Gallery Canvas Set of 3", "ギャラリー キャンバス 3枚セット", "갤러리 캔버스 3종 세트", "Set de 3 toiles galerie"), "price": "EUR 72.00", "sold": 190},
        ],
        "reviews": [
            {"author": "Sanne B.", "rating": 5, "days": 4,
             "text": _ml("色彩浓郁，画布绷得很平整，挂在走廊效果很好。",
                         "Colours are rich and the canvas is stretched properly. Looks great in our hallway.",
                         "発色が豊かでキャンバスの張りも良好。廊下にとても映えます。",
                         "색감이 풍부하고 캔버스가 팽팽하게 잘 당겨져 있어요. 복도에 아주 잘 어울립니다.",
                         "Couleurs riches, toile bien tendue. Superbe dans notre couloir.")},
            {"author": "Lucas M.", "rating": 4, "days": 11,
             "text": _ml("印刷质量很好，但不含画框，下单前看清描述。",
                         "Print quality is excellent. No frame included - read the description carefully.",
                         "印刷品質は素晴らしいです。額縁は付属しないので説明をよく読んでください。",
                         "인쇄 품질은 훌륭하지만 액자 미포함이니 설명을 잘 읽으세요.",
                         "Impression excellente. Cadre non inclus : lisez bien la description.")},
            {"author": "Ana R.", "rating": 2, "days": 23,
             "text": _ml("十天没发货，卖家才说尺寸缺货。",
                         "Not shipped after ten days, then the seller said the size was unavailable.",
                         "10日経っても発送されず、その後サイズ欠品と告げられました。",
                         "열흘 동안 발송이 없더니 사이즈 품절이라고 안내받았습니다.",
                         "Pas d'expédition pendant dix jours, puis taille indisponible.")},
            {"author": "Chloe T.", "rating": 5, "days": 36,
             "text": _ml("我订的尺寸缺货，卖家免费升级成了更大的尺寸，很大方。",
                         "Seller upgraded to a bigger canvas when mine was out of stock. Very generous.",
                         "注文サイズが欠品で、販売者が大きいサイズに無料アップグレードしてくれました。",
                         "주문한 사이즈가 품절이었는데 더 큰 캔버스로 무료 업그레이드해줬어요.",
                         "Ma taille épuisée, le vendeur a offert une toile plus grande. Très généreux.")},
        ],
    },
    "Milano Style Outlet": {
        "intro": _ml("米兰意式外套奥莱店。往季款式奥莱价格，每件商品发货前经店内验真。",
                     "Milan outlet for Italian outerwear. Past-season pieces at outlet prices, every item "
                     "authenticity-checked in-house before dispatch.",
                     "ミラノのアウターウェア・アウトレット。過去シーズン品をアウトレット価格で。発送前に全品を店内で真贋チェックしています。",
                     "밀라노 아우터웨어 아울렛. 지난 시즌 상품을 아울렛 가격에 제공하며, 모든 상품은 발송 전 자체 정품 검수를 거칩니다.",
                     "Outlet milanais de manteaux italiens. Pièces de saisons passées à prix outlet, authenticité vérifiée avant expédition."),
        "tags": [_ml("外套", "Outerwear", "アウター", "아우터", "Manteaux"),
                 _ml("时尚", "Fashion", "ファッション", "패션", "Mode"),
                 _ml("奥莱", "Outlet", "アウトレット", "아울렛", "Outlet")],
        "rating": 4.5, "sold": 3980,
        "products": [
            {"name": _ml("羊毛混纺风衣", "Wool Blend Trench Coat", "ウール混トレンチコート", "울 블렌드 트렌치코트", "Trench en laine mélangée"), "price": "EUR 110.00", "sold": 290},
            {"name": _ml("绗缝轻量夹克", "Quilted Light Jacket", "キルティング ライトジャケット", "퀼팅 라이트 재킷", "Veste légère matelassée"), "price": "EUR 86.00", "sold": 350},
            {"name": _ml("羊绒围巾", "Cashmere Scarf", "カシミヤ マフラー", "캐시미어 스카프", "Écharpe en cachemire"), "price": "EUR 64.00", "sold": 470},
            {"name": _ml("真皮腰带", "Leather Belt", "レザーベルト", "가죽 벨트", "Ceinture en cuir"), "price": "EUR 39.00", "sold": 540},
        ],
        "reviews": [
            {"author": "Giulia P.", "rating": 5, "days": 2,
             "text": _ml("风衣尺码标准，羊毛比预想柔软很多。",
                         "The trench fits true to size and the wool is much softer than I expected.",
                         "トレンチはサイズ通りで、ウールは想像よりずっと柔らかいです。",
                         "트렌치코트 사이즈가 정확하고 울이 기대보다 훨씬 부드러워요.",
                         "Le trench taille bien et la laine est plus douce que prévu.")},
            {"author": "Noah F.", "rating": 4, "days": 10,
             "text": _ml("奥莱价很划算，唯一不足是派送前需要缴关税。",
                         "Great outlet price. Only downside: duties were requested before delivery.",
                         "アウトレット価格は魅力的です。唯一、配達前に関税請求があった点だけが残念。",
                         "아울렛 가격이 좋습니다. 단점은 배송 전 관세 납부 요청이 있었던 점.",
                         "Prix outlet intéressant. Seul bémol : droits demandés avant livraison.")},
            {"author": "Sofia M.", "rating": 5, "days": 22,
             "text": _ml("防伪标完好，客服用意大利语和英语双语回复。",
                         "Authenticity tag intact. Customer service replied in both Italian and English.",
                         "正規品タグも完好。カスタマー対応は伊・英両言語でした。",
                         "정품 택이 그대로고, 고객센터가 이탈리아어와 영어로 모두 답변했어요.",
                         "Étiquette d'authenticité intacte, support en italien et anglais.")},
            {"author": "Dmitri K.", "rating": 3, "days": 31,
             "text": _ml("夹克有颗纽扣松动，不过退款到账很快。",
                         "Jacket had a loose button, though the refund was issued quickly.",
                         "ジャケットのボタンが一つ緩んでいましたが、返金は迅速でした。",
                         "재킷 단추가 하나 헐거웠지만 환불은 빨랐습니다.",
                         "Un bouton desserré sur la veste, mais remboursement rapide.")},
        ],
    },
}


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

MONTHS_ABBR = {
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "fr": ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."],
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


# 状态 -> 合理流转路径（节点, 距下单小时数），最后一条即当前状态
TIMELINE_OFFSETS = {
    "created": 0, "未发货": 1, "已发货": 6, "正在运输中": 30, "待签收": 54, "已签收": 66,
    "申请退款中": 20, "申请退货中": 80, "已退款": 96, "已退货": 168,
    "清关中": 42, "待缴税": 48, "待补件": 50, "查验扣留": 46, "已完成": 72,
}
TIMELINE_PATHS = {
    "未发货": ["created", "未发货"],
    "已发货": ["created", "已发货"],
    "正在运输中": ["created", "已发货", "正在运输中"],
    "待签收": ["created", "已发货", "正在运输中", "待签收"],
    "已签收": ["created", "已发货", "正在运输中", "待签收", "已签收"],
    "申请退款中": ["created", "已发货", "申请退款中"],
    "申请退货中": ["created", "已发货", "已签收", "申请退货中"],
    "已退款": ["created", "已发货", "申请退款中", "已退款"],
    "已退货": ["created", "已发货", "已签收", "申请退货中", "已退货"],
    "清关中": ["created", "已发货", "正在运输中", "清关中"],
    "待缴税": ["created", "已发货", "正在运输中", "清关中", "待缴税"],
    "待补件": ["created", "已发货", "正在运输中", "清关中", "查验扣留", "待补件"],
    "已完成": ["created", "已发货", "正在运输中", "已签收", "已完成"],
}


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

# =========================================================
# 汇率数据
# =========================================================
CURRENCY_LABELS = {
    "USD": "USD", "EUR": "EUR", "GBP": "GBP", "CNY": "CNY",
    "JPY": "JPY", "KRW": "KRW", "AUD": "AUD", "SGD": "SGD",
    "THB": "THB"
}

EXCHANGE_RATES = {
    "USD": 1.0,
    "EUR": 0.92,
    "GBP": 0.78,
    "CNY": 7.15,
    "JPY": 157.0,
    "KRW": 1385.0,
    "AUD": 1.51,
    "SGD": 1.35,
    "THB": 35.5
}

# 币种别名（小写），用于识别自然语言中的币种
CURRENCY_ALIASES = {
    "USD": ["usd", "美元", "美金", "美刀", "dollar", "dollars", "buck"],
    "EUR": ["eur", "欧元", "euro", "euros"],
    "GBP": ["gbp", "英镑", "pound", "pounds"],
    "CNY": ["cny", "人民币", "rmb"],
    "JPY": ["jpy", "日元", "日币", "日圆", "yen"],
    "KRW": ["krw", "韩元", "韩币", "won"],
    "AUD": ["aud", "澳元", "澳币"],
    "SGD": ["sgd", "新加坡元", "新币"],
    "THB": ["thb", "泰铢"],
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

HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_history.json")


def load_ai_sessions():
    """从磁盘恢复历史会话；失败则返回 None。"""
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            data = json.load(f)
        sessions = []
        for s in data.get("sessions", []):
            sessions.append({
                "id": s["id"],
                "title": s.get("title", ""),
                "created": datetime.fromisoformat(s["created"]),
                "messages": s.get("messages", []),
                "pinned": bool(s.get("pinned", False)),
            })
        if sessions:
            active = data.get("active")
            if active not in [s["id"] for s in sessions]:
                active = sessions[0]["id"]
            return sessions, active, int(data.get("seq", len(sessions)))
    except Exception:
        pass
    return None


def save_ai_sessions():
    """把会话列表写入磁盘，附件字节不落盘。"""
    try:
        data = {
            "active": st.session_state.ai_active,
            "seq": st.session_state.ai_seq,
            "sessions": [
                {
                    "id": s["id"],
                    "title": s["title"],
                    "created": s["created"].isoformat(),
                    "pinned": bool(s.get("pinned", False)),
                    "messages": [
                        {k: v for k, v in m.items() if k != "attachments"}
                        for m in s["messages"]
                    ],
                }
                for s in st.session_state.ai_sessions
            ],
        }
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


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
# 页面切换工具
# =========================================================
def goto(page_name):
    if st.session_state.page != page_name:
        st.session_state.page_stack.append(st.session_state.page)
        st.session_state.page = page_name
        st.session_state["cg_page_fade"] = True

def go_back():
    if len(st.session_state.page_stack) > 0:
        st.session_state.page = st.session_state.page_stack.pop()
    else:
        st.session_state.page = "ai"
    st.session_state["cg_page_fade"] = True


def get_ai_session():
    for s in st.session_state.ai_sessions:
        if s["id"] == st.session_state.ai_active:
            return s
    return st.session_state.ai_sessions[0]


def touch_ai_title(text):
    """首条用户消息作为会话标题（按话题区分）。"""
    session = get_ai_session()
    if session.get("title"):
        return
    title = (text or "").strip().replace("\n", " ")
    if title:
        session["title"] = title[:18] + ("…" if len(title) > 18 else "")


def start_new_ai_session():
    touch_ai_title("")
    session = get_ai_session()
    if not session.get("title"):
        session["title"] = T[st.session_state.lang]["untitled"]
    st.session_state.ai_seq += 1
    messages = [{"role": "ai", "i18n": "default_ai", "ts": _now_ts()}]
    new_session = {"id": f"s{st.session_state.ai_seq}", "title": "", "created": datetime.now(), "messages": messages}
    st.session_state.ai_sessions.insert(0, new_session)
    st.session_state.ai_active = new_session["id"]
    st.session_state.ai_messages = messages
    save_ai_sessions()


def switch_ai_session(session_id):
    for s in st.session_state.ai_sessions:
        if s["id"] == session_id:
            st.session_state.ai_active = session_id
            st.session_state.ai_messages = s["messages"]
            save_ai_sessions()
            return


def delete_ai_session(session_id):
    """删除一条历史会话；若删的是当前会话则切到剩余第一条，全部删完则自动新建一条。"""
    st.session_state.ai_sessions = [
        s for s in st.session_state.ai_sessions if s["id"] != session_id
    ]
    if not st.session_state.ai_sessions:
        st.session_state.ai_seq += 1
        messages = [{"role": "ai", "i18n": "default_ai", "ts": _now_ts()}]
        new_session = {
            "id": f"s{st.session_state.ai_seq}",
            "title": "",
            "created": datetime.now(),
            "messages": messages,
        }
        st.session_state.ai_sessions.insert(0, new_session)
        st.session_state.ai_active = new_session["id"]
        st.session_state.ai_messages = messages
    elif st.session_state.ai_active == session_id:
        first = st.session_state.ai_sessions[0]
        st.session_state.ai_active = first["id"]
        st.session_state.ai_messages = first["messages"]
    save_ai_sessions()


def _ai_history_items():
    """把会话列表转成组件需要的数据（含分组、置顶、当前会话）。"""
    lang_pack = T[st.session_state.lang]
    today = datetime.now().date()
    items = []
    for s in st.session_state.ai_sessions:
        d = s["created"].date()
        if d == today:
            group = lang_pack["today"]
        elif d == today - timedelta(days=1):
            group = lang_pack["yesterday"]
        else:
            group = d.strftime("%Y-%m-%d")
        items.append({
            "id": s["id"],
            "title": s.get("title") or lang_pack["untitled"],
            "titleRaw": s.get("title", ""),
            "active": s["id"] == st.session_state.ai_active,
            "pinned": bool(s.get("pinned")),
            "group": group,
        })
    return items


def _handle_ai_history_action(res):
    """处理历史记录组件的回传：切换 / 删除 / 重命名 / 顶置。"""
    if not isinstance(res, dict):
        return
    seq = int(res.get("seq", 0) or 0)
    action = res.get("action")
    if not action or seq == st.session_state.get("ai_hist_seq", 0):
        return
    st.session_state["ai_hist_seq"] = seq
    sid = res.get("id")

    if action == "switch":
        switch_ai_session(sid)
        st.rerun()
    if action == "delete":
        delete_ai_session(sid)
        st.rerun()

    target = next(
        (s for s in st.session_state.ai_sessions if s["id"] == sid), None
    )
    if target is None:
        return
    if action == "rename":
        target["title"] = (res.get("title") or "").strip()[:60]
        save_ai_sessions()
    elif action == "pin":
        target["pinned"] = True
        st.session_state.ai_sessions.remove(target)
        st.session_state.ai_sessions.insert(0, target)
        save_ai_sessions()
    elif action == "unpin":
        target["pinned"] = False
        save_ai_sessions()


def _render_ai_history_list():
    lang_pack = T[st.session_state.lang]
    labels = {
        "delete": lang_pack["delete"],
        "rename": lang_pack["rename"],
        "pin": lang_pack["pin"],
        "unpin": lang_pack["unpin"],
        "pinned": lang_pack["pinned"],
        "untitled": lang_pack["untitled"],
        "empty": lang_pack["history_empty"],
    }
    res = ai_history_component(
        items=_ai_history_items(), labels=labels, key="ai_hist_list"
    )
    _handle_ai_history_action(res)


def render_ai_history():
    """AI 页右上角：时钟图标（历史记录）+ 对话图标（新对话），悬停显示灰色提示。"""
    lang_pack = T[st.session_state.lang]
    # 悬停提示文案跟随界面语言
    st.markdown(
        "<style>"
        f'.st-key-cg_hist_btn::after {{ content: "{lang_pack["history"]}"; }}'
        f'.st-key-cg_new_btn::after {{ content: "{lang_pack["new_chat"]}"; }}'
        '[data-testid="stPopoverBody"] { min-width: 340px; }'
        "</style>",
        unsafe_allow_html=True,
    )
    with st.container(key="cg_ai_topbar"):
        with st.container(key="cg_hist_btn"):
            with st.popover("🕘", use_container_width=False):
                _render_ai_history_list()
        with st.container(key="cg_new_btn"):
            if st.button("💬", key="ai_new_chat", use_container_width=False):
                start_new_ai_session()
                st.rerun()

# =========================================================
# helper functions
# =========================================================
def find_order_by_id(order_id):
    for o in orders:
        if o["order_id"].upper() == order_id.upper():
            return o
    return None

def extract_order_id(text):
    m = re.search(r"ORD-\d{3,}", text, flags=re.I)
    if m:
        return m.group(0).upper()
    m = re.search(r"(?<!\d)(\d{3,})(?!\d)", text)
    if m:
        return "ORD-" + m.group(1)
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

def get_order_answer(text, order):
    """根据问法（发货/物流/退款）和订单状态给出问答式回复，带订单号与状态标签。"""
    q = text.lower()
    oid = order["order_id"]
    status = order.get("status", "未发货")
    lang = st.session_state.lang
    pack = T[lang]
    label = localize_status(status, lang)

    if any(k in q for k in ["发货", "ship"]):
        if status == "未发货":
            return pack["status_ship_no"].format(order_id=oid)
        if status in ["已发货", "正在运输中", "待签收", "已签收"]:
            return pack["status_ship_yes"].format(order_id=oid, status=label)
        return pack["status_ship_after"].format(order_id=oid, status=label)

    if any(k in q for k in ["退款", "退货", "到账", "refund"]):
        if status in ["已退款", "已退货", "申请退款中", "申请退货中"]:
            return pack["status_refund_active"].format(order_id=oid, status=label)
        return pack["status_refund_none"].format(order_id=oid, status=label)

    # 默认：物流/状态
    tracking = order.get("tracking_number") or pack["status_no_tracking"]
    return pack["status_logistics"].format(
        order_id=oid, status=label,
        shipping_status=localize_shipping(order.get("shipping_status", ""), lang),
        logistics_info=localize_logistics(order.get("logistics_info", ""), lang),
        tracking=tracking,
    )

# 商品实体问题（损伤/质量/发错货）关键词：命中即走商家客服
DAMAGE_KEYWORDS = [
    "损坏", "破损", "坏", "烂", "碎", "裂", "漏", "污渍", "瑕疵", "锈", "变形", "变色",
    "质量", "次品", "假货", "少件", "少发", "缺件", "发错", "发成别的", "装错",
    "货不对板", "不是我要的", "压坏", "挤坏", "撞坏",
    "damaged", "broken", "rotten", "defective", "quality", "stain", "cracked",
    "wrong item", "wrong product", "wrong delivery", "sent wrong",
]

# 服务主体词表：句中出现「主体 + 消极行为」即判定商家未履行
SERVICE_SUBJECTS = [
    "商家", "店铺", "卖家", "网店", "店家", "店主", "店长", "客服", "这店", "这个店",
    "merchant", "seller", "store", "shop", "support",
]

# 消极行为词表（服务不履行/不配合）
SERVICE_NEGATIVES = [
    "拒绝", "不给退", "不让退", "不让我退", "不给我退", "退不了", "不予退", "不同意退", "被拒",
    "不处理", "没处理", "不解决", "不理", "不回复", "不回消息", "已读不回", "不回应", "失联", "没人管",
    "态度差", "态度不好", "态度很差", "态度恶劣", "态度敷衍", "说话难听", "难听", "凶", "不耐烦",
    "拖延", "拖沓", "拖", "太慢", "迟迟", "敷衍", "推诿", "甩锅", "踢皮球", "扯皮", "打太极", "忽悠",
    "refuse", "refused", "won't refund", "denied refund", "no reply", "ignored", "rude",
    "unhelpful", "slow", "delay", "dragging",
]


def detect_escalation(text):
    """判定该找谁：返回 'platform' / 'merchant' / None。

    - 商家未履行（主体 + 消极行为，或退款/退货被拖延）→ platform，优先于商品问题
    - 商品实体问题（损伤/发错货）→ merchant
    """
    q = text.lower()

    has_damage = any(k in q for k in DAMAGE_KEYWORDS)
    has_subject = any(k in q for k in SERVICE_SUBJECTS)
    has_negative = any(k in q for k in SERVICE_NEGATIVES)
    # 退款/退货语境下的拖延、拒绝，无需显式「商家」也视为商家未履行
    refund_stuck = (
        any(k in q for k in ["退款", "退货", "售后", "refund", "return"])
        and any(k in q for k in ["拖", "太慢", "迟迟", "一直没", "拒绝", "不给", "不让", "退不了"])
    )

    if (has_subject and has_negative) or refund_stuck:
        return "platform"
    if has_damage:
        return "merchant"
    return None


def escalation_context(order, pack):
    """升级结论后的背景附注：订单号 + 当前状态 + 退款流程状态。"""
    status = order.get("status", "未发货")
    lang = st.session_state.lang
    if status in ["申请退款中", "申请退货中"]:
        refund = pack["refund_in_progress"]
    elif status in ["已退款", "已退货"]:
        refund = pack["refund_done"]
    else:
        refund = pack["refund_none_now"]
    return pack["escalate_order_context"].format(
        order_id=order["order_id"], status=localize_status(status, lang), refund=refund
    )

def detect_intent(text):
    q = text.lower()

    if any(k in q for k in ["损坏","破损","坏了","damaged","damage","broken","发错货","发错了","wrong item","wrong product","wrong delivery","sent wrong","wrong goods","装错"]):
        if any(k in q for k in ["发错货","发错了","wrong item","wrong product","wrong delivery","sent wrong","wrong goods","装错"]):
            return "wrong_delivery"
        return "damage"

    if any(k in q for k in [
        "汇率", "换算", "兑换", "等于多少", "exchange", "rate", "currency", "convert", "how much",
        "人民币", "美元", "美金", "欧元", "英镑", "日元", "日币", "韩元", "韩币", "泰铢", "澳元", "澳币", "新币",
        "cny", "usd", "eur", "gbp", "jpy", "krw", "aud", "sgd", "thb",
    ]):
        # 必须同时出现「问汇率」的关键词，避免「35美元关税」被误判为汇率查询
        rate_keywords = ["汇率", "换算", "兑换", "等于多少", "exchange", "rate", "convert", "how much"]
        if any(k in q for k in rate_keywords):
            return "exchange_rate"
        # 或者出现明确的「A to B / A=B」格式
        if re.search(r"[a-z]{3}\s*[=≈]\s*[a-z]{3}", q) or re.search(r"[a-z]{3}\s+to\s+[a-z]{3}", q):
            return "exchange_rate"
        return None

    if any(k in q for k in ["状态","status","物流","delivery","where is","在哪","到哪","哪儿","哪里","track","tracking"]):
        return "status"

    if any(k in q for k in ["运费","shipping fee","邮费","delivery fee"]):
        return "shipping_fee"

    if any(k in q for k in ["退款","refund","退货"]):
        return "refund"

    if any(k in q for k in ["商家","卖家","merchant","seller"]):
        return "merchant_help"

    if any(k in q for k in ["平台","platform"]):
        return "platform_help"

    return "general"

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

def is_dispute_text(text):
    """出现纠纷信号时不走订单状态模板，交给维权参谋处理。"""
    s = (text or "").lower()
    signals = (
        "没收到", "未收到", "没拿到", "没有拿到", "没有收到", "未拿到", "没收到货", "没有收到货",
        "不见了", "包裹不见", "快递不见", "显示签收", "签收了但", "签收但没", "被拿", "丢了", "丢失",
        "签收异常", "没看到包裹", "没看到快递", "包裹找不到", "快递找不到",
        "弄坏", "损坏", "破损", "裂", "烂", "瑕疵", "发错", "错货", "少件", "缺件", "假货", "质量",
        "拒绝", "不退", "不让我", "不处理", "不回复", "敷衍", "拖延", "退款", "退货",
        "跑路", "倒闭", "关店", "店铺关闭", "注销", "失联", "联系不上", "找不到人", "人去楼空",
        "不发货", "没发货", "未发货", "打不开", "停止运营",
        "关税", "清关", "海关", "扣关", "税费", "停滞", "没更新", "没有更新", "退运费", "运费谁",
        "尺码", "尺寸不符", "货不对板", "误导", "隐瞒",
        "never received", "not received", "didn't receive", "not delivered", "damaged", "broken",
        "wrong item", "missing", "lost", "refund", "return",
        "届かない", "届いていない", "破損", "返金", "返品",
        "받지 못", "미수령", "파손", "환불", "반품",
        "pas reçu", "non reçu", "endommagé", "remboursement", "retour",
    )
    return any(k in s for k in signals)


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


def render_ai_text(text):
    """AI 回复：先转义 HTML，再渲染少量 Markdown（标题/加粗/列表/分隔线），保留换行。"""
    t = html.escape(text)
    t = re.sub(r"^\s*#{1,6}\s+(.+)$", r"<strong>\1</strong>", t, flags=re.M)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"^\s*(?:-|\*)\s+", "• ", t, flags=re.M)
    t = re.sub(r"^\s*(?:&gt;|>)\s*", "", t, flags=re.M)
    t = re.sub(r"^\s*---+\s*$", '<div style="border-top:1px solid #e5e7eb;margin:8px 0;"></div>', t, flags=re.M)
    return t


def render_messages(messages, show_read=False, translate=False):
    lang_pack = T[st.session_state.lang]
    html_parts = ['<div style="display:flex; flex-direction:column; gap:10px;">']
    for m in messages:
        raw = lang_pack[m["i18n"]] if m.get("i18n") else m.get("content", "")
        # AI 客服回复允许少量排版；商家/平台等其它消息一律按原文转义
        body = render_ai_text(raw) if (m["role"] == "ai" and not translate) else html.escape(raw)
        # 对方（商家/平台）消息：原文下方附所选语言译文；原文即所选语言则不显示
        if translate and m["role"] == "ai" and m.get("original_lang") != st.session_state.lang:
            translation = (m.get("translations") or {}).get(st.session_state.lang) or lang_pack["no_translation"]
            body += (
                '<div style="margin-top:6px;padding-top:6px;border-top:1px dashed #d1d5db;'
                'font-size:0.75rem;line-height:1.5;color:#000000;'
                'word-break:break-word;overflow-wrap:anywhere;white-space:pre-wrap;">'
                f'{lang_pack["translated"]}{html.escape(translation)}</div>'
            )
        for a in m.get("attachments", []):
            b64 = base64.b64encode(a["bytes"]).decode()
            if a["kind"] == "image":
                body += (
                    f'<img src="data:{a["mime"]};base64,{b64}" '
                    'style="max-width:220px; border-radius:12px; margin-top:8px; display:block;" />'
                )
            else:
                body += (
                    f'<video controls preload="metadata" src="data:{a["mime"]};base64,{b64}" '
                    'style="max-width:260px; border-radius:12px; margin-top:8px; display:block;"></video>'
                )
        if not body:
            body = "&nbsp;"
        ts = m.get("ts")
        ts_html = (
            f'<span style="font-size:0.68rem;color:#000000;white-space:nowrap;">{html.escape(ts)}</span>'
            if ts else ""
        )
        if m["role"] == "user":
            # 已读/未读状态：消息创建时写入 read 字段，未写入按未读处理
            read_mark = ""
            if show_read:
                is_read = bool(m.get("read", False))
                read_mark = (
                    f'<span style="font-size:0.68rem;color:#000000;white-space:nowrap;">'
                    f'{lang_pack["read"] if is_read else lang_pack["unread"]}</span>'
                )
            # 用户消息：浅灰圆角气泡靠右，时间戳在气泡下方
            html_parts.append(
                '<div style="display:flex; flex-direction:column; align-items:flex-end; gap:4px; width:100%;">'
                f'<div style="max-width:70%; background:#f1f2f4; color:#111827; padding:12px 16px; border-radius:18px; border-bottom-right-radius:6px; white-space:pre-wrap; word-break:break-word; overflow-wrap:anywhere;">{body}</div>'
                f'<div style="display:flex; gap:8px; align-items:center;">{ts_html}{read_mark}</div>'
                '</div>'
            )
        else:
            # AI / 对方回复：不加气泡，占满整个聊天宽度
            html_parts.append(
                '<div style="display:flex; flex-direction:column; align-items:flex-start; gap:2px; width:100%;">'
                f'<div style="width:100%; color:#111827; white-space:pre-wrap; word-break:break-word; overflow-wrap:anywhere;">{body}</div>'
                f'{ts_html}'
                '</div>'
            )
    html_parts.append('</div>')
    return "".join(html_parts)

def render_chat_panel(title, messages, show_read=True, translate=False, boxed=True):
    """输出聊天面板。

    boxed=False 时只渲染消息本身（无外框、无标题栏），用于 AI 页；
    boxed=True 时保留卡片式对话框，用于商家/平台客服。
    """
    bubbles = render_messages(messages, show_read=show_read, translate=translate)
    if not boxed:
        st.markdown(
            '<div class="cg-chat-scroll">' + bubbles + "</div>",
            unsafe_allow_html=True,
        )
        return
    online = T[st.session_state.lang]["status_online"]
    st.markdown(
        textwrap.dedent(f"""
        <div style="background:white; border:1px solid #e5e7eb; border-radius:18px;
        padding:12px; box-shadow:0 10px 20px rgba(15,23,42,0.04);">
            <div class="chat-header" style="margin:0 0 10px 0;">
                <div>{html.escape(title)}</div>
                <div style="color:#10b981;">● {online}</div>
            </div>
            <div class="chat-scroll" style="height:380px; overflow-y:auto; padding:0 6px 0 0;
            display:flex; flex-direction:column-reverse;">
                <div style="margin-bottom:auto; width:100%;">{bubbles}</div>
            </div>
        </div>
        """),
        unsafe_allow_html=True,
    )

MAX_ATTACHMENT_MB = 25
ATTACHMENT_TYPES = ["png", "jpg", "jpeg", "gif", "webp", "mp4", "mov", "webm"]

# 表情面板：常用 emoji，按分类分组（图片类表情包可后续在此扩展）
EMOJI_GROUPS = [
    ("emoji_smile", ["😀", "😄", "😅", "😂", "😊", "🙂", "😉", "🥰"]),
    ("emoji_gesture", ["👍", "👎", "🙏", "👏", "🙌", "🤝", "✌️", "👌"]),
    ("emoji_item", ["🎁", "📦", "🛒", "💳", "📷", "📱", "🎧", "👕"]),
    ("emoji_mood", ["😢", "😭", "😡", "😤", "😱", "🤔", "😴", "🤗"]),
]

def render_composer(page_key):
    """
    聊天输入行：左侧「+」附件按钮（popover 内上传图片/视频）+ 输入框 + 发送按钮。
    返回 (text, send_clicked, attachments)。附件在发送后由调用方清空。
    """
    att_key = f"{page_key}_attachments"
    seq_key = f"{page_key}_up_seq"
    lang_pack = T[st.session_state.lang]
    st.session_state.setdefault(att_key, [])
    st.session_state.setdefault(seq_key, 0)

    # 已选附件预览（可单个移除）
    atts = st.session_state[att_key]
    if atts:
        preview_cols = st.columns(min(len(atts), 6))
        for i, att in enumerate(atts):
            with preview_cols[i % 6]:
                if att["kind"] == "image":
                    st.image(att["bytes"], width=90)
                else:
                    st.markdown(f"🎬 **{att['name']}**  \n{att['size'] / 1024 / 1024:.1f}MB")
                if st.button("✕", key=f"{page_key}_rm_{i}_{att['name']}"):
                    st.session_state[att_key].pop(i)
                    st.rerun()

    c_plus, c_emoji, c_input, c_send = st.columns([0.7, 0.7, 6.6, 2], vertical_alignment="bottom")

    with c_plus:
        with st.popover("＋", use_container_width=True):
            st.caption(lang_pack["attach_caption"].format(mb=MAX_ATTACHMENT_MB))
            uploader_key = f"{page_key}_uploader_{st.session_state[seq_key]}"
            files = st.file_uploader(
                "attachments",
                type=ATTACHMENT_TYPES,
                accept_multiple_files=True,
                key=uploader_key,
                label_visibility="collapsed",
            )
            if files:
                for f in files:
                    if f.size > MAX_ATTACHMENT_MB * 1024 * 1024:
                        st.warning(lang_pack["attach_too_big"].format(name=f.name, mb=MAX_ATTACHMENT_MB))
                        continue
                    kind = "image" if f.type.startswith("image") else "video"
                    st.session_state[att_key].append(
                        {"name": f.name, "size": f.size, "kind": kind, "mime": f.type, "bytes": f.read()}
                    )
                # 轮换 uploader key，清空已消费的文件，避免重复添加
                st.session_state[seq_key] += 1
                st.rerun()

    with c_emoji:
        # 表情面板：点选后插入输入框（不直接发送，便于继续编辑）
        with st.popover("🙂", use_container_width=True):
            text_key = f"{page_key}_text"
            for group_key, emojis in EMOJI_GROUPS:
                st.markdown(
                    f"<div style='font-size:0.75rem;font-weight:700;color:#000000;margin:4px 0 2px;'>"
                    f"{lang_pack[group_key]}</div>",
                    unsafe_allow_html=True,
                )
                rows = [emojis[i:i + 4] for i in range(0, len(emojis), 4)]
                for r_i, row in enumerate(rows):
                    cols = st.columns(4)
                    for c_i, ch in enumerate(row):
                        if cols[c_i].button(ch, key=f"emoji_{page_key}_{group_key}_{r_i}_{c_i}"):
                            current = st.session_state.get(text_key, "") or ""
                            st.session_state[text_key] = current + ch
                            st.rerun()

    with c_input:
        text = st.text_input(
            "message",
            key=f"{page_key}_text",
            label_visibility="collapsed",
            placeholder=T[st.session_state.lang]["placeholder"],
        )

    with c_send:
        send_clicked = st.button(
            T[st.session_state.lang]["send"],
            key=f"{page_key}_send",
            use_container_width=True,
        )

    return text, send_clicked, list(st.session_state[att_key])


EMPTY_STATE_TEXT = {
    "en": ("How can I help you today?",
           "Ask me about cross-border orders, logistics issues, after-sales rights or return policies."),
    "zh": ("有什么可以帮助您？",
           "跨境订单、物流异常、售后维权与退换货法规，都可以问我。"),
    "ja": ("何をお手伝いしましょうか？",
           "越境注文・物流トラブル・アフターサービス・返品規約についてご相談ください。"),
    "ko": ("무엇을 도와드릴까요?",
           "해외 주문, 물류 문제, 애프터서비스 및 반품 규정에 대해 물어보세요."),
    "fr": ("Comment puis-je vous aider ?",
           "Commandes internationales, problèmes de logistique, service après-vente et retours."),
}


def render_ai_empty_state():
    """AI 页空态：居中欢迎语，仅在没有聊天记录时显示（跟随界面语言）。"""
    title, subtitle = EMPTY_STATE_TEXT.get(
        st.session_state.lang, EMPTY_STATE_TEXT["en"]
    )
    st.markdown(
        "<div class='cg-empty-fill' style='display:flex;flex-direction:column;align-items:center;"
        "justify-content:flex-start;padding-top:19vh;text-align:center;'>"
        f"<div style='font-size:1.9rem;font-weight:800;color:#000000;letter-spacing:.5px;'>{title}</div>"
        f"<div style='margin-top:10px;font-size:.92rem;color:#000000;'>{subtitle}</div>"
        "</div>",
        unsafe_allow_html=True,
    )


def render_chat_composer(page_key="ai"):
    """聊天页底部输入卡片：附件 + 表情 + 输入框（三个客服页共用）。

    - 无发送按钮：输入框内按回车即发送（单个 text_input 在 form 中回车提交）
    - 整体吸底（sticky），只有上方对话区滚动
    返回 (text, send_clicked, attachments)。
    """
    att_key = f"{page_key}_attachments"
    seq_key = f"{page_key}_up_seq"
    text_key = f"{page_key}_text"
    # 聊天页锁定整页滚动：只有对话区内部滚动，滚动条止于输入框上方
    st.markdown(
        "<style>"
        "[data-testid='stMain']{overflow:hidden !important;}"
        "[data-testid='stMain'] .block-container{"
        "padding-left:8px !important;padding-right:8px !important;max-width:100% !important;}"
        "[data-testid='stMain'] .block-container > [data-testid='stVerticalBlock']{"
        "padding-bottom:8px !important;}"
        ".cg-chat-scroll{height:var(--cg-chat-height,calc(100vh - 330px));min-height:80px;"
        "overflow-y:auto;box-sizing:border-box;padding:4px 6px 10px 2px;}"
        ".cg-empty-fill{height:var(--cg-chat-height,calc(100vh - 330px));min-height:80px;"
        "box-sizing:border-box;}"
        "</style>",
        unsafe_allow_html=True,
    )
    lang_pack = T[st.session_state.lang]
    st.session_state.setdefault(att_key, [])
    st.session_state.setdefault(seq_key, 0)

    with st.container(key="cg_chat_composer"):
        atts = st.session_state[att_key]
        if atts:
            preview_cols = st.columns(min(len(atts), 6))
            for i, att in enumerate(atts):
                with preview_cols[i % 6]:
                    if att["kind"] == "image":
                        st.image(att["bytes"], width=90)
                    else:
                        st.markdown(f"🎬 **{att['name']}**  \n{att['size'] / 1024 / 1024:.1f}MB")
                    if st.button("✕", key=f"{page_key}_rm_{i}_{att['name']}"):
                        st.session_state[att_key].pop(i)
                        st.rerun()

        with st.form(f"{page_key}_composer_form", clear_on_submit=True, border=False):
            text = st.text_input(
                "message",
                key=text_key,
                label_visibility="collapsed",
                placeholder=lang_pack["placeholder"],
            )
            send_clicked = st.form_submit_button("Send", use_container_width=True)

        c_plus, c_emoji, _ = st.columns([0.55, 0.55, 8.9])

        with c_plus:
            with st.popover("＋", use_container_width=True):
                st.caption(lang_pack["attach_caption"].format(mb=MAX_ATTACHMENT_MB))
                files = st.file_uploader(
                    "attachments",
                    type=ATTACHMENT_TYPES,
                    accept_multiple_files=True,
                    key=f"{page_key}_uploader_{st.session_state[seq_key]}",
                    label_visibility="collapsed",
                )
                if files:
                    for f in files:
                        if f.size > MAX_ATTACHMENT_MB * 1024 * 1024:
                            st.warning(lang_pack["attach_too_big"].format(name=f.name, mb=MAX_ATTACHMENT_MB))
                            continue
                        kind = "image" if f.type.startswith("image") else "video"
                        st.session_state[att_key].append(
                            {"name": f.name, "size": f.size, "kind": kind, "mime": f.type, "bytes": f.read()}
                        )
                    st.session_state[seq_key] += 1
                    st.rerun()

        with c_emoji:
            with st.popover("🙂", use_container_width=True):
                for group_key, emojis in EMOJI_GROUPS:
                    st.markdown(
                        f"<div style='font-size:0.75rem;font-weight:700;color:#000000;margin:4px 0 2px;'>"
                        f"{lang_pack[group_key]}</div>",
                        unsafe_allow_html=True,
                    )
                    rows = [emojis[i:i + 4] for i in range(0, len(emojis), 4)]
                    for r_i, row in enumerate(rows):
                        cols = st.columns(4)
                        for c_i, ch in enumerate(row):
                            if cols[c_i].button(ch, key=f"{page_key}_emoji_{group_key}_{r_i}_{c_i}"):
                                current = st.session_state.get(text_key, "") or ""
                                st.session_state[text_key] = current + ch
                                st.rerun()

    # 测量真实高度，把对话区撑到输入框正上方（避免不同分辨率下被裁切）
    fit_chat_component(key="cg_fit_chat", default=None, height=0)

    return text, send_clicked, list(st.session_state[att_key])

def clear_composer_attachments(page_key):
    st.session_state[f"{page_key}_attachments"] = []

def render_header(title, show_back=True):
    """页面标题栏与返回箭头已移除：右侧内容区不再显示任何标题文字。"""
    return


def render_back_button(key):
    """灰色、无边框的返回箭头（仅用于详情类页面）。"""
    val = back_arrow_component(key=f"cg_back_arrow_{key}", default=None)
    if isinstance(val, dict) and val.get("action") == "back":
        if st.session_state.get(f"cg_back_seq_{key}") != val.get("seq"):
            st.session_state[f"cg_back_seq_{key}"] = val.get("seq")
            go_back()
            st.rerun()

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
        padding: 14px 16px 10px 16px;
        box-sizing: border-box;
        box-shadow: 0 10px 28px rgba(15, 23, 42, 0.08);
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
        top: -18px !important;
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
# 各界面语言的全称（用于用户菜单语言行等需要完整语言名的展示）
LANG_NAMES = {"en": "English", "zh": "简体中文", "ja": "日本語", "ko": "한국어", "fr": "français"}

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
# AI 客服：CargoGuard 买家维权参谋
# =========================================================


def country_code_from_address(address):
    """从地址字符串中粗略识别收货/寄件国家码，用于 RAG 法规匹配。"""
    if not address:
        return ""
    a = address.lower()
    mapping = [
        ("中国", "CN"), ("china", "CN"), ("beijing", "CN"), ("shanghai", "CN"),
        ("guangzhou", "CN"), ("shenzhen", "CN"), ("chengdu", "CN"),
        ("美国", "US"), ("usa", "US"), ("u.s.a", "US"), ("new york", "US"),
        ("los angeles", "US"), ("california", "US"), ("ca, usa", "US"),
        ("英国", "GB"), ("uk", "GB"), ("united kingdom", "GB"), ("london", "GB"),
        ("日本", "JP"), ("japan", "JP"), ("tokyo", "JP"),
        ("韩国", "KR"), ("korea", "KR"), ("seoul", "KR"),
        ("法国", "FR"), ("france", "FR"), ("paris", "FR"),
        ("德国", "DE"), ("germany", "DE"), ("berlin", "DE"),
        ("泰国", "TH"), ("thailand", "TH"), ("bangkok", "TH"),
        ("欧盟", "EU"), ("europe", "EU"),
    ]
    for kw, code in mapping:
        if kw in a:
            return code
    return ""


def ai_order_context(order_obj, lang):
    """把命中的订单整理成给模型看的背景，避免模型凭空编造订单信息。"""
    if not order_obj:
        return ""
    ship_to = order_obj.get("shipping_address") or "-"
    ship_from = order_obj.get("origin_address") or "-"
    svc = order_services(order_obj)
    tags = []
    if svc.get("free_ship"):
        tags.append("包邮")
    if svc.get("tax_in"):
        tags.append("包税（DDP，进口税费由商家承担）")
    if svc.get("seven_day"):
        tags.append("7天无理由")
    service_txt = "、".join(tags) if tags else "无特殊服务承诺"
    delisted_txt = "｜⚠ 重要：该商品已下架、商品页面无法打开、店铺疑似关闭或失联（商家跑路风险），按跑路/失联商家流程处理" if is_delisted(order_obj) else ""
    return (
        f"订单背景：{order_obj['order_id']}｜商家：{order_obj.get('merchant','')}｜"
        f"商品：{order_obj.get('product_name','')}｜数量：{order_obj.get('quantity', 1)}｜"
        f"商品金额：{order_obj.get('currency','USD')} {float(order_obj.get('total_price', 0)):.2f}｜"
        f"寄件地：{ship_from}｜收件地：{ship_to}｜"
        f"下单时间：{order_obj.get('order_time') or '-'}｜"
        f"服务承诺：{service_txt}｜"
        f"当前状态：{localize_status(order_obj.get('status',''), lang)}"
        f"{delisted_txt}"
    )


def ai_history(limit=6):
    """取最近几轮对话作为上下文，跳过附件占位消息。"""
    history = []
    for m in st.session_state.ai_messages[-limit:]:
        content = m.get("content") or ""
        if not content:
            continue
        history.append({"role": "user" if m["role"] == "user" else "assistant", "content": content})
    return history


# =========================================================
# 页面分发
# =========================================================
# =========================================================
# 订单 / 商品详情渲染
# =========================================================
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


_PAY_BY_CURRENCY = {
    "USD": "Visa •••• 4242",
    "EUR": "Visa •••• 1881",
    "GBP": "Mastercard •••• 5506",
    "JPY": "JCB •••• 3090",
    "KRW": "Visa •••• 7712",
    "CNY": "Alipay",
}


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


def render_order_detail(order):
    picked = order_detail_component(
        order=order_detail_payload(order),
        lang=st.session_state.lang,
        key="cg_order_detail",
        default=None,
        height=760,
    )
    if isinstance(picked, dict) and picked.get("seq"):
        if picked["seq"] != st.session_state.get("cg_order_detail_seq"):
            st.session_state["cg_order_detail_seq"] = picked["seq"]
            if picked.get("action") == "back":
                go_back()
                st.rerun()
            elif picked.get("action") == "logistics" and picked.get("order_id"):
                st.session_state.logistics_order_id = picked["order_id"]
                goto("logistics")
                st.rerun()
            elif picked.get("action") == "merchant" and picked.get("order_id"):
                st.session_state.merchant_store_name = order.get("merchant") or picked["order_id"]
                goto("merchant_store")
                st.rerun()
            elif picked.get("order_id"):
                st.session_state.product_detail_id = picked["order_id"]
                goto("product_detail")
                st.rerun()


def render_logistics(order):
    """物流动态页：当前状态 + 物流单号 + 运输路线 + 竖向时间轴。"""
    lang = st.session_state.lang
    pack = LOG_T.get(lang, LOG_T["zh"])
    descs = LOG_NODE_DESC.get(lang, LOG_NODE_DESC["zh"])
    status = order.get("status") or "未发货"
    status_label = localize_status(status, lang)
    tracking = order.get("tracking_number") or ""
    origin = order.get("origin_address") or "-"
    dest = order.get("shipping_address") or "-"
    logistics_info = localize_logistics(order.get("logistics_info"), lang)

    route = f"{html.escape(origin)} → {html.escape(dest)}"

    timeline = build_timeline(order.get("order_time"), status)
    nodes = []
    for i, (key, node_time) in enumerate(timeline):
        last = i == len(timeline) - 1
        label = T[lang]["node_created"] if key == "created" else localize_status(key, lang)
        node_desc = descs.get(key, "")
        now_tag = f'<span class="cg-log-now">{html.escape(pack["now"])}</span>' if last else ""
        nodes.append(
            f'<div class="cg-log-node{" last" if last else ""}">'
            '<span class="cg-log-node-dot"></span>'
            f'<div class="cg-log-node-time">{fmt_datetime(node_time, lang)}</div>'
            f'<div class="cg-log-node-label">{html.escape(label)}{now_tag}</div>'
            + (f'<div class="cg-log-node-desc">{html.escape(node_desc)}</div>' if node_desc else "")
            + "</div>"
        )
    track_html = (
        '<div class="cg-log-track">' + "".join(nodes) + "</div>"
        if nodes
        else f'<div class="cg-log-empty">{html.escape(pack["no_tracking"])}</div>'
    )

    tracking_row = (
        f'<div class="cg-log-row"><span class="k">{html.escape(pack["tracking"])}</span>'
        f'<span class="v">{html.escape(tracking)}</span></div>'
        if tracking
        else ""
    )
    route_row = (
        f'<div class="cg-log-row"><span class="k">{html.escape(pack["route"])}</span>'
        f'<span class="v">{route}</span></div>'
    )
    info_html = (
        f'<div class="cg-log-route">{html.escape(logistics_info)}</div>'
        if logistics_info
        else ""
    )

    page_html = (
        "<style>"
        ".cg-log{max-width:820px;position:relative;}"
        ".cg-log-head{position:absolute;top:-44px;left:44px;height:34px;display:flex;"
        "align-items:center;font-size:1.15rem;font-weight:800;color:#111111;margin:0;}"
        ".cg-log-card{background:#ffffff;border:1px solid #ececec;border-radius:16px;"
        "padding:16px 18px;margin-bottom:12px;}"
        ".cg-log-status{display:flex;align-items:center;gap:9px;font-size:1.15rem;"
        "font-weight:800;color:#111111;margin-bottom:12px;}"
        ".cg-log-live{width:9px;height:9px;border-radius:50%;background:#111111;flex:0 0 9px;}"
        ".cg-log-row{display:flex;justify-content:space-between;gap:16px;font-size:0.82rem;"
        "padding:7px 0;border-bottom:1px solid #f4f4f4;}"
        ".cg-log-row:last-of-type{border-bottom:0;}"
        ".cg-log-row .k{color:#9a9a9a;white-space:nowrap;}"
        ".cg-log-row .v{color:#2f2f2f;text-align:right;word-break:break-all;}"
        ".cg-log-route{margin-top:9px;padding-top:9px;border-top:1px dashed #f0f0f0;"
        "font-size:0.78rem;color:#7c7c7c;line-height:1.6;}"
        ".cg-log-title{font-size:0.9rem;font-weight:800;color:#111111;margin-bottom:14px;}"
        ".cg-log-node{position:relative;padding-left:26px;padding-bottom:18px;}"
        ".cg-log-node:last-child{padding-bottom:0;}"
        ".cg-log-node:not(:last-child)::before{content:'';position:absolute;left:5px;top:14px;"
        "bottom:0;width:2px;background:#ededed;}"
        ".cg-log-node-dot{position:absolute;left:0;top:5px;width:12px;height:12px;"
        "border-radius:50%;background:#ffffff;border:2px solid #d9d9d9;}"
        ".cg-log-node.last .cg-log-node-dot{background:#111111;border-color:#111111;}"
        ".cg-log-node-time{font-size:0.72rem;color:#9a9a9a;margin-bottom:2px;}"
        ".cg-log-node-label{display:flex;align-items:center;gap:8px;font-size:0.88rem;"
        "font-weight:600;color:#4a4a4a;}"
        ".cg-log-node.last .cg-log-node-label{font-weight:800;color:#111111;}"
        ".cg-log-node-desc{font-size:0.76rem;color:#9a9a9a;margin-top:3px;line-height:1.55;}"
        ".cg-log-now{display:inline-block;font-size:0.66rem;font-weight:700;color:#111111;"
        "background:#f1f2f4;border-radius:999px;padding:2px 8px;}"
        ".cg-log-empty{font-size:0.82rem;color:#9a9a9a;}"
        "</style>"
        '<div class="cg-log">'
        f'<div class="cg-log-head">{html.escape(pack["title"])}</div>'
        '<div class="cg-log-card">'
        f'<div class="cg-log-status"><span class="cg-log-live"></span>'
        f"{html.escape(status_label)}</div>"
        f"{tracking_row}{route_row}{info_html}"
        "</div>"
        '<div class="cg-log-card">'
        f'<div class="cg-log-title">{html.escape(pack["movement"])}</div>'
        f"{track_html}"
        "</div>"
        "</div>"
    )
    st.markdown(page_html, unsafe_allow_html=True)


def merchant_stars(rating):
    full = max(0, min(5, int(round(rating))))
    return ('<span class="cg-ms-star">' + "★" * full + "</span>"
            + '<span class="cg-ms-star off">' + "★" * (5 - full) + "</span>")


def render_merchant_store(merchant):
    """商家主页：商家介绍 + 店铺商品 + 评论区（可发表评价）+ 举报 + 联系商家客服。"""
    lang = st.session_state.lang
    pack = MERCHANT_T.get(lang, MERCHANT_T["en"])
    profile = merchant_profile(merchant)
    user_reviews = st.session_state.setdefault("merchant_reviews", {}).setdefault(merchant, [])

    reviews = user_reviews + [
        {"author": item["author"], "rating": item["rating"],
         "date": (datetime.now() - timedelta(days=item["days"])).strftime("%Y-%m-%d"),
         "text": item["text"]}
        for item in profile["reviews"]
    ]
    count = len(reviews)
    avg = sum(item["rating"] for item in reviews) / count if count else 0.0

    # 评论原文保持发布语言；点击后由组件在上方展示当前语言翻译
    review_payload = []
    for item in reviews:
        text_ml = item["text"]
        if isinstance(text_ml, dict):
            origin = review_origin(item["author"])
            text = _pick(text_ml, origin)
            trans = _pick(text_ml, lang)
        else:
            origin = lang
            text = text_ml
            trans = text_ml
        review_payload.append({
            "author": item["author"],
            "rating": item["rating"],
            "date": item["date"],
            "location": _pick(REVIEW_LOCATIONS[origin], lang),
            "text": text,
            "trans": "" if origin == lang else trans,
            "langLabel": _pick(REVIEW_LANG_NAMES[origin], lang),
        })

    tag_html = "".join(
        f'<span class="cg-ms-tag">{html.escape(_pick(tag, lang))}</span>'
        for tag in profile["tags"]
    )
    product_html = "".join(
        '<div class="cg-ms-prod">'
        f'<div class="cg-ms-thumb">{html.escape(name[:1].upper())}</div>'
        f'<div class="cg-ms-prod-name">{html.escape(name)}</div>'
        f'<div class="cg-ms-prod-row"><span class="cg-ms-prod-price">{html.escape(price)}</span>'
        f'<span class="cg-ms-prod-sold">{html.escape(pack["sold"])} {sold:,}</span></div>'
        "</div>"
        for name, price, sold in (
            (_pick(p["name"], lang), p["price"], p["sold"]) for p in profile["products"]
        )
    )

    page_html = (
        "<style>"
        # 防止客服聊天区的内联高度随 React DOM 复用残留到商家主页
        ".cg-ms{max-width:none;height:auto !important;}"
        ".cg-ms-card{background:#ffffff;border:1px solid #ececec;border-radius:16px;"
        "padding:16px 18px;margin-bottom:12px;}"
        ".cg-ms-head{display:flex;gap:14px;align-items:flex-start;}"
        ".cg-ms-avatar{width:54px;height:54px;flex:0 0 54px;border-radius:16px;background:#f2f2f2;"
        "color:#8f8f8f;font-size:1.3rem;font-weight:800;display:flex;align-items:center;"
        "justify-content:center;}"
        ".cg-ms-main{flex:1 1 auto;min-width:0;}"
        ".cg-ms-name{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:1.15rem;"
        "font-weight:800;color:#111111;}"
        ".cg-ms-verified{font-size:0.66rem;font-weight:700;color:#2f9e5f;background:#eaf6ef;"
        "border-radius:999px;padding:2px 8px;}"
        ".cg-ms-rating{display:flex;align-items:center;gap:8px;margin-top:5px;font-size:0.8rem;"
        "color:#6f6f6f;}"
        ".cg-ms-star{color:#e08a3c;font-size:0.85rem;letter-spacing:1px;}"
        ".cg-ms-star.off{color:#e3e3e3;}"
        ".cg-ms-tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:9px;}"
        ".cg-ms-tag{font-size:0.7rem;color:#8a8a8a;background:#f4f4f4;border:1px solid #ededed;"
        "border-radius:6px;padding:2px 8px;}"
        ".cg-ms-sec{font-size:0.9rem;font-weight:800;color:#111111;margin-bottom:12px;}"
        ".cg-ms-intro{font-size:0.82rem;color:#5f5f5f;line-height:1.7;}"
        ".cg-ms-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;}"
        ".cg-ms-prod{border:1px solid #f0f0f0;border-radius:12px;padding:10px 12px;}"
        ".cg-ms-thumb{width:34px;height:34px;border-radius:9px;background:#f5f5f5;color:#a0a0a0;"
        "font-size:0.95rem;font-weight:800;display:flex;align-items:center;justify-content:center;"
        "margin-bottom:7px;}"
        ".cg-ms-prod-name{font-size:0.78rem;color:#2f2f2f;line-height:1.45;margin-bottom:5px;}"
        ".cg-ms-prod-row{display:flex;align-items:baseline;justify-content:space-between;gap:8px;}"
        ".cg-ms-prod-price{font-size:0.82rem;font-weight:800;color:#e08a3c;}"
        ".cg-ms-prod-sold{font-size:0.68rem;color:#9a9a9a;}"
        ".cg-ms-review{display:flex;gap:11px;padding:12px 0;border-top:1px solid #f4f4f4;}"
        ".cg-ms-review:first-child{border-top:0;padding-top:2px;}"
        ".cg-ms-r-avatar{width:30px;height:30px;flex:0 0 30px;border-radius:50%;background:#f2f2f2;"
        "color:#8f8f8f;font-size:0.75rem;font-weight:800;display:flex;align-items:center;"
        "justify-content:center;}"
        ".cg-ms-r-main{flex:1 1 auto;min-width:0;}"
        ".cg-ms-r-top{display:flex;align-items:center;gap:7px;flex-wrap:wrap;}"
        ".cg-ms-r-name{font-size:0.8rem;font-weight:700;color:#3a3a3a;}"
        ".cg-ms-r-date{margin-left:auto;font-size:0.68rem;color:#a6a6a6;}"
        ".cg-ms-r-stars{font-size:0.72rem;letter-spacing:1px;margin:2px 0 3px;}"
        ".cg-ms-r-text{font-size:0.78rem;color:#5f5f5f;line-height:1.65;}"
        ".cg-ms-empty{font-size:0.8rem;color:#9a9a9a;}"
        # 发表评价卡片（含评分控件的边框容器）
        "div[data-testid='stLayoutWrapper']:has([data-testid='stFeedback'])"
        " > div[data-testid='stVerticalBlock']{"
        "background:#ffffff !important;border:1px solid #ececec !important;"
        "border-radius:16px !important;padding:6px 18px 16px !important;"
        "margin-bottom:12px;}"
        # 举报 / 联系商家客服：浅灰色按钮
        "div[data-testid='stHorizontalBlock']:has([data-testid='stPopoverButton'])"
        " [data-testid='stPopoverButton'],"
        "div[data-testid='stHorizontalBlock']:has([data-testid='stPopoverButton'])"
        " .stButton > button{"
        "background:#f3f4f6 !important;background-image:none !important;"
        "border:1px solid #e5e7eb !important;color:#374151 !important;"
        "-webkit-text-fill-color:#374151 !important;height:38px !important;"
        "min-height:38px !important;border-radius:10px !important;"
        "font-weight:700;}"
        "div[data-testid='stHorizontalBlock']:has([data-testid='stPopoverButton'])"
        " [data-testid='stPopoverButton']:hover,"
        "div[data-testid='stHorizontalBlock']:has([data-testid='stPopoverButton'])"
        " .stButton > button:hover{"
        "background:#e9eaec !important;border-color:#dcdddf !important;"
        "color:#374151 !important;-webkit-text-fill-color:#374151 !important;}"
        # 发表评价按钮（primary 深灰）改为浅灰
        "div[data-testid='stLayoutWrapper']:has([data-testid='stFeedback'])"
        " .stButton > button{"
        "background:#f3f4f6 !important;background-image:none !important;"
        "border:1px solid #e5e7eb !important;color:#374151 !important;"
        "-webkit-text-fill-color:#374151 !important;font-weight:700;}"
        "div[data-testid='stLayoutWrapper']:has([data-testid='stFeedback'])"
        " .stButton > button:hover{"
        "background:#e9eaec !important;border-color:#dcdddf !important;"
        "color:#374151 !important;-webkit-text-fill-color:#374151 !important;}"
        # 评论区容器：与商家卡片保持一致的圆角与内边距
        "div[data-testid='stVerticalBlockBorderWrapper']:has(iframe[title*='merchant_reviews']){"
        "border:1px solid #ececec !important;border-radius:16px !important;"
        "background:#ffffff !important;padding:16px 18px !important;margin-bottom:12px;}"
        "</style>"
        '<div class="cg-ms">'
        '<div class="cg-ms-card cg-ms-head">'
        f'<div class="cg-ms-avatar">{html.escape(merchant.strip()[:1].upper())}</div>'
        '<div class="cg-ms-main">'
        f'<div class="cg-ms-name">{html.escape(merchant)}'
        f'<span class="cg-ms-verified">{html.escape(pack["verified"])}</span></div>'
        f'<div class="cg-ms-rating">{merchant_stars(profile["rating"])}'
        f'<span>{profile["rating"]:.1f}</span>'
        f'<span>{html.escape(pack["sold"])} {profile["sold"]:,}</span>'
        f'<span>{html.escape(pack["count"].format(n=count))}</span></div>'
        f'<div class="cg-ms-tags">{tag_html}</div>'
        "</div></div>"
        '<div class="cg-ms-card">'
        f'<div class="cg-ms-sec">{html.escape(pack["about"])}</div>'
        f'<div class="cg-ms-intro">{html.escape(_pick(profile["intro"], lang))}</div>'
        "</div>"
        '<div class="cg-ms-card">'
        f'<div class="cg-ms-sec">{html.escape(pack["products"])}</div>'
        f'<div class="cg-ms-grid">{product_html}</div>'
        "</div>"
        "</div>"
    )
    st.markdown(page_html, unsafe_allow_html=True)

    # 评论区：原文 + 点击在上方展开当前语言翻译
    with st.container(border=True):
        st.markdown(
            f'<div class="cg-ms-sec">{html.escape(pack["reviewsTitle"])}'
            f'<span class="cg-ms-star" style="margin-left:8px">{avg:.1f}</span></div>',
            unsafe_allow_html=True,
        )
        merchant_reviews_component(
            reviews=review_payload,
            labels={
                "translation": pack["translation"],
                "sameLang": pack["sameLang"],
                "click": pack["clickTrans"],
                "empty": pack["empty"],
            },
            key=f"cg_reviews_{merchant}",
            default=None,
        )

    with st.container(border=True):
        st.markdown(f'<div class="cg-ms-sec">{html.escape(pack["write"])}</div>',
                    unsafe_allow_html=True)
        rating = st.feedback("stars", key=f"cg_ms_stars_{merchant}")
        comment = st.text_area(pack["placeholder"], placeholder=pack["placeholder"],
                               key=f"cg_ms_text_{merchant}",
                               height=88, label_visibility="collapsed")
        if st.button(pack["submit"], key=f"cg_ms_submit_{merchant}", type="primary"):
            if rating is not None and comment.strip():
                user_reviews.insert(0, {
                    "author": pack["you"], "rating": rating + 1,
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "text": comment.strip(),
                })
                st.session_state["cg_ms_posted"] = True
                st.rerun()
            else:
                st.warning(pack["needRating"])

    if st.session_state.pop("cg_ms_posted", False):
        st.success(pack["posted"])

    with st.container():
        col_report, col_contact = st.columns(2)
        with col_report:
            # 提交后重新挂载一个关闭的 popover：表单消失，但举报按钮始终保留
            report_version = st.session_state.get("cg_ms_report_version", 0)
            with st.container(key=f"cg_ms_report_pop_{merchant}_{report_version}"):
                with st.popover(pack["report"], use_container_width=True):
                    # 用 form 包裹：选择原因/填写说明不触发 rerun，popover 不再闪退
                    with st.form(key=f"cg_ms_report_form_{merchant}", border=False):
                        st.radio(pack["reason"], pack["reasons"], key=f"cg_ms_reason_{merchant}")
                        st.text_area(pack["detail"], key=f"cg_ms_report_{merchant}", height=80)
                        if st.form_submit_button(pack["reportSubmit"], type="primary",
                                                 use_container_width=True):
                            st.session_state["cg_ms_report_version"] = report_version + 1
                            st.session_state["cg_ms_report_ok"] = True
                            st.rerun()
        with col_contact:
            if st.button(pack["contact"], key=f"cg_ms_contact_{merchant}",
                         use_container_width=True):
                st.session_state.selected_merchant = merchant
                goto("merchant_chat")
                st.rerun()

    if st.session_state.pop("cg_ms_report_ok", False):
        # 居中成功弹窗：淡入 → 3 秒后自动淡出；点击遮罩立即关闭（纯 CSS，无脚本依赖）
        # 每次用唯一 id/key，避免 React 复用旧 DOM 导致动画不重播
        uid = datetime.now().strftime("%H%M%S%f")
        with st.container(key=f"cg_rp_modal_{uid}"):
            st.markdown(
            "<style>"
            ".cg-rp-close{position:fixed;width:0;height:0;opacity:0;pointer-events:none;}"
            ".cg-rp-overlay{position:fixed;inset:0;z-index:999999;display:grid;place-items:center;"
            "animation:cgRpFadeIn .25s ease-out,cgRpFadeOut .35s ease-in 3s forwards;}"
            ".cg-rp-backdrop{position:absolute;inset:0;background:rgba(17,24,39,.45);cursor:pointer;}"
            ".cg-rp-modal{position:relative;background:#ffffff;border-radius:18px;padding:30px 42px;"
            "text-align:center;min-width:260px;box-shadow:0 20px 60px rgba(17,24,39,.20);"
            "animation:cgRpPop .3s ease-out;}"
            ".cg-rp-count{position:absolute;top:11px;right:13px;width:18px;height:18px;"
            "color:#9ca3af;font-size:12px;line-height:18px;font-weight:600;text-align:center;"
            "font-variant-numeric:tabular-nums;}"
            ".cg-rp-count span{position:absolute;inset:0;opacity:0;}"
            ".cg-rp-count span:nth-child(1){animation:cgRpCount3 3s linear forwards;}"
            ".cg-rp-count span:nth-child(2){animation:cgRpCount2 3s linear forwards;}"
            ".cg-rp-count span:nth-child(3){animation:cgRpCount1 3s linear forwards;}"
            ".cg-rp-icon{width:52px;height:52px;margin:0 auto 14px;border-radius:50%;background:#eaf6ef;"
            "display:flex;align-items:center;justify-content:center;}"
            ".cg-rp-icon svg{width:26px;height:26px;color:#2f9e5f;}"
            ".cg-rp-title{font-size:1.05rem;font-weight:800;color:#111827;margin-bottom:8px;}"
            ".cg-rp-desc{font-size:0.82rem;color:#6b7280;line-height:1.7;}"
            ".cg-rp-close:checked~.cg-rp-overlay{opacity:0;visibility:hidden;pointer-events:none;"
            "transition:opacity .25s ease-out,visibility 0s .25s;}"
            "@keyframes cgRpFadeIn{from{opacity:0;}to{opacity:1;}}"
            "@keyframes cgRpFadeOut{to{opacity:0;visibility:hidden;pointer-events:none;}}"
            "@keyframes cgRpPop{from{opacity:0;transform:translateY(12px) scale(.96);}"
            "to{opacity:1;transform:translateY(0) scale(1);}}"
            "@keyframes cgRpCount3{0%,33.32%{opacity:1;}33.33%,100%{opacity:0;}}"
            "@keyframes cgRpCount2{0%,33.32%{opacity:0;}33.33%,66.65%{opacity:1;}"
            "66.66%,100%{opacity:0;}}"
            "@keyframes cgRpCount1{0%,66.65%{opacity:0;}66.66%,100%{opacity:1;}}"
            "</style>"
            f'<input type="checkbox" id="cgRpClose{uid}" class="cg-rp-close">'
            '<div class="cg-rp-overlay">'
            f'<label for="cgRpClose{uid}" class="cg-rp-backdrop" aria-label="Close"></label>'
            '<div class="cg-rp-modal" role="alertdialog">'
            '<div class="cg-rp-count" aria-hidden="true"><span>3</span><span>2</span><span>1</span></div>'
            '<div class="cg-rp-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">'
            '<polyline points="4 12.5 9.5 18 20 6"/></svg></div>'
            f'<div class="cg-rp-title">{html.escape(pack["reportOkTitle"])}</div>'
            f'<div class="cg-rp-desc">{html.escape(pack["reportDone"])}</div>'
            "</div></div>",
            unsafe_allow_html=True,
            )


def render_product_detail(order):
    currency = order.get("currency", "USD")
    meta, spec = product_meta(order)

    if is_delisted(order):
        # 商家跑路/商品下架：页面打不开，显示下架警示
        st.markdown(
            '<div style="background:white;border:1px solid #e5e7eb;border-radius:18px;padding:32px 18px;'
            'text-align:center;filter:grayscale(0.6);opacity:0.85;">'
            '<div style="font-size:3rem;">📦</div>'
            f'<div style="margin-top:8px;font-size:1.05rem;font-weight:800;color:#000000;">{html.escape(order.get("product_name") or "")}</div>'
            f'<div style="margin-top:6px;color:#000000;font-size:0.85rem;">{ux("merchant")}: {html.escape(order.get("merchant") or "")}</div>'
            '</div>'
            '<div style="margin-top:16px;background:#fef2f2;border:1px solid #fecaca;border-radius:18px;padding:16px 18px;">'
            '<div style="font-size:0.95rem;font-weight:800;color:#b91c1c;margin-bottom:6px;">⚠ '
            + ('该商品已下架' if st.session_state.lang == 'zh' else 'Item removed') + '</div>'
            f'<div style="color:#7f1d1d;font-size:0.85rem;line-height:1.8;">{html.escape(ux("delisted_notice"))}</div></div>',
            unsafe_allow_html=True,
        )
        return

    desc = PRODUCT_DESC.get(meta.get("cat", "generic"), PRODUCT_DESC["generic"]).get(
        st.session_state.lang, PRODUCT_DESC["generic"]["en"]
    )
    st.markdown(
        '<div style="background:white;border:1px solid #e5e7eb;border-radius:18px;padding:18px;">'
        '<div style="display:flex;gap:18px;align-items:flex-start;">'
        f'{_product_thumb_html(order, size=180, radius=16)}'
        '<div style="flex:1;">'
        f'<div style="font-size:1.05rem;font-weight:800;">{html.escape(order.get("product_name") or "")}</div>'
        f'<div style="margin-top:8px;color:#111827;font-size:1.15rem;font-weight:800;">{currency} {float(order.get("unit_price", 0)):.2f}</div>'
        f'<div style="margin-top:8px;color:#000000;font-size:0.8rem;">{ux("merchant")}: {html.escape(order.get("merchant") or "")}</div>'
        f'<div style="margin-top:4px;color:#000000;font-size:0.8rem;">{ux("spec")}: {html.escape(spec)}</div>'
        f'<div style="margin-top:4px;color:#000000;font-size:0.8rem;">{ux("qty")}: {order.get("quantity", 1)} · {ux("subtotal")}: {currency} {float(order.get("total_price", 0)):.2f}</div>'
        '</div></div></div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div style="margin-top:16px;background:white;border:1px solid #e5e7eb;border-radius:18px;padding:16px 18px;">'
        f'<div style="font-size:0.95rem;font-weight:800;margin-bottom:10px;">{ux("service_title")}</div>'
        f'{service_tags_html(order)}</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div style="margin-top:16px;background:white;border:1px solid #e5e7eb;border-radius:18px;padding:16px 18px;">'
        f'<div style="font-size:0.95rem;font-weight:800;margin-bottom:8px;">{ux("desc_title")}</div>'
        f'<div style="color:#000000;font-size:0.85rem;line-height:1.8;">{html.escape(desc)}</div></div>',
        unsafe_allow_html=True,
    )

    # 商品评论区：与商家详情一致（原文展示 + 点击查看当前语言翻译 + 发表评价）
    lang = st.session_state.lang
    pack = MERCHANT_T.get(lang, MERCHANT_T["en"])
    profile = merchant_profile(order.get("merchant") or "")
    pool = profile.get("reviews") or []
    item_key = f'{order.get("order_id") or ""}_{order.get("product_name") or ""}'
    store = st.session_state.setdefault("cg_product_reviews", {})
    user_reviews = store.setdefault(item_key, [])

    if pool:
        start = sum(ord(c) for c in (order.get("product_name") or "")) % len(pool)
        rotated = pool[start:] + pool[:start]
    else:
        rotated = []
    base_reviews = [
        {"author": item["author"], "rating": item["rating"],
         "date": (datetime.now() - timedelta(days=item["days"])).strftime("%Y-%m-%d"),
         "text": item["text"]}
        for item in rotated[:4]
    ]
    all_reviews = user_reviews + base_reviews
    avg = sum(item["rating"] for item in all_reviews) / len(all_reviews) if all_reviews else 0.0

    payload = []
    for item in all_reviews:
        text_ml = item["text"]
        if isinstance(text_ml, dict):
            origin = review_origin(item["author"])
            text = _pick(text_ml, origin)
            trans = _pick(text_ml, lang)
        else:
            origin = lang
            text = text_ml
            trans = text_ml
        payload.append({
            "author": item["author"],
            "rating": item["rating"],
            "date": item["date"],
            "location": _pick(REVIEW_LOCATIONS[origin], lang),
            "text": text,
            "trans": "" if origin == lang else trans,
        })

    st.markdown(
        "<style>"
        "div[data-testid='stVerticalBlockBorderWrapper']:has(iframe[title*='merchant_reviews']){"
        "border:1px solid #e5e7eb !important;border-radius:18px !important;"
        "background:#ffffff !important;padding:16px 18px !important;margin-top:16px;}"
        "</style>",
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        st.markdown(
            f'<div style="font-size:0.95rem;font-weight:800;color:#111111;margin-bottom:10px;">'
            f'{html.escape(pack["reviewsTitle"])}'
            f'<span style="color:#e08a3c;margin-left:8px;">{avg:.1f}</span></div>',
            unsafe_allow_html=True,
        )
        merchant_reviews_component(
            reviews=payload,
            labels={
                "translation": pack["translation"],
                "sameLang": pack["sameLang"],
                "click": pack["clickTrans"],
                "empty": pack["empty"],
            },
            key=f"cg_pd_reviews_{item_key}",
            default=None,
        )

    with st.container(border=True):
        st.markdown(
            f'<div style="font-size:0.95rem;font-weight:800;color:#111111;margin-bottom:10px;">'
            f'{html.escape(pack["write"])}</div>',
            unsafe_allow_html=True,
        )
        rating = st.feedback("stars", key=f"cg_pd_stars_{item_key}")
        comment = st.text_area(
            pack["placeholder"], placeholder=pack["placeholder"],
            key=f"cg_pd_text_{item_key}", height=88, label_visibility="collapsed",
        )
        if st.button(pack["submit"], key=f"cg_pd_submit_{item_key}", type="primary"):
            if rating is not None and comment.strip():
                user_reviews.insert(0, {
                    "author": pack["you"], "rating": rating + 1,
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "text": comment.strip(),
                })
                st.session_state["cg_pd_posted"] = True
                st.rerun()
            else:
                st.warning(pack["needRating"])

    if st.session_state.pop("cg_pd_posted", False):
        st.success(pack["posted"])

    # 风险提示固定为商品详情最后一个内容区块
    st.markdown(risk_block_html(order), unsafe_allow_html=True)


# 页面切换不再做整体淡入：Streamlit 重渲染时整块从透明渐现会看起来像“闪一下”，
# 交给导航组件自身的展开动画做过渡即可。

if st.session_state.page == "ai":
    render_header(T[st.session_state.lang]["ai"], show_back=False)
    render_ai_history()
    if any(m["role"] == "user" for m in st.session_state.ai_messages):
        render_chat_panel(T[st.session_state.lang]["ai"], st.session_state.ai_messages, show_read=False, boxed=False)
    else:
        render_ai_empty_state()

    user_input, send_clicked, attachments = render_chat_composer("ai")
    if send_clicked and (user_input.strip() or attachments):
        lang_pack = T[st.session_state.lang]
        text = user_input.strip()
        intent = detect_intent(text) if text else "general"
        order_id = resolve_order_id(text, orders) if text else None
        order_ref = extract_order_id(text) if text else None

        # 优先级：商家服务问题→平台 / 商品损伤或发错货→商家 / 订单状态物流 / 汇率 / 兜底
        esc = detect_escalation(text) if text else None

        # 附件先做视觉识别：图片→事实摘要，视频明确说明需截帧
        vision_notes = None
        if attachments:
            with st.spinner(lang_pack["analyzing"]):
                vision_notes = describe_attachments(attachments)

        # 文本里没提到订单号时，从图片识别结果里兜底提取（截图含订单号的常见场景）
        if not order_id and vision_notes:
            order_id = resolve_order_id(vision_notes, orders)
            if order_id:
                order_ref = order_id

        order_obj = find_order_by_id(order_id) if order_id else None

        full_reply = None
        needs_disclaimer = False

        # 纯查询保持本地确定性回答，不让模型改写订单事实；纠纷/维权类交给 CargoGuard
        pure_query = bool(order_id) and not is_dispute_text(text)
        if not attachments and esc is None and pure_query:
            full_reply = get_order_answer(text, order_obj) if order_obj else lang_pack["order_not_found"].format(order_id=order_id)
        elif not attachments and esc is None and not is_dispute_text(text) and order_ref and not order_obj and any(
            k in text.lower() for k in ["发货", "物流", "订单", "到哪", "状态", "签收", "ship", "track", "order", "deliver"]
        ):
            # 订单号格式对但系统里查不到：只回一句查不到，不进入维权流程
            full_reply = lang_pack["order_not_found"].format(order_id=order_ref)
        elif not attachments and intent == "exchange_rate":
            full_reply = get_rate_answer(text)

        # 其余（纠纷、维权、附件求助）走 CargoGuard 人设
        if full_reply is None and has_llm():
            try:
                full_reply = cargoguard_answer(
                    text,
                    LANG_NAMES[st.session_state.lang],
                    ai_order_context(order_obj, st.session_state.lang),
                    vision_notes,
                    ai_history(),
                    tool_context={"order": {**order_obj, "services": order_services(order_obj), "delisted": is_delisted(order_obj), "merchant_unreachable": is_delisted(order_obj)}} if order_obj else None,
                )
                needs_disclaimer = True
            except Exception:
                full_reply = None

        # 模型不可用时回退到本地规则
        if full_reply is None:
            if esc == "platform":
                full_reply = lang_pack["escalate_platform"]
                if order_obj:
                    full_reply += "\n\n" + escalation_context(order_obj, lang_pack)
                full_reply += "\n\n" + lang_pack["escalate_platform_materials"]
                needs_disclaimer = True
            elif esc == "merchant":
                full_reply = lang_pack["escalate_merchant"]
                if order_obj:
                    full_reply += "\n\n" + escalation_context(order_obj, lang_pack)
                needs_disclaimer = True
            elif attachments:
                full_reply = lang_pack["attachment_ack"].format(n=len(attachments))
            elif any(k in (text or "").lower() for k in ["发货", "退款", "退货", "到账", "物流", "到哪", "状态", "ship", "refund", "track"]):
                full_reply = lang_pack["order_not_found_bare"]
            elif intent != "general":
                full_reply = lang_pack["ai_fallback"] + lang_pack["order_hint"]
            else:
                full_reply = lang_pack["ai_fallback"]

        # 免责提示只在维权类回复末尾追加，简单订单/汇率查询不加
        full_reply = strip_self_disclaimer(full_reply)
        if needs_disclaimer:
            full_reply += "\n\n" + lang_pack["disclaimer"]

        st.session_state.ai_messages.append({"role": "user", "content": text, "attachments": attachments, "ts": _now_ts()})
        st.session_state.ai_messages.append({"role": "ai", "content": full_reply, "ts": _now_ts()})
        touch_ai_title(text)
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