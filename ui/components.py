"""Streamlit 自定义组件声明与聊天/订单页面渲染。

组件资源位于项目根目录的 components/ 下，因此从 ui/ 向上取一层作为 ROOT。
"""

import base64
import html
import json
import os
import re
import textwrap
from contextlib import nullcontext
from datetime import datetime, timedelta

import streamlit as st
import streamlit.components.v1 as components

from ui.catalog import PRODUCT_DESC, REVIEW_LOCATIONS
from ui.copy import (
    EMPTY_STATE_TEXT, LANG_NAMES, LOG_NODE_DESC, LOG_T, MERCHANT_T,
    REVIEW_LANG_NAMES, T,
)
from ui.html import (
    _pick, _product_thumb_html, build_timeline, fmt_datetime, is_delisted,
    localize_logistics, localize_status, merchant_profile, merchant_stars,
    order_detail_payload, order_services, product_meta, review_origin,
    risk_block_html, service_tags_html, ux,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@st.cache_resource
def _nav_component():
    _dir = os.path.join(
        ROOT, "components", "nav_panel"
    )
    return components.declare_component("cargoguard_nav", path=_dir)


nav_component = _nav_component()


@st.cache_resource
def _order_list_component():
    _dir = os.path.join(
        ROOT, "components", "order_inquiry"
    )
    return components.declare_component("cargoguard_orders", path=_dir)


order_list_component = _order_list_component()


@st.cache_resource
def _fit_chat_component():
    _dir = os.path.join(
        ROOT, "components", "fit_chat"
    )
    return components.declare_component("cargoguard_fit_chat", path=_dir)


fit_chat_component = _fit_chat_component()


@st.cache_resource
def _order_views_component():
    _dir = os.path.join(
        ROOT, "components", "order_views"
    )
    return components.declare_component("cargoguard_order_views", path=_dir)


order_views_component = _order_views_component()


@st.cache_resource
def _back_arrow_component():
    _dir = os.path.join(
        ROOT, "components", "back_arrow"
    )
    return components.declare_component("cargoguard_back_arrow", path=_dir)


back_arrow_component = _back_arrow_component()


@st.cache_resource
def _order_detail_component():
    _dir = os.path.join(
        ROOT, "components", "order_detail"
    )
    return components.declare_component("cargoguard_order_detail", path=_dir)


order_detail_component = _order_detail_component()


@st.cache_resource
def _merchant_reviews_component():
    _dir = os.path.join(
        ROOT, "components", "merchant_reviews"
    )
    return components.declare_component("cargoguard_merchant_reviews", path=_dir)


merchant_reviews_component = _merchant_reviews_component()


@st.cache_resource
def _sidebar_toggle_component():
    _dir = os.path.join(
        ROOT, "components", "sidebar_toggle"
    )
    return components.declare_component("cargoguard_sidebar_toggle", path=_dir)


sidebar_toggle_component = _sidebar_toggle_component()


@st.cache_resource
def _ai_history_component():
    _dir = os.path.join(
        ROOT, "components", "ai_history"
    )
    return components.declare_component("cargoguard_ai_history", path=_dir)


ai_history_component = _ai_history_component()


def _now_ts():
    """消息时间戳：HH:MM，随消息保存。"""
    return datetime.now().strftime("%H:%M")


HISTORY_FILE = os.path.join(ROOT, "ai_history.json")


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
        # AI 回复底部的来源明细：蓝色小字，含规则/法案名与适用国家或地区
        sources = m.get("sources") or []
        if m["role"] == "ai" and sources:
            rows = []
            # 标点也跟随界面语言：中文用全角，其他语言用半角
            cjk = st.session_state.lang == "zh"
            colon, lpar, rpar = ("：", "（", "）") if cjk else (": ", " (", ")")
            for s in sources:
                title = html.escape((s.get("title") or s.get("source") or "").strip())
                desc = html.escape((s.get("desc") or "").strip())
                country = html.escape((s.get("country") or "").strip())
                detail = f"{title}{colon}{desc}" if (title and desc) else (title or desc)
                if country:
                    detail = f"{detail}{lpar}{country}{rpar}" if detail else country
                if detail:
                    rows.append(f"<div>· {detail}</div>")
            if rows:
                body += (
                    '<div style="margin-top:10px;padding-top:8px;border-top:1px dashed #dbeafe;'
                    'font-size:0.72rem;line-height:1.65;color:#2563eb;">'
                    f'<div>{html.escape(lang_pack.get("sources_label", "Sources"))}</div>'
                    + "".join(rows)
                    + "</div>"
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


_LIVE_CSS = (
    "<style>"
    "@keyframes cgBlink{0%,49%{opacity:1}50%,100%{opacity:0}}"
    ".cg-cursor{display:inline-block;color:#2563eb;animation:cgBlink 1s step-end infinite;"
    "margin-left:1px;font-weight:600;}"
    "@keyframes cgDot{0%,80%,100%{opacity:.25}40%{opacity:1}}"
    ".cg-typing-dots{display:inline-flex;gap:3px;align-items:center;}"
    ".cg-typing-dots i{width:5px;height:5px;border-radius:50%;background:#6b7280;"
    "display:inline-block;animation:cgDot 1.2s infinite;}"
    ".cg-typing-dots i:nth-child(2){animation-delay:.2s;}"
    ".cg-typing-dots i:nth-child(3){animation-delay:.4s;}"
    "</style>"
)


def _live_bubble(live_text="", live_status=""):
    if live_text:
        return (
            '<div style="display:flex;flex-direction:column;align-items:flex-start;gap:2px;width:100%;">'
            '<div style="width:100%;color:#111827;white-space:pre-wrap;word-break:break-word;'
            f'overflow-wrap:anywhere;">{render_ai_text(live_text)}<span class="cg-cursor">▌</span></div>'
            "</div>"
        )
    if live_status:
        return (
            '<div style="display:flex;align-items:center;gap:8px;color:#6b7280;font-size:.85rem;'
            'padding:4px 2px;"><span class="cg-typing-dots"><i></i><i></i><i></i></span>'
            f"<span>{html.escape(live_status)}</span></div>"
        )
    return ""


def _wrap_scroll(bubbles, live_status="", live_text=""):
    live = _live_bubble(live_text, live_status)
    if live:
        bubbles = _LIVE_CSS + bubbles + live
    # 外层 column-reverse：内容不足时贴底（紧邻输入框），超出时自动停在最新一条
    return (
        '<div class="cg-chat-scroll">'
        '<div style="width:100%;">' + bubbles + "</div></div>"
    )


def make_chat_drawer(placeholder, messages, show_read=False, translate=False):
    """预渲染历史消息，返回可反复调用的绘制函数（只更新末尾的实时气泡）。

    逐字输出时避免每帧重新编码附件 base64，明显更流畅。
    """
    base = render_messages(messages, show_read=show_read, translate=translate)

    def draw(live_status="", live_text=""):
        placeholder.markdown(
            _wrap_scroll(base, live_status=live_status, live_text=live_text),
            unsafe_allow_html=True,
        )

    return draw


def chat_scroll_html(messages, show_read=False, translate=False, live_status="", live_text=""):
    """聊天记录 HTML；live_text/live_status 用于流式输出时追加的“正在输入”气泡。"""
    bubbles = render_messages(messages, show_read=show_read, translate=translate)
    return _wrap_scroll(bubbles, live_status=live_status, live_text=live_text)


def render_chat_panel(title, messages, show_read=True, translate=False, boxed=True, live_status="", live_text=""):
    """输出聊天面板。

    boxed=False 时只渲染消息本身（无外框、无标题栏），用于 AI 页；
    boxed=True 时保留卡片式对话框，用于商家/平台客服。
    """
    if not boxed:
        st.markdown(
            chat_scroll_html(messages, show_read=show_read, translate=translate,
                             live_status=live_status, live_text=live_text),
            unsafe_allow_html=True,
        )
        return
    online = T[st.session_state.lang]["status_online"]
    bubbles = render_messages(messages, show_read=show_read, translate=translate)
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


def empty_state_html():
    """AI 页空态 HTML（可放入 st.empty() 占位符中重绘）。"""
    title, subtitle = EMPTY_STATE_TEXT.get(
        st.session_state.lang, EMPTY_STATE_TEXT["en"]
    )
    return (
        "<div class='cg-empty-fill' style='display:flex;flex-direction:column;align-items:center;"
        "justify-content:flex-start;padding-top:19vh;text-align:center;'>"
        f"<div style='font-size:1.9rem;font-weight:800;color:#000000;letter-spacing:.5px;'>{title}</div>"
        f"<div style='margin-top:10px;font-size:.92rem;color:#000000;'>{subtitle}</div>"
        "</div>"
    )


def render_ai_empty_state():
    """AI 页空态：居中欢迎语，仅在没有聊天记录时显示（跟随界面语言）。"""
    st.markdown(empty_state_html(), unsafe_allow_html=True)


def render_approval_card(approval):
    """渲染当前会话的人工审批卡片，返回审批决定或 None。"""
    pack = T[st.session_state.lang]
    request = approval.get("request") or approval
    status = approval.get("status", "pending")
    approval_id = str(approval.get("id") or "current")
    editable = status == "pending"
    tool = str(request.get("tool") or "")
    case_type = str(request.get("case_type") or "other")
    priority = str(request.get("priority") or "normal")

    with st.container(key="cg_hitl_card", border=True):
        title_col, status_col = st.columns([5, 1.5], vertical_alignment="center")
        with title_col:
            st.markdown(f"**{pack['hitl_title']}**")
        with status_col:
            st.markdown(f"**{pack.get('hitl_' + status, status)}**")

        st.markdown(f"**{pack.get('hitl_tool_' + tool, tool)}**")
        st.caption(pack["hitl_description"])
        order_col, case_col, priority_col = st.columns(3)
        with order_col:
            st.markdown(f"**{pack['order_id']}**  \n{request.get('order_id') or '-'}")
        with case_col:
            st.markdown(
                f"**{pack['hitl_case_label']}**  \n"
                f"{pack.get('hitl_case_' + case_type, case_type)}"
            )
        with priority_col:
            st.markdown(
                f"**{pack['hitl_priority_label']}**  \n"
                f"{pack.get('hitl_priority_' + priority, priority)}"
            )
        st.markdown(f"**{pack['hitl_reason_label']}**")
        st.write(request.get("reason") or "-")

        if status in {"pending", "processing"}:
            reviewer = st.text_input(
                pack["hitl_reviewer_label"],
                value=approval.get("reviewer") or "operator",
                max_chars=40,
                key=f"hitl_reviewer_{approval_id}",
                disabled=not editable,
            )
            note = st.text_area(
                pack["hitl_note_label"],
                value=approval.get("note") or "",
                placeholder=pack["hitl_note_placeholder"],
                max_chars=200,
                key=f"hitl_note_{approval_id}",
                disabled=not editable,
            )
            approved = st.button(
                pack["hitl_approve"],
                key=f"hitl_approve_{approval_id}",
                type="primary",
                disabled=not editable,
                use_container_width=True,
            )
            rejected = st.button(
                pack["hitl_reject"],
                key=f"hitl_reject_{approval_id}",
                disabled=not editable,
                use_container_width=True,
            )
            if approved or rejected:
                return approved, reviewer.strip() or "operator", note.strip()
        else:
            reviewer = approval.get("reviewer") or "operator"
            st.caption(f"{pack['hitl_reviewer_label']}：{reviewer}")
            if approval.get("note"):
                st.caption(f"{pack['hitl_note_label']}：{approval['note']}")
            if approval.get("summary"):
                st.markdown(f"**{pack['hitl_result_label']}**")
                st.write(approval["summary"])
    return None


def render_chat_composer(page_key="ai", disabled=False, docked=False):
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
        ".cg-chat-scroll{height:var(--cg-chat-height,calc(100vh - 240px));min-height:80px;"
        "overflow-y:auto;box-sizing:border-box;padding:4px 6px 10px 2px;"
        # column-reverse 让滚动位置默认停在底部：新内容追加时视图自动跟随最新消息
        "display:flex;flex-direction:column-reverse;}"
        ".cg-empty-fill{height:var(--cg-chat-height,calc(100vh - 240px));min-height:80px;"
        "box-sizing:border-box;}"
        "</style>",
        unsafe_allow_html=True,
    )
    lang_pack = T[st.session_state.lang]
    st.session_state.setdefault(att_key, [])
    st.session_state.setdefault(seq_key, 0)

    with nullcontext() if docked else st.container(key="cg_chat_composer"):
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

        if disabled:
            st.caption(lang_pack["hitl_input_locked"])
        with st.form(f"{page_key}_composer_form", clear_on_submit=True, border=False):
            text = st.text_input(
                "message",
                key=text_key,
                label_visibility="collapsed",
                placeholder=lang_pack["placeholder"],
                disabled=disabled,
            )
            send_clicked = st.form_submit_button(
                "Send", use_container_width=True, disabled=disabled
            )

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
                    disabled=disabled,
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
                            if cols[c_i].button(
                                ch,
                                key=f"{page_key}_emoji_{group_key}_{r_i}_{c_i}",
                                disabled=disabled,
                            ):
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


def ai_user_id():
    """长期记忆隔离键：登录账户与游客各自独立。"""
    return "account" if st.session_state.get("is_logged_in", True) else "guest"


def ai_thread_id():
    """短期记忆隔离键：同一账户的不同历史会话各自独立。"""
    return f"{ai_user_id()}:{st.session_state.ai_active}"


def ai_extra_context(order_obj, vision_notes):
    """给 Agent 的补充背景：界面语言、订单服务承诺、店铺状态、附件识别结果。"""
    blocks = [f"界面语言偏好：{LANG_NAMES[st.session_state.lang]}（必须使用该语言回答，即使买家消息或历史记录使用其他语言）"]
    if order_obj:
        svc = order_services(order_obj)
        tags = []
        if svc.get("free_ship"):
            tags.append("包邮")
        if svc.get("tax_in"):
            tags.append("包税（DDP，进口税费由商家承担）")
        if svc.get("seven_day"):
            tags.append("7天无理由")
        if tags:
            blocks.append("订单服务承诺：" + "、".join(tags))
        if is_delisted(order_obj):
            blocks.append("店铺状态：商品已下架、店铺疑似关闭或失联，按跑路/失联商家流程处理")
    if vision_notes:
        blocks.append("附件识别结果：\n" + vision_notes)
    return "\n".join(blocks)


def ai_prior_history(limit=12):
    """把界面历史转成 Agent 对话历史；断点丢失时用于恢复上下文。"""
    history = []
    for m in st.session_state.ai_messages[-limit:]:
        content = (m.get("content") or "").strip()
        if not content:
            continue
        history.append({
            "role": "user" if m.get("role") == "user" else "assistant",
            "content": content,
        })
    return history


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
