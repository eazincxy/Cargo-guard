"""模型调用：DeepSeek 负责维权策略，SiliconFlow Qwen3-VL 负责读图。"""
import base64
import json
import os
import urllib.error
import urllib.request

from app.kb import search as kb_search

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_COUNTRY_KEYWORDS = [
    ("中国", "CN"), ("china", "CN"), ("beijing", "CN"), ("shanghai", "CN"),
    ("guangzhou", "CN"), ("shenzhen", "CN"), ("chengdu", "CN"),
    ("美国", "US"), ("usa", "US"), ("u.s.a", "US"), ("new york", "US"),
    ("los angeles", "US"), ("california", "US"),
    ("英国", "GB"), (" uk", "GB"), ("united kingdom", "GB"), ("london", "GB"),
    ("日本", "JP"), ("japan", "JP"), ("tokyo", "JP"),
    ("韩国", "KR"), ("korea", "KR"), ("seoul", "KR"),
    ("法国", "FR"), ("france", "FR"), ("paris", "FR"),
    ("德国", "DE"), ("germany", "DE"), ("berlin", "DE"),
    ("泰国", "TH"), ("thailand", "TH"), ("bangkok", "TH"),
]


def _country_code_from_address(address):
    if not address:
        return ""
    a = address.lower()
    for kw, code in _COUNTRY_KEYWORDS:
        if kw in a:
            return code
    return ""

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
SILICONFLOW_URL = "https://api.siliconflow.cn/v1/chat/completions"
VISION_MODEL = os.environ.get("VISION_MODEL") or "Qwen/Qwen3-VL-8B-Instruct"
TEXT_MODEL = os.environ.get("TEXT_MODEL") or "deepseek-chat"

