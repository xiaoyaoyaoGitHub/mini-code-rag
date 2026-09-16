"""
检索质量评测：Recall@K + MRR + 三路覆盖天花板
用法：
    PYTHONPATH=src-mine .venv/bin/python eval_recall.py
评测集放 eval/queries.jsonl，每行一条：
    {"query": "发布活动保存信息的接口", "gold": ["my-project:server/src/controller/publish.ts:28"]}
不依赖 LangGraph、不调大模型 —— 只测检索，不花钱。
"""
import json
from pathlib import Path

from rag_mine.config import load_config
from rag_mine.store import SqliteStore
from rag_mine.embed import get_embedder
from rag_mine.retrieve import rrf_fuse

TOP_K = 5          # 最终给大模型的条数
DEPTH = 15         # 每路召回深度（top_k * 3，和 graph.py 的 _recall_depth 一致）


def load_queries(path: str) -> list[dict]:
    queries = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            queries.append(json.loads(line))
    return queries


def recall_at_k(ranked_ids: list[str], gold_ids: list[str], k: int) -> float:
    hits = set(gold_ids) & set(ranked_ids[:k])
    return len(hits) / len(gold_ids)


def mrr(ranked_ids: list[str], gold_ids: list[str]) -> float:
    gold = set(gold_ids)
    for i, cid in enumerate(ranked_ids, 1):
        if cid in gold:
            return 1.0 / i
    return 0.0


def evaluate(queries: list[dict], cfg) -> None:
    store = SqliteStore(cfg)
    embedder = get_embedder(cfg)

    rows = []
    for q in queries:
        query, gold = q["query"], set(q["gold"])

        # ---- 三路召回（和 graph.py 三个节点同样的调用）----
        exact = store.search_exact(query, limit=DEPTH)
        bm25 = store.search_bm25(query, limit=DEPTH)
        vec = embedder.embed([query])[0]
        vector = store.search_vector(vec, limit=DEPTH)

        # ---- 三路覆盖天花板：去重后是否含 gold ----
        all_ids = {h["id"] for h in exact} | {h["id"] for h in bm25} | {h["id"] for h in vector}

        # ---- RRF 融合排序（和 node_fuse 同样的调用）----
        fused = rrf_fuse({"exact": exact, "bm25": bm25, "vector": vector},
                         cfg.retrieval.rrf_k)
        ranked = [cid for cid, _, _ in fused]

        rows.append({
            "query": q["query"],
            "recall@k": recall_at_k(ranked, q["gold"], TOP_K),
            "mrr": mrr(ranked, q["gold"]),
            "recall@depth": recall_at_k(ranked, q["gold"], DEPTH),
            "pool_hit": 1.0 if gold & all_ids else 0.0,
            "pool_size": len(all_ids),
        })

    store.close()

    # ---- 打印明细 ----
    print(f"{'query':<30} {'Recall@5':>9} {'MRR':>6} {'Recall@15':>10} {'天花板':>6} {'池':>4}")
    print("-" * 72)
    for r in rows:
        flag = "✓" if r["pool_hit"] else "✗"
        print(f"{r['query']:<30} {r['recall@k']:>9.2f} {r['mrr']:>6.2f} "
              f"{r['recall@depth']:>10.2f} {flag:>4} {r['pool_size']:>4}")

    # ---- 汇总 ----
    n = len(rows)
    avg = lambda key: sum(r[key] for r in rows) / n
    print("-" * 72)
    print(f"Recall@{TOP_K} = {avg('recall@k'):.2f}   MRR = {avg('mrr'):.2f}   "
          f"Recall@{DEPTH} = {avg('recall@depth'):.2f}   三路覆盖天花板 = {avg('pool_hit'):.2f}")

    # ---- 按指标定位问题在哪一层 ----
    if avg("pool_hit") < 1.0:
        print("\n→ 天花板 < 1：有 query 三路都没召回 gold，问题在召回层（分词/symbols/向量），")
        print("  排序调了也白调。逐条看 ✗ 的 query 先修召回。")
    elif avg("recall@k") < avg("recall@depth"):
        print("\n→ 天花板 = 1 但 Recall@5 拉不满：目标召回了但被排到 5 名开外，")
        print("  问题在排序层（RRF 权重 / is_strong 阈值），调排序。")
    elif avg("mrr") < 0.8:
        print("\n→ 目标都在 top5 但排名靠后：微调融合权重或 _index_text 的重复加权。")


if __name__ == "__main__":
    evaluate(load_queries("eval/queries.jsonl"), load_config("config.yaml"))
