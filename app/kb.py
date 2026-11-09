"""RAG 知识库：加载 kb/facts.csv，切块、embedding、检索并返回引用来源。

- embedding 使用硅基流动 BAAI/bge-m3（若可用），失败时回退关键词检索。
- 本地 numpy 向量检索 + 关键词混合；低分结果直接判空，避免幻觉。
"""
import csv
import json
import math
import os
import re
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KB_DIR = os.path.join(ROOT, "kb")
FACTS_CSV = os.path.join(KB_DIR, "facts.csv")
CACHE_EMB = os.path.join(KB_DIR, "chunks_emb.json")

EMBED_URL = "https://api.siliconflow.cn/v1/embeddings"
EMBED_MODEL = "BAAI/bge-m3"

# 与 llm.py 一致的 env 读取
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


SILICONFLOW_KEY = _env("SILICONFLOW_API_KEY")


def _post_json(url, key, payload, timeout=90):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _embed(texts):
    """返回向量列表；失败返回 None。"""
    if not SILICONFLOW_KEY:
        return None
    payload = {"model": EMBED_MODEL, "input": texts}
    try:
        data = _post_json(EMBED_URL, SILICONFLOW_KEY, payload, timeout=120)
        return [d["embedding"] for d in data.get("data", [])]
    except Exception:
        return None


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-8
    nb = math.sqrt(sum(y * y for y in b)) or 1e-8
    return dot / (na * nb)


def _load_law_yamls():
    """读取 kb/laws/*.yaml：每个文件一个国家法规，作为一条 chunk 入库。"""
    docs = []
    laws_dir = os.path.join(KB_DIR, "laws")
    if not os.path.isdir(laws_dir):
        return docs
    for name in sorted(os.listdir(laws_dir)):
        if not name.endswith((".yaml", ".yml")):
            continue
        path = os.path.join(laws_dir, name)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read().strip()
        except Exception:
            continue
        if not text:
            continue
        law_id = re.search(r"^law_id:\s*(.+)$", text, flags=re.M)
        country_code = re.search(r"^country_code:\s*(.+)$", text, flags=re.M)
        law_name = re.search(r"^law_name:\s*(.+)$", text, flags=re.M)
        law_id = law_id.group(1).strip() if law_id else name.rsplit(".", 1)[0]
        cc = country_code.group(1).strip().lower() if country_code else ""
        topic = law_name.group(1).strip() if law_name else law_id
        meta = {"kind": "law", "tag": cc.replace("/", "_"), "topic": topic}
        docs.append({"id": law_id, "title": f"{topic}-{cc}", "text": text, "meta": meta})
    return docs


def load_documents():
    """读取 facts.csv + kb/laws/*.yaml → chunk 列表 [{id,text,meta}]。"""
    docs = []
    if os.path.exists(FACTS_CSV):
        with open(FACTS_CSV, encoding="utf-8") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if not row or len(row) < 3:
                    continue
                kind, tag, topic, *rest = row
                meta = {"kind": kind, "tag": tag, "topic": topic}
                text = "，".join([x for x in row[3:] if x])
                title = f"{topic}-{tag}"
                docs.append({"id": f"{i:04d}", "title": title, "text": text, "meta": meta})
    docs.extend(_load_law_yamls())
    return docs


def _load_cache():
    if not os.path.exists(CACHE_EMB):
        return {}
    try:
        with open(CACHE_EMB, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache):
    with open(CACHE_EMB, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)


def build_index():
    docs = load_documents()
    cache = _load_cache()
    texts = [d["title"] + "。" + d["text"] for d in docs]
    embs = cache.get("emb")
    if embs is None or len(embs) != len(texts):
        embs = _embed(texts)
        if embs:
            cache["emb"] = embs
            _save_cache(cache)
    return docs, embs


DOCS, EMBS = build_index()


def search(query, top_k=4, min_score=0.30, country_code=None):
    """混合检索：向量余弦 + 关键词命中；country_code 给定则优先召回该国法规（meta.tag）。"""
    if not query:
        return []
    docs = load_documents()
    if not docs:
        return []

    q = query.strip().lower()
    raw_terms = re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]+", q)
    terms = set()
    for t in raw_terms:
        if re.match(r"[\u4e00-\u9fff]+", t):
            # 中文拆成单字 + 相邻双字，提升关键词召回
            for i in range(len(t)):
                terms.add(t[i])
                if i + 1 < len(t):
                    terms.add(t[i:i+2])
        else:
            terms.add(t)

    kw_scores = []
    for d in docs:
        text = (d["title"] + " " + d["text"]).lower()
        hits = sum(1 for t in terms if t in text)
        kw_scores.append(hits)

    vec_scores = [0.0] * len(docs)
    if EMBS:
        qemb = _embed([query])
        if qemb:
            qv = qemb[0]
            for i, ev in enumerate(EMBS):
                vec_scores[i] = _cosine(qv, ev)

    # 欧盟国家统一映射到 eu 法规
    eu_countries = {"de", "fr", "es", "it", "nl", "be", "at", "pt", "ie", "fi", "se", "dk", "pl"}
    cc = (country_code or "").lower()
    target_tags = set()
    if cc:
        target_tags.add(cc)
        if cc in eu_countries:
            target_tags.add("eu")

    results = []
    for i, d in enumerate(docs):
        tag = (d["meta"].get("tag") or "").lower()
        kind = d["meta"].get("kind", "")
        # 国家隔离：给定收货国时，法规类(law)只保留匹配该国的；平台规则/案例等非法规不限制
        if cc and kind == "law" and tag not in target_tags:
            continue
        score = 0.55 * vec_scores[i] + 0.45 * (kw_scores[i] / max(1, max(kw_scores)))
        # 命中目标国法规额外加权，确保属地法优先
        if cc and kind == "law" and tag in target_tags:
            score += 0.12
        results.append((score, d))

    results.sort(key=lambda x: x[0], reverse=True)
    out = []
    for score, d in results[:top_k]:
        if score < min_score:
            continue
        out.append({
            "title": d["title"],
            "text": d["text"],
            "meta": d["meta"],
            "score": round(score, 3),
            "source": f"{d['meta'].get('kind','')}-{d['meta'].get('topic','')}",
        })
    return out