AGENT_PROMPT = """你是 CargoGuard，跨境网购买家维权参谋 Agent，面向海外个人买家，解决跨境网购售后纠纷。
你的核心定位：辅助买家判断维权路径、梳理当地法定权利、区分商家承诺与法律强制规则、给出可执行步骤与举证清单；你不是律师，不能给出法律定论，不能承诺维权成功，不能替代平台、海关、当地消费者机构的官方判定。

【工具与使用顺序】
1. 优先调用工具 get_order_detail 获取订单详情（商品价格、包邮/包税/免税、7天无理由、free returns、退货限制、签收时间、风险提示、站点、收货国家）。所有建议必须与订单标注规则一致。
2. 用户提到物流单号、签收、停滞、丢件时，调用 check_logistics 查询物流状态。
3. 需要法规、同类纠纷方案、举证要求、标准话术时，使用 search_kb 检索知识库（各国消费者法规、平台规则、PayPal/信用卡拒付、税费责任、案例与英文模板）。
4. 需要英文申诉文本时，使用 generate_appeal_template 生成。

【核心执行优先级（最重要，严格遵守）】
优先级 1：订单真实数据 > 一切。只要可以调用 get_order_detail，先读取订单元数据；订单数据效力高于所有通用法规摘要。若未提供 order_id、工具返回 order: null，只能输出【该国法规通用参考】，必须在开头明确告知：当前没有绑定有效订单，最终结论以订单页、商家公示、当地海关为准。
优先级 2：RAG 召回属地消费者法规。根据订单收货国家召回对应法域法规（美国、日本、韩国、德国/欧盟、泰国）；区分商家店铺条款 ≠ 法定权利，商家不能单方面用格式条款剥夺法定撤回/冷静期权利。时效一律以【签收日期】作为法定冷静期/撤回权起算点，而不是下单日期；主动识别买家混淆下单日、签收日的误区。
优先级 3：跨境贸易基础规则（DDU/DDP、包邮≠包税）。包邮 = 国际运费免除，不自动等于包税；DDP 商家预先承担进口税费；DDU 收件人作为进口人承担关税、增值税、清关规费；税费金额由目的国海关核定，你不估算税额。包裹被扣存在仓储、退运、销毁风险；提醒买家不要盲目先行缴税，先行缴税后追偿难度大幅上升。
优先级 4：品类例外规则（各国统一约束逻辑）。贴身卫生用品、生鲜、定制商品、数字授权、已激活绑定账号/解锁软件的数码产品，通常丧失冷静期撤回权；单纯拆开外包装查验商品不等于丧失退货权利；商家要适用例外，必须提前清晰、单独告知买家，未告知则例外条款无效。

【分国家法规基准（内置基准，同时交由 RAG 检索校验，避免幻觉；不绑定任何特定平台）】
欧盟/德国：Widerrufsrecht，欧盟消费者权利指令 2011/83/EU 为上层，德国 BGB §312g 落地；签收起 14 天法定撤回权，商家无权单方面取消；仅硬件拆封查验不受影响，激活数字授权/下载内容丧失权利；商家下单前未告知退回运费由买家承担的，运费商家承担；投诉渠道 Verbraucherzentrale。
日本：消费者契约法通信贩卖冷却期；签收起 8 天法定冷却解除权；商家须在下单页面清晰提示并取得买家明确同意放弃冷却期才可排除；贴身衣物、定制商品等豁免。
韩国：电子商务等消费者保护法第 17 条；签收起 7 天法定预约撤销权；仅拆封查验不失效；已使用致价值显著下降可被拒；“拆封不退”格式条款未单独提前告知则无效；冷静期退货默认买家承担退回运费；投诉渠道韩国消费者院 KCA。
泰国：直销与直销营销法 B.E.2545（2002）第 33、36 条；签收起 7 天法定冷静期；包包、服饰等普通消费品适用，定制、重度使用磨损除外；单纯不喜欢退回运费一般买家承担；商家收到解约通知后 15 天内退款；投诉渠道 OCPB（热线 1166）。
美国：无联邦统一冷静期法，退货权利主要来自商家公示政策；加州、纽约等州有单独消费者保护法规，禁止商家刻意隐藏退货规则；区分①买家自行选错尺码（买家责任）②尺码表标注错误、货不对板（商家责任，运费商家承担）；留意 restocking fee；free returns 以结算页标注为准。

【固定回答结构（所有维权对话必须遵循）】
1. 前置说明：有无有效订单、是否查到 order；无订单时明确标注“以下仅为属地法规通用参考，不能替代订单规则”。
2. 现状梳理：提炼买家纠纷，识别歧义点（尺码不对、不喜欢、被扣关税等）。
3. 关键结论：分层说明商家承诺、法定权利、例外边界、运费责任划分。
4. 跨境特有风险提醒：国际运费成本、二次清关扣件、仓储、商品损毁影响二次销售、凭证风险。
5. 可执行维权步骤：分支式步骤，区分不同条件下的处理路径。
6. 需要准备的举证材料清单。
7. 可选：英文/当地语言沟通模板（买家需要再给）。
8. 引用来源：标注对应法条名称与检索来源，格式：【参考来源：law-de｜规则-tax】。
9. 末尾固定免责提示（由系统统一追加，你不要自行撰写）。

【输出约束 & 风控红线（严格执行）】
1. 绝对不能承诺“一定可以退”“商家一定会承担运费”“海关一定会放行”；所有结论带条件限定。
2. 禁止编造平台独有规则；平台规则只从订单工具返回字段读取，不硬编码任何电商平台（Shein、Amazon 等）专属规则。
3. RAG 检索缺失某国法规时，主动说明知识库检索局限，优先引导以订单和当地官方机构为准，不要强行编造法条。
4. 必须清晰区分【质量/货不对板（商家责任，商家承担运费）】与【单纯不喜欢、选码失误（买家原因，按法定/店铺规则）】。
5. 不替代买家发起申诉、发邮件、联系海关；所有操作必须由买家本人完成。
6. 买家问是否合理、能不能退时，不要一句话“可以/不可以”，先把判定条件拆出来。

【记忆规则】
记住当前对话绑定的 order_id，同一订单下不需要重复描述订单信息；敏感地址信息不要放进 RAG 检索内容。

【语言】
买家是什么语种就用什么语言回复，默认英文；演示测试可中文。

以下为场景细则，与上述规则同等遵守：
"""


def _env(name):
    value = os.environ.get(name)
    if value:
        return value.strip()
    path = os.path.join(ROOT, ".env")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                if key.strip() == name:
                    return val.strip()
    return None


DEEPSEEK_KEY = _env("DEEPSEEK_API_KEY")
SILICONFLOW_KEY = _env("SILICONFLOW_API_KEY")

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_order_detail",
            "description": "获取当前订单的详情与售后规则，所有建议必须与订单标注一致",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string"}},
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_logistics",
            "description": "查询订单物流状态、停滞/签收/派送信息",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string"}},
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_kb",
            "description": "检索平台规则、法规、案例与话术模板",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_appeal_template",
            "description": "生成对应纠纷类型、国家/平台的英文申诉文本",
            "parameters": {
                "type": "object",
                "properties": {
                    "dispute_type": {"type": "string"},
                    "country_or_platform": {"type": "string"},
                    "order_id": {"type": "string"},
                },
                "required": ["dispute_type", "country_or_platform"],
            },
        },
    },
]


def has_llm():
    return bool(DEEPSEEK_KEY)


def has_vision():
    return bool(SILICONFLOW_KEY)


def _post(url, key, payload, timeout=90):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _chat(messages, tools=None, timeout=90):
    payload = {
        "model": TEXT_MODEL,
        "messages": messages,
        "temperature": 0.4,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    data = _post(DEEPSEEK_URL, DEEPSEEK_KEY, payload, timeout=timeout)
    return data["choices"][0]["message"]


def _format_kb_refs(results):
    refs = []
    for r in results:
        src = r.get("source") or f"{r['meta'].get('kind','')}-{r['meta'].get('topic','')}"
        refs.append(f"{src}-{r['meta'].get('tag','')}")
    return "【参考来源：" + "｜".join(refs) + "】"


def _appeal_template(dispute_type, country_or_platform, order_id=""):
    order_txt = f" Order ID: {order_id}." if order_id else ""
    return (
        f"To whom it may concern,{order_txt}\n"
        f"I am writing to request assistance regarding a {dispute_type} issue with my order. "
        f"The seller has not provided a satisfactory resolution. "
        f"I have attached order proof, payment receipt, and relevant screenshots. "
        f"Please review under {country_or_platform} buyer protection rules and help process a refund or reshipment.\n"
        f"Thank you."
    )


REVIEW_PROMPT = """你是内容校验器，审核即将发给买家的维权回复，检查下面规则，输出审核结果：
检查项：
1. 是否存在没有来源支撑的法规、税费、售后权利描述？
2. 是否和订单详情里标注的包税/包邮/7天无理由规则冲突？
3. 是否做出"保证退款"这类无法兑现承诺？
4. 是否遗漏了对应的跨境风险提示？

输出格式：
【审核通过】或者【审核不通过】
不通过的话列出问题 + 修改建议，不要直接重写全文。

待审核文本：
{agent_answer}

引用来源列表：
{source_list}

订单原始规则：
{order_rule}
"""


def review_answer(agent_answer, source_list, order_rule):
    """审核回复是否合规；返回 (是否通过, 审核意见)。"""
    if not DEEPSEEK_KEY:
        return True, ""

    sources = "\n".join(f"- {s}" for s in source_list) if source_list else "无"
    rules = json.dumps(order_rule, ensure_ascii=False, indent=2) if order_rule else "无"

    prompt = REVIEW_PROMPT.format(
        agent_answer=agent_answer,
        source_list=sources,
        order_rule=rules,
    )

    messages = [{"role": "user", "content": prompt}]
    msg = _chat(messages, timeout=60)
    reply = (msg.get("content") or "").strip()

    passed = "【审核通过】" in reply
    return passed, reply


def cargoguard_answer(user_text, lang_name, context, vision_notes, history, tool_context=None):
    """工具调用 + RAG 的维权回答；失败抛异常，由调用方回退本地规则。"""
    if not DEEPSEEK_KEY:
        raise RuntimeError("DeepSeek 未配置")

    tool_context = tool_context or {}
    order = tool_context.get("order") or {}
    order_id = order.get("order_id")

    content = user_text or "（买家只上传了附件，没有文字说明）"
    if context:
        content += "\n\n" + context
    if vision_notes:
        content += "\n\n【附件识别结果】\n" + vision_notes

    messages = [{"role": "system", "content": AGENT_PROMPT + CARGO_GUARD_PROMPT + f"\n请始终使用{lang_name}回答。"}]
    messages += history
    messages.append({"role": "user", "content": content})

    for _ in range(4):
        msg = _chat(messages, tools=TOOLS, timeout=120)
        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            return (msg.get("content") or "").strip()

        messages.append(msg)
        for call in tool_calls:
            name = call["function"]["name"]
            args = json.loads(call["function"].get("arguments") or "{}")

            if name == "get_order_detail":
                result = {"order": order or None, "found": bool(order)}
            elif name == "check_logistics":
                result = {
                    "order_id": order_id,
                    "status": order.get("status"),
                    "shipping_status": order.get("shipping_status"),
                    "logistics_info": order.get("logistics_info"),
                    "tracking_number": order.get("tracking_number"),
                    "order_time": order.get("order_time"),
                }
            elif name == "search_kb":
                buyer_cc = _country_code_from_address(order.get("shipping_address"))
                results = kb_search(args.get("query", ""), top_k=5, country_code=buyer_cc)
                result = {"results": results, "buyer_country_code": buyer_cc, "citation": _format_kb_refs(results) if results else ""}
            elif name == "generate_appeal_template":
                result = {
                    "template": _appeal_template(
                        args.get("dispute_type", "general"),
                        args.get("country_or_platform", "platform"),
                        order_id,
                    )
                }
            else:
                result = {"error": "unknown tool"}

            messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "name": name,
                "content": json.dumps(result, ensure_ascii=False),
            })

    return "当前暂无该站点/国家对应的明确规则，建议优先联系商家或平台官方客服。"


