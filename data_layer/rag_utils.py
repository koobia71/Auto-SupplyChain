"""Data Layer RAG 工具。

本文件提供最小可用的 RAG 能力：
1. 将中国制造业 MRO 价格/供应商/谈判案例文本切块。
2. 构建 FAISS 向量索引并执行相似度检索。
3. 把检索结果拼装成可直接注入 Prompt 的上下文字符串。

设计原则：
- 优先使用真实向量检索（FAISS + Embeddings），让“今天判断”尽量基于数据证据。
- 允许在依赖缺失时安全降级，保证 MVP 端到端可运行。
- 检索结果结构化沉淀到 context，服务 Sequoia judgment -> intelligence 飞轮。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable

from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter


@dataclass
class RetrievedChunk:
    """检索片段数据结构。

    该结构用于把检索证据标准化，便于后续：
    1. 直接注入 Prompt；
    2. 写入审计日志；
    3. 后续升级为带来源追踪的评估数据集。
    """

    rank: int
    text: str


class HashEmbeddings(Embeddings):
    """MVP 兜底嵌入器（确定性哈希向量）。

    使用原因：
    - 当 HuggingFace / 云端嵌入不可用时，依然提供稳定向量空间；
    - 保证 FAISS 检索链路不断，便于本地开发与演示。
    """

    def __init__(self, dimensions: int = 256) -> None:
        self.dimensions = dimensions

    def _embed_text(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        vector = [0.0] * self.dimensions

        # 通过字符级哈希映射生成稳定稀疏向量。
        for idx, ch in enumerate(text):
            key = digest[idx % len(digest)]
            bucket = (ord(ch) + key + idx) % self.dimensions
            vector[bucket] += 1.0

        # L2 归一化，避免文本长度直接主导相似度。
        norm = sum(v * v for v in vector) ** 0.5
        if norm > 0:
            vector = [v / norm for v in vector]

        return vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_text(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_text(text)


def get_default_mro_benchmark() -> dict[str, Any]:
    """提供内置的模拟 benchmark 数据。

    数据覆盖：
    - 1688 / 京东工业 / 本地经销三类路径
    - 单价区间与交付时效
    - 谈判与替代料经验

    这些数据是 MVP 阶段的“冷启动知识底座”，后续会被真实交付数据替换。
    """

    return {
        "category": "MRO备件",
        "city_focus": ["东莞", "苏州"],
        "entries": [
            {
                "source": "1688",
                "item_name": "气动电磁阀",
                "spec": "4V210-08, DC24V",
                "price_range": "52-60 元",
                "lead_time": "2-4天",
                "risk": "同款店铺差异大，需核验质保与实拍参数。",
            },
            {
                "source": "京东工业",
                "item_name": "气动电磁阀",
                "spec": "4V210-08, DC24V",
                "price_range": "60-72 元",
                "lead_time": "次日/隔日达",
                "risk": "价格较高但票据与交付稳定。",
            },
            {
                "source": "本地经销",
                "item_name": "气动电磁阀",
                "spec": "4V210-08, DC24V",
                "price_range": "58-68 元",
                "lead_time": "1-2天",
                "risk": "紧急响应强，但需防止临时溢价。",
            },
            {
                "source": "历史谈判案例",
                "item_name": "气动元件类",
                "spec": "同参数替代",
                "price_range": "目标降本10%-18%",
                "lead_time": "按周滚动补货",
                "risk": "替代料必须先小批验证，避免停线。",
            },
        ],
    }


def _flatten_benchmark_to_texts(benchmark_data: dict[str, Any]) -> list[str]:
    """把 benchmark JSON 展平为可检索文本集合。"""

    texts: list[str] = []

    entries = benchmark_data.get("entries", [])
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict):
                texts.append(json.dumps(entry, ensure_ascii=False))
            else:
                texts.append(str(entry))

    # 为增强召回，也把顶层信息单独作为一个文档。
    top_level = {
        "category": benchmark_data.get("category", "MRO"),
        "city_focus": benchmark_data.get("city_focus", []),
    }
    texts.append(json.dumps(top_level, ensure_ascii=False))

    return texts


def _split_texts(raw_texts: Iterable[str]) -> list[str]:
    """对原始文本做切块，适配 FAISS 检索。"""

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=220,
        chunk_overlap=40,
        separators=["\n\n", "\n", "。", "，", " "],
    )

    chunks: list[str] = []
    for text in raw_texts:
        for chunk in splitter.split_text(text):
            cleaned = chunk.strip()
            if cleaned:
                chunks.append(cleaned)

    return chunks


def _get_embedding_model() -> Embeddings:
    """获取嵌入模型：优先 HuggingFace，失败则哈希嵌入。"""

    try:
        from langchain_community.embeddings import HuggingFaceEmbeddings

        return HuggingFaceEmbeddings(
            model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
    except Exception:
        return HashEmbeddings(dimensions=256)


def _fallback_keyword_retrieve(chunks: list[str], query: str, top_k: int) -> list[RetrievedChunk]:
    """当 FAISS 不可用时的关键词回退检索。"""

    query_terms = [t for t in query.replace(",", " ").split() if t]

    scored: list[tuple[int, str]] = []
    for chunk in chunks:
        score = 0
        for term in query_terms:
            if term and term in chunk:
                score += 1
        scored.append((score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    selected = scored[: max(1, top_k)]

    return [RetrievedChunk(rank=i + 1, text=item[1]) for i, item in enumerate(selected)]


def retrieve_context_from_benchmark(
    query: str,
    benchmark_data: dict[str, Any],
    top_k: int = 4,
) -> str:
    """基于 benchmark 数据执行检索，并返回 Prompt 可注入上下文字符串。

    返回格式示例：
    [RAG-1] ...
    [RAG-2] ...

    该文本会写入 state["context"]["retrieved_context"]，
    让分析/调研/推荐节点都能共享同一组证据。
    """

    raw_texts = _flatten_benchmark_to_texts(benchmark_data)
    chunks = _split_texts(raw_texts)

    if not chunks:
        return "暂无可用RAG上下文。"

    retrieved: list[RetrievedChunk]

    try:
        from langchain_community.vectorstores import FAISS

        embeddings = _get_embedding_model()
        vector_store = FAISS.from_texts(chunks, embedding=embeddings)

        docs = vector_store.similarity_search(query, k=max(1, top_k))
        retrieved = [
            RetrievedChunk(rank=i + 1, text=doc.page_content.strip())
            for i, doc in enumerate(docs)
            if doc.page_content.strip()
        ]

        if not retrieved:
            retrieved = _fallback_keyword_retrieve(chunks, query, top_k)

    except Exception:
        # 当 FAISS 或向量依赖不可用时，仍提供可运行检索结果。
        retrieved = _fallback_keyword_retrieve(chunks, query, top_k)

    lines = [f"[RAG-{item.rank}] {item.text}" for item in retrieved]
    return "\n".join(lines)
