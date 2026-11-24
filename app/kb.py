"""RAG 知识库：加载 kb/facts.csv，切块、embedding、检索并返回引用来源。

- embedding 使用硅基流动 BAAI/bge-m3（若可用），失败时回退关键词检索。
- 本地 numpy 向量检索 + 关键词混合；低分结果直接判空，避免幻觉。
"""
import csv
import hashlib
import json
import math
import os
import re
import urllib.error
import urllib.request
from functools import lru_cache

try:
    import numpy as np
except ImportError:  # pragma: no cover - 未安装 numpy 时退回纯 Python 计算
    np = None

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


def _build_emb_matrix(embs):
    """把向量列表预归一化成矩阵，后续用一次矩阵乘法算全部余弦相似度。"""
    if np is None or not embs:
        return None
    try:
        mat = np.asarray(embs, dtype=np.float32)
    except (TypeError, ValueError):
        return None
    if mat.ndim != 2 or mat.shape[0] == 0:
        return None
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


@lru_cache(maxsize=256)
def _query_embedding(query: str):
    """查询向量缓存：相同问题不重复调用远程 embedding 接口。"""
    embs = _embed([query])
    return tuple(embs[0]) if embs else None


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
        review_status = re.search(r"^review_status:\s*(.+)$", text, flags=re.M)
        review_status = review_status.group(1).strip().lower() if review_status else ""
        # 双人审核门槛：仅 review_status=passed 的法规可入库检索，未标注/未过审一律跳过
        if review_status != "passed":
            continue
        law_id = law_id.group(1).strip() if law_id else name.rsplit(".", 1)[0]
        cc = country_code.group(1).strip().lower() if country_code else ""
        topic = law_name.group(1).strip() if law_name else law_id
        tags = [t.strip().lower() for t in cc.split("/") if t.strip()]
        meta = {"kind": "law", "tag": tags[0] if tags else cc, "tags": tags, "topic": topic}
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
                kind, tag, topic = row[:3]
                tags = [t.strip().lower() for t in tag.split("/") if t.strip()]
                meta = {"kind": kind, "tag": tags[0] if tags else tag, "tags": tags, "topic": topic}
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
    # 用内容指纹判断缓存是否有效：只比对条数会在“文本改了但条数不变”时复用旧向量，
    # 造成静默错召回。这里把全部文本拼起来取 sha256 作为缓存版本。
    digest = hashlib.sha256("\n".join(texts).encode("utf-8")).hexdigest()
    embs = cache.get("emb")
    if embs is None or cache.get("hash") != digest or len(embs) != len(texts):
        embs = _embed(texts)
        if embs:
            cache["emb"] = embs
            cache["hash"] = digest
            _save_cache(cache)
    return docs, embs


DOCS, EMBS = build_index()
EMB_MATRIX = _build_emb_matrix(EMBS)


def search(query, top_k=4, min_score=0.30, country_code=None, state_code=None):
    """混合检索：向量余弦 + 关键词命中；country_code 给定则优先召回该国法规；美国可传 state_code 按州优先。"""
    if not query:
        return []
    # 直接使用启动时构建的文档快照，既避免每次查询重读文件，也保证与 EMBS 下标对齐
    docs = DOCS
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
    if EMBS and len(EMBS) == len(docs):
        qv = _query_embedding(query)
        if qv is None:
            # 失败结果不缓存，避免密钥或网络恢复后仍命中空值
            _query_embedding.cache_clear()
        elif (
            EMB_MATRIX is not None
            and EMB_MATRIX.shape[0] == len(docs)
            and EMB_MATRIX.shape[1] == len(qv)
        ):
            qarr = np.asarray(qv, dtype=np.float32)
            norm = float(np.linalg.norm(qarr))
            if norm:
                qarr = qarr / norm
            vec_scores = (EMB_MATRIX @ qarr).tolist()
        else:
            for i, ev in enumerate(EMBS):
                vec_scores[i] = _cosine(qv, ev)

    # 欧盟国家统一映射到 eu 法规；美国可按州（us-<state>）进一步精确召回
    eu_countries = {"de", "fr", "es", "it", "nl", "be", "at", "pt", "ie", "fi", "se", "dk", "pl"}
    cc = (country_code or "").lower()
    state_code = (state_code or "").lower()
    target_tags = set()
    if cc:
        target_tags.add(cc)
        if cc in eu_countries:
            target_tags.add("eu")
        if cc == "us" and state_code:
            target_tags.add(f"us-{state_code}")

    results = []
    max_kw = max(kw_scores) if kw_scores else 0
    for i, d in enumerate(docs):
        meta = d["meta"]
        tag = (meta.get("tag") or "").lower()
        doc_tags = set((t or "").lower() for t in (meta.get("tags") or [tag]))
        kind = meta.get("kind", "")
        # 国家/州隔离：给定收货国时，法规类(law)只保留匹配该国或该州的；非法规不限制
        if cc and kind == "law" and not (doc_tags & target_tags):
            continue
        score = 0.55 * vec_scores[i] + 0.45 * (kw_scores[i] / max(1, max_kw))
        # 命中目标国/目标州法规额外加权，确保属地法优先；州级精确命中再额外加权
        if cc and kind == "law" and (doc_tags & target_tags):
            score += 0.12
            if state_code and cc == "us" and f"us-{state_code}" in doc_tags:
                score += 0.08
        results.append((score, d))

    results.sort(key=lambda x: x[0], reverse=True)
    out = []
    for score, d in results[:top_k]:
        if score < min_score:
            continue
        out.append({
            "id": d["id"],
            "title": d["title"],
            "text": d["text"],
            "meta": d["meta"],
            "score": round(score, 3),
            "source": f"{d['meta'].get('kind','')}-{d['meta'].get('topic','')}",
        })
    return out
