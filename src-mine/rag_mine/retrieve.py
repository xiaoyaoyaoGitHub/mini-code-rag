
RRF_K = 60

# 倒数排名融合
def rrf_fuse(rankings:dict[str, list[dict]], k: int = RRF_K):
    print(f"ranking exact", len(rankings["exact"]))
    print(f"ranking bm25", len(rankings["bm25"]))
    print(f"ranking vector", len(rankings["vector"]))
    scores:dict[str, float] = {}
    ranks: dict[str,dict] = {}
    for name, hits in rankings.items():
        # 等级默认从 1 开始累加 (1,{})(2,{})
        for rank , c in enumerate(hits, 1):
            # print(f"name, rank, h",name, rank, h)
            cid = c['id']
            scores[cid] = scores.get(cid, 0.0) + 1 / (rank + k)
            ranks.setdefault(cid, {})[name] = rank
    order = sorted(scores, key=lambda c: -scores[c])
    return [(cid, scores[cid], ranks[cid]) for cid in order ]