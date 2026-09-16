"""
排序诊断：对 eval/queries.jsonl 的每条 query，看 gold 在三路各自排第几、
融合后排第几、被谁压在前面。用于「天花板=1 但 MRR 低」时定位排序层问题。

用法：
    PYTHONPATH=src-mine .venv/bin/python eval_diagnose.py
"""
import io
import json
import contextlib
from pathlib import Path

from rag_mine.config import load_config
from rag_mine.store import SqliteStore, expand_cjk
from rag_mine.embed import get_embedder
from rag_mine.retrieve import rrf_fuse

DEPTH = 15  # 和 eval_recall.py 保持一致


def load_queries(path: str) -> list[dict]:
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(json.loads(line))
    return out


def main() -> None:
    cfg = load_config("config.yaml")
    store = SqliteStore(cfg)
    embedder = get_embedder(cfg)

    for q in load_queries("eval/queries.jsonl"):
        query, golds = q["query"], q["gold"]

        # ---- 三路召回（同一套调用）----
        exact = store.search_exact(query, limit=DEPTH)
        bm25 = store.search_bm25(query, limit=DEPTH)
        vec = embedder.embed([query])[0]
        vector = store.search_vector(vec, limit=DEPTH)
        rankings = {"exact": exact, "bm25": bm25, "vector": vector}

        # ---- RRF 融合（顺手屏蔽 rrf_fuse 里的 print）----
        with contextlib.redirect_stdout(io.StringIO()):
            fused = rrf_fuse(rankings, cfg.retrieval.rrf_k)
        fused_ids = [cid for cid, _, _ in fused]

        print("=" * 72)
        print("query:", query)
        print("  bm25 实际拿去搜的 tokens:", expand_cjk(query))

        for gold in golds:
            # 三路里 gold 各自的名次
            per_route = {}
            for name, hits in rankings.items():
                ids = [h["id"] for h in hits]
                per_route[name] = ids.index(gold) + 1 if gold in ids else None
            # 融合后的名次
            fr = fused_ids.index(gold) + 1 if gold in fused_ids else None

            row = store.conn.execute(
                "SELECT name, breadcrumb FROM chunks WHERE id = ?", (gold,)
            ).fetchone()
            print(f"  gold: {gold}  (name={row[0]!r}, breadcrumb={row[1]!r})")
            pretty = {k: (f"#{v}" if v else "未召回") for k, v in per_route.items()}
            print(f"    三路名次: {pretty}  →  融合: #{fr}")

            # 融合后压在 gold 前面的都是谁
            if fr and fr > 1:
                print("    被谁压着:")
                for rank, (cid, score, ranks) in enumerate(fused[: fr - 1], 1):
                    print(f"      #{rank} score={score:.4f} ranks={ranks}  {cid}")

    store.close()


if __name__ == "__main__":
    main()