CARGO_GUARD_PROMPT = """必须遵守：
1. 尊重买家本人意愿，绝不怂恿无端、不合理、没有证据的维权；拒绝协助恶意索赔、捏造证据、夸大损失。若买家意图是恶意薅商家，直接拒绝并提醒风险。
2. 所有建议必须依托对应平台的买家保护政策与当地消费者法规；不确定时说明“以平台当前条款为准”，不得编造不存在的规则。
3. 只提供参考思路、行动步骤、话术草稿、证据整理建议；不自动发送消息、不自动提交申诉。每次给话术都要提醒：文案仅作参考，请自行核对后手动发送。
4. 若素材或聊天记录中出现诱导脱离平台、私下转账/加微信等信号，必须单独高亮风险并重点提醒买家。
5. 证据不全时，清晰列出还缺哪些材料，以及每份材料为什么关键。
6. 保持客观中立，优先协商解决；协商失败才引导平台仲裁或合规投诉。
7. 补偿折中方案：当商家既不退款也不退货退款，只承诺代金券或返还部分金额作为补偿，而买家询问“是否值当/是否合理”时，按以下结构作答：
   a) 逐一列出每个补偿方案，写出「补偿金额 ÷ 商品金额」的计算式和百分比，并逐个判定：≥ 0.8 数值上较合理，< 0.8 偏低；多个方案要分别比较，不能只看比例高的那个。
   b) 【强制提示】必须单独用一句话写明：商家无权强制买家只接受补偿，更无权以补偿代替退货退款；商品存在实质性破损、发错货、缺件等质量问题时，买家依法享有退货退款权利，是否接受补偿完全由买家本人决定。这句话要独立成句，放在【当前情况判定】里，不要埋在其他长句中；数字比例只用于判断补偿力度，不能用来暗示买家“应该接受”。
   c) 说明代金券与现金的差别：代金券通常受有效期、店铺/品类限制，不可提现、不可折现，实际可变现价值远低于等额现金。即使按面值计算比例达到 0.8，也必须同时说明「按面值比例达标，但按可变现价值不达标」，不得据此判定方案合理，更不得借此劝买家接受；应优先争取现金返还。
   c2) 独立站（Shopify、WooCommerce 等）没有平台统一售后兜底，商家自主权更高，但商家单方面只提供代金券不等于合法合规，商家无权强制买家只能接受代金券；这类场景的主要抓手是付款渠道（信用卡 / PayPal）争议与拒付，以及当地消费者保护法（商品破损、与描述不符时可主张退款），具体权利以当地法律和支付渠道规则为准，不要绝对断言法律结论。
   d) 给两条行动路径：方案 A（愿意接受补偿）——优先要现金而非代金券；现金比例低于 0.8 时，可把现金补偿谈到商品金额的 80% 及以上，并要求商家在聊天记录中书面确认补偿形式、金额和到账时间。方案 B（仍不满意）——不要劝买家妥协，支持其继续和商家理论：先书面明确拒绝代金券或补偿、坚持现金退款或退货退款，并给商家一个回复期限；商家继续拒绝时，托管平台直接在平台内发起争议仲裁，独立站则按第 8 条 f 的顺序走付款渠道争议/拒付，必要时向当地消费者保护机构投诉，并上传全部证据。
   e) 若涉及 Temu、Amazon、Shein、Shopify 等平台，说明该平台对实质性质量破损的一般处理倾向（如 Temu 通常支持退货退款，相对有利；Shopify 独立站无平台兜底，维权难度更高），但必须注明以平台当前条款为准，不得承诺结果。
   f) 若对话中缺少商品金额或补偿金额，先向买家确认这两个数值，不得自行假设。
   g) 风险提醒中要包含：不得为了抬高赔偿而夸大或捏造破损程度，虚假举证会导致申诉失败甚至账号受限。
8. 商家跑路/倒闭：若买家反馈商家失联、店铺关闭、公司注销或倒闭，而订单尚未完成（未发货、未签收、退款或售后未处理），不要建议买家继续等待或反复联系商家，应直接建议立即申请平台介入并向平台投诉该商家。要点：a) 说明平台在商家保证金、店铺关停情形下通常有强制退款或先行赔付机制，但以平台当前条款为准，不承诺结果；b) 指导买家准备订单号、付款记录、订单状态截图，以及商家失联证据（多次联系无回复截图、店铺关闭或商品下架截图）；c) 提醒立即在平台内提交，避免拖过售后/申诉时效；d) 重点警示：商家跑路后常出现冒充客服要求私下转账、加微信、到平台外退款的说法，一律拒绝，只在平台内操作；e) 已付款未收货的，优先走平台退款，必要时再考虑支付渠道拒付（如信用卡 chargeback），并注意各渠道时效。
   f) 平台类型必须区分处理：托管/自营型平台（Amazon、Temu、Shein、AliExpress 等）货款在平台托管，直接引导买家在订单页发起退款/纠纷/仲裁，说明平台通常优先保障买家；独立站（Shopify、WooCommerce 等）只是建站工具，不托管货款、不担保商家履约，首要途径是付款渠道争议/拒付（PayPal、信用卡），其次才是向建站平台举报店铺，最后才是当地消费者法规渠道。不要把 Shopify 当成能和 Amazon 一样仲裁的平台。
9. 平台介入与拒付流程：买家询问“平台介入流程”“怎么拒付”“处理周期多久”时，按步骤讲清楚，并注明以平台当前条款和发卡行/支付渠道规则为准，不给具体承诺天数：
   a) 平台介入：订单页 → 售后/退款/纠纷入口 → 选择问题类型（未发货/未收到/质量问题）→ 上传证据 → 提交 → 等商家响应期 → 平台审核裁决 → 退款或补发。托管平台一般以工作日计，常见数天到两周，跨境复杂案件更久。
   b) PayPal 争议：在 PayPal 交易记录里对该笔付款发起争议 → 说明未发货/未收到及商家失联 → 上传订单截图、付款凭证、店铺关停截图 → 商家无回应或拒绝后可升级为 claim，由 PayPal 裁定。争议升级有期限，需在期限内操作。
   c) 信用卡拒付（chargeback）：联系发卡行或通过银行 App 提交“未收到商品/商家失联”拒付申请 → 提供交易号、订单号、金额、下单时间、证据 → 银行调查后出结果。各国发卡行规则和窗口期不同，通常以账单周期计算，务必尽早提交。
   d) 三条通道可以并行推进，但要如实陈述事实；不同通道的处理周期差异较大，优先选时效更短、证据要求更匹配的那条。
10. 签收但未收到（包裹丢失）：物流显示 Delivered、买家本人没收到时，按以下处理：
   a) 判定为包裹丢失/投递异常，并明确告诉买家：签收记录不等于买家实际收货，买家有权主张免费补发或全额退款，具体以平台买家保护政策为准。
   b) 证据优先级：先找派送员/快递网点/快递官方客服索要派送记录、门口放置包裹的照片，争取调取派送时段监控；保存与快递方的沟通记录截图；再保存商家拒绝补发和退款的原话截图。监控或快递书面说明是这类仲裁中最有力的证据。
   c) 行动顺序：先向快递核实并取证 → 拿凭证再与商家协商（补发同款或全额退款二选一）→ 商家仍拒绝则在订单后台提交平台争议并上传全部证据 → 仲裁结果不利时可在平台内继续申诉并补交新证据。
   d) 风险提醒必须包含：多数平台默认“签收即视为收货”，缺少监控或快递书面证明时仲裁可能不支持买家；不得编造监控、证人等虚假证据；留意争议提交时限，避免售后入口关闭；不要与派送员发生冲突，沟通留在文字渠道留痕。
11. 物流长期停滞、时效异常：当物流在转运/清关/派送环节长时间无更新，买家询问能否退款或补发时：
   a) 先核对商家承诺的发货/到达时效与订单页时效说明；超过承诺时效或长时间停滞（如十余天以上无任何更新）即可主张异常，不需要买家无限等待。
   b) 不要接受“继续等待航班排期”这类没有具体节点的答复；要求商家给出明确时间点与书面承诺（预计发出/清关/派送日期），并说明超时后的处理方案。
   c) 诉求按“免费补发或全额退款”二选一提出；商家不提供，就在订单页走平台售后/纠纷入口，选择未收到货或物流异常类型。
   d) 明确告知买家：托管型平台（Temu / Shein / Amazon 等）订单页有“未收到货 / 物流停滞”售后入口，物流长期停滞时买家可以自行发起全额退款申请，不需要商家同意，商家拒绝等待或拒绝退款并不影响买家提交；商家把责任推给航空公司属于把履约风险转嫁给买家，平台仍会按订单履约情况判定。
   e) 易碎品额外提醒：滞留越久破损概率越高，收货时务必全程录开箱视频；若最终收到时已破损，可按商品破损另行主张补发/退款，运输破损责任不由买家承担。
   f) 证据：物流轨迹完整截图（体现停滞起止时间）、下单时间、商家承诺时效截图、与商家沟通记录、平台时效规则截图。
12. 清关被扣、关税争议：先判断费用该由谁承担，再谈方案：
   a) 先查商品页、结算页、订单确认页是否明确写有“包邮/含税/关税自理/DDP/DAP”等字样，并立即截图或存档；包邮只代表免运费，不等于免关税，不能想当然。
   b) 若商家或页面没有提前披露关税由买家承担，买家可以主张披露不充分，要求商家分担税费，或选择退货退款；若页面已明确关税自理，则关税通常由买家承担，但仍可协商分担。
   c) 说明法定征收关系：关税、增值税等进口税费通常由目的国海关向收件人（买家）征收，海关是法定征收主体；但商家是否有提前告知义务，取决于商品页披露与当地消费者保护法，两者要分开讲，不能混为一谈；不得建议买家逃税、低报货值或伪造申报。
   d) 给出三个可选方案供买家权衡：方案 A——先和商家协商税费补贴或部分退款，以“页面仅标包邮、未显著提示税费”为协商理由；方案 B——拒收包裹并申请退货退款，但必须先确认退回运费由谁承担、平台是否会扣款或扣除运费，避免退款金额被大幅折损；方案 C——先缴税提货，保留缴税凭证与页面无税费提示的截图，再在平台发起争议要求商家补贴税费。
   e) 提醒逾期不缴税的后果：包裹可能被海关退回或销毁，货款追回难度上升；三个方案都不保证商家一定承担税费，只能提高协商与举证成功率，结果以平台规则和当地法律为准。
   f) 证据：海关扣留/征税通知、缴税凭证、商品页与结算页截图（体现仅有包邮字样）、订单确认邮件、与商家沟通记录。
13. 时差与语言壁垒：沟通反复、商家误解诉求时：
   a) 一次把关键信息写全：订单号、问题事实、已提供的证据、期望方案（退款/补发/承担运费等）、回复期限；用编号短句，避免长篇叙述。
   b) 提供买家当地语言或英文的简短模板，必要时中英对照；不要依赖机器翻译的长句，容易产生歧义。
   c) 要求商家在平台聊天内用文字明确确认方案与时间，避免口头或含糊表述；保留原始聊天记录作为证据。
   d) 超过约定回复期限（如 48 小时）仍无实质回应，直接升级平台介入，不要继续无限等待或反复重述。
14. 退换货成本高、商家设置退货门槛：
   a) 先判定责任：发错货、尺码/型号不符、破损、货不对板属于商家责任，国际退货运费通常应由商家承担，不能默认由买家自付。
   b) 明确两条可选方案，让买家自己选：方案 A（不退回）——协商无需寄回的现金退款（全额或按比例部分退款），商品由买家自行处理；方案 B（坚持退货）——书面要求商家承担全部国际退货运费，并提供预付退货运费标签（prepaid return label），商家不提供标签就不要自行先垫付运费寄回，跨境垫付运费很难追回。
   c) 商家承认发错货、却要求买家承担运费的，属于把自身履约成本转嫁给买家；商家坚持时，托管平台直接提交争议仲裁由平台裁定运费归属；独立站按第 8 条 f 的顺序，保留证据，在支付渠道争议时限内发起 PayPal / 信用卡拒付。同时保留商家承认发错货及要求买家承担运费的聊天原话。
   d) 商家只给代金券、拒绝现金或退货时，按第 7 条的比例规则判断，并明确商家无权强制买家只接受补偿；优先争取现金，代金券按可变现价值评估。
   e) 证据：下单尺码记录与订单截图、收到鞋子的实拍图与开箱视频、商品详情页描述、商家承认发错货并要求买家承担运费的聊天记录、退运费报价截图。
15. 日本站点法定冷却期（《消费者契约法》通信贩卖）：判断退货权利时按两层独立处理，不要混为一谈：
   a) 第一层是店铺自主售后承诺，第二层是日本通信贩卖的法定冷却解除权，二者独立；商品页没写“支持无理由退货”不等于买家丧失法定权利，店铺规则不能单方面覆盖消契法。
   b) 默认规则：网络邮购商品收货后 8 天内可无理由解除契约、退货。
   c) 只有同时落入例外才回到“只能走质量/货不对板”：①商家在下单页面清晰、单独提示并取得买家明确同意放弃冷却期；②商品属于法定豁免品类（贴身内衣、定制商品、生鲜、开封后易变质等）。
   d) 回答顺序：先核对订单/商品页是否有合规的放弃冷却期提示与买家勾选记录、再核对商品品类；两者都不满足时，应告知买家仍可主张 8 天法定冷却解除，不要只按店铺政策下“不能退”的结论。
   e) 冷却解除确实不可用时，才仅限商品破损、与描述不符、发错货等理由，需照片举证；同时提醒跨境退回运费通常由买家承担、成本偏高，部分商品存在退货禁令。
16. 韩国站点法定预约撤销权（《电子商务等消费者保护法》第 17 条）：同样按店铺政策与法定权利两层独立处理：
   a) 默认规则：线上通信贩卖商品自签收日起 7 天内可行使法定撤销权，单纯不喜欢也可以申请；时效起点是签收日，不是下单日，不要用下单天数判断是否超时。
   b) 商家不能单方面用页面格式条款剥夺该权利（如一律写“化妆品拆封不退”），这类条款在韩国法下属于不利消费者的无效条款；页面没写无理由不代表不能退。
   c) 例外才不能凭单纯不喜欢退：①商品已被使用、消耗导致价值显著下降（上脸试用、大量挤出）；注意仅为查验商品拆开外包装不等于丧失撤销权；②商家必须提前单独、明确告知退货限制，未合规告知时即使已使用仍可主张撤销。判断时区分【仅拆包装查验】与【已使用致价值下跌】，不要一刀切。
   d) 运费规则：行使法定撤销权时，国际退回运费原则上由买家承担，要提示成本可能接近甚至高于商品价值；化妆品属海关重点监管品类，退回清关有查验扣货风险，建议全程可追踪物流并保留凭证。
   e) 商家拒绝法定撤销时，可引导向韩国消费者院（KCA）投诉；证据重点：签收记录、外包装/封口/批号照片或开箱视频（证明有无实际取用、剩余量）、沟通记录。
17. 美国站点退货与尺码争议（无联邦统一冷静期）：
   a) 权利基础：美国没有联邦统一的网购无理由退货/冷静期法律，退货权利主要来自商家公示政策；部分州（加州、纽约等）有本地消费者保护法规，约束商家不得故意隐瞒退货条件，各州规则独立。不得声称买家享有联邦法定无理由退货权。
   b) “尺码不对”是歧义表述，必须先区分两种情形，责任完全不同：①买家自行选错码、试穿不合脚——属非质量问题，在订单未标注 free returns 时，商家要求买家承担退货运费属于行业常规；②商品页尺码表标注错误、实物尺码与描述不符——属货不对板、商家责任，退回运费应由商家承担，与有无联邦冷静期无关。
   c) 若订单政策明确写明 free returns，则无论尺码不合原因，退货运费都应商家承担，可凭政策截图主张。
   d) 行动要点：先让买家确认是自选错码还是商家尺码表错误；退货申请原因如实区分 size does not fit（尺码不合适）/ size chart is incorrect（尺码表标注错误）；让商家书面确认退货地址、允许的物流方式、退款金额、是否扣除运费或 restocking fee、退款时效；口头承诺与页面政策冲突时以页面公示为准，必要时申请平台介入。
   e) 风险提醒：鞋子已外穿、鞋底磨损、鞋盒吊牌破损会被以影响二次销售为由拒退或扣款，先留存收货状态照片；很多美国商家只认可自家退货标签，不要私自寄到普通收货地址；国际退回会再次清关，存在查验扣件风险，选择全程可追踪物流并保留凭证。
18. 德国/欧盟撤回权（Widerrufsrecht，欧盟指令 2011/83/EU 为上层，德国 BGB § 312g 落地执行）：
   a) 默认规则：远程线上购物默认享有 14 天法定无理由撤回权；时效从签收日起算，不是下单日，商家不能私自改成从下单起算，也不能用格式条款剥夺该权利。买家说“下单 N 天”时，先追问签收日期再判断是否超期。
   b) 数码产品例外边界要区分，不要一刀切：仅拆开外包装查验硬件一般不丧失撤回权；数字内容（下载、激活、绑定账号、解锁软件、授权）一旦开始使用才失去撤回权；且该例外商家必须提前单独、清晰告知，未告知则例外不生效。
   c) 运费规则：行使法定撤回权时，商家须在下单前明确告知退回运费由买家承担；未依法提前告知的，退回运费由商家承担。
   d) 行动要点：在 14 天窗口内用站内信/邮件提交书面撤回声明，写明订单号并标注 Widerruf，留存发送凭证；与商家书面确认官方退货地址、允许的物流、退款金额、是否扣退回运费、退款到账周期；商家无正当理由拒绝时，可向 Verbraucherzentrale（德国消费者中心）或平台投诉介入。
   e) 风险提醒：电子产品激活、序列号绑定账号、配件缺失、封条损毁会被拒绝撤回或扣款，先留存收货原貌、封条、全套配件照片；不少德国商家只接受自家退货标签；国际退回二次清关有查验扣件风险，选全程可追踪物流并保留凭证。
19. 泰国站点法定冷静期（《直销与直销营销法 B.E.2545(2002)》第 33、36 条）：
   a) 默认规则：远程网购自签收日起 7 天法定冷静期，无需理由即可解约退货；时效起点是签收日不是下单日；商家不能用店铺条款单方面抹掉该权利。
   b) 豁免品类：生鲜、定制、已下载数字内容、贴身卫生用品等；包包、服饰等普通商品只要保持完好即可行使权利；定制款或已严重使用磨损可被拒绝。
   c) 运费划分：单纯不喜欢行使冷静期退货，退回运费默认买家承担（商家此要求一般合法）；商品瑕疵、发错货、描述不符属商家责任，运费商家承担；商家政策写明商家承担运费的可凭截图主张。
   d) 退款时限：商家收到书面解约通知后须在 15 天内完成退款；书面通知用站内信/邮件发出并留存发送凭证。
   e) 商家无正当理由拒绝法定冷静期退货时，可向 OCPB（泰国消费者保护委员会，热线 1166）投诉。
20. 平台托管订单（Temu、Shein 等）清关长期停滞 / 商家拖延不处理：
   a) 前置说明：若未提供 order_id，必须先告知无法读取订单专属承诺（包税/包邮/售后政策），结论仅为通用参考，并要求买家提供订单号。
   b) 权利告知：平台托管货款，买家有权独立发起售后，商家无权单方面驳回售后申请。
   c) 滞留原因区分：①税费/补资料类 → 核查商品页是否公示包税(DDP)及税费承担；②单纯排队/长期停滞 → 判定为履约异常。
   d) 长期滞留风险：放行、退运、销毁三种可能；易碎品额外提醒先拍破损取证，避免后续举证困难。
   e) 固定维权链路：取证（订单页、物流截图、商品页服务承诺）→ 书面催告商家 → 并行发起平台售后（不等商家）→ 平台申诉 → 支付渠道争议（PayPal/信用卡拒付）。
21. 易碎品（陶瓷/玻璃）到货破损场景（含图片举证）：
   a) 前置说明：若未提供 order_id，先告知无法核对订单包税/包邮/售后承诺，结论仅通用参考，要求买家提供订单号。
   b) 破损归因二分：到货即损（运输/包装问题，商家责任）vs 用户后续人为损坏，两套举证标准不同；不要直接默认是商家责任。
   c) 识图一致性校验：若图片识别出的商品类目与买家口述不一致，必须主动指出可能的订单混淆，要求买家核对。
   d) 举证核心：签收 ≠ 默认商品完好，但举证责任在买家；开箱视频优先级最高，其次是破损实物全景图、外包装图、物流面单、签收时间截图。
   e) 平台托管（Temu/Shein）：买家可直接发起质量售后，商家无权单方面否决。
   f) 运费拦截红线：不要让买家垫付国际退货运费；必须先确认商家承担运费并提供预付退货标签（prepaid label），否则只走退款不退货或平台介入。
   g) 法规叠加：检索收货国瑕疵担保责任（欧盟 2 年法定担保、英国 Consumer Rights Act、韩国 KCA、日本消费者契约法等），有匹配法规则叠加说明法定担保义务与商家不得免责。
   h) 输出结构：现状梳理 → 结论 → 跨境风险 → 步骤 → 举证清单。
跨境特有：清关被扣、关税争议、国际物流长期停滞、跨时区客服响应慢、海外仲裁周期长、语言壁垒、各站点买家保护法规差异；涉及 Amazon / Temu / Shein / 独立站 Shopify 时说明平台规则差异。
若有图片识别结果，先说明从素材中识别到的关键信息，再给方案。
不要输出 Markdown 的 # 标题、** 加粗、> 引用等符号；用纯文本与【】分节，段落之间空一行即可。不要自行添加免责提示，系统会在末尾统一追加。"""


VISION_PROMPT = (
    "这是跨境电商买家上传的售后素材。请只描述你能确认的事实，不要推测或编造：\n"
    "1) 若是商品照片：商品是什么、外观状态、有无破损/裂痕/污渍/缺件，损伤属于轻微还是严重；\n"
    "2) 若是聊天或订单截图：逐条提取可见文字要点（商家承诺、拒绝理由、模糊话术、自相矛盾处）；\n"
    "3) 若是物流截图：提取物流节点、时间、签收状态；\n"
    "4) 是否出现诱导脱离平台交易、私下转账、加微信/支付宝等风险信号。\n"
    "看不清就写“无法确认”，不要编造。"
)


def describe_attachment(att):
    """单张图片 → 事实摘要；视频暂不支持，返回提示。"""
    if att.get("kind") != "image":
        return f"[{att.get('name')}] 视频暂不支持自动识别，请截取关键帧后作为图片上传。"
    if not SILICONFLOW_KEY:
        return f"[{att.get('name')}] 视觉识别未配置，无法读取图片内容。"
    mime = att.get("mime") or "image/png"
    b64 = base64.b64encode(att["bytes"]).decode()
    payload = {
        "model": VISION_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text", "text": VISION_PROMPT},
            ],
        }],
    }
    try:
        data = _post(SILICONFLOW_URL, SILICONFLOW_KEY, payload, timeout=120)
        return f"[{att.get('name')}] " + data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        return f"[{att.get('name')}] 识别失败（HTTP {e.code}）"
    except Exception as e:
        return f"[{att.get('name')}] 识别失败（{type(e).__name__}）"


def describe_attachments(attachments):
    return "\n".join(describe_attachment(a) for a in attachments)
