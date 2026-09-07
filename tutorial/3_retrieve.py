#!/usr/bin/env python3
"""第 3 步：三路召回 + RRF 融合 —— 检索层的核心。

    python tutorial/3_retrieve.py "密码是怎么校验的"
    python tutorial/3_retrieve.py "validate_user" --dir service
    python tutorial/3_retrieve.py "verify_password" --only exact

三路召回：
  ① 精确    符号名归一化后比对，问 A 就给 A，不给「像 A 的 B」
  ② BM25    关键词，FTS5 算的相关性
  ③ 向量    语义兜底，只在前面两路都接不住时才真正发力

为什么不用加权平均？因为三路的分数根本不可比：
  bm25() 返回负数且量纲随意，余弦在 0~1，精确命中只有 0/1。
  把它们加权平均，等于拿不同单位的数做加法，权重怎么调都是拍脑袋。

RRF（Reciprocal Rank Fusion）只认排名，不认分数：

    score(d) = Σ  1 / (k + rank_i(d))

  k=60 是经验值，一般不调。它天然免疫量纲问题，
  而且「在三路里都排第一」的文档会显著高于「某一路第一、其余没进」。

跑完重点看那张排名表：同一条 chunk 在三路里的排名差异，
以及融合后谁上来了 —— 这就是 RRF 在起作用。
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    DB_PATH,
    banner,
    cosine,
    hash_vector,
    load_script,
    print_hits,
)

idx = load_script("2_index.py")
search_exact = idx.search_exact
search_bm25 = idx.search_bm25
load_vectors = idx.load_vectors
expand_cjk = idx.expand_cjk

RRF_K = 60

# 每路的召回深度 = top_n 的倍数。融合后再截到 top_n。
# 真实工程里每路常常召回 top-50 ~ top-200，最后只给用户看 5 条。
#
# 深度不是越大越好：召回太深时，「在多路里都出现」变得太容易，
# 反而会淹没「某一路明确排第一」的信号。小库上尤其明显。
RECALL_DEPTH = 3


def search_vector(conn, query, limit=10, vecs=None):
    """语义召回。用的是 _common 里的假向量（字符 n-gram）。

    玩具库 33 条，直接全表扫算余弦。
    真实规模要用 sqlite-vec / Qdrant 做 ANN，否则每次查询 O(n)。
    """
    vecs = vecs if vecs is not None else load_vectors(conn)
    qvec = hash_vector(expand_cjk(query) or query)
    scored = [(cid, cosine(qvec, vec)) for cid, vec in vecs.items()]
    scored.sort(key=lambda x: -x[1])

    out = []
    for cid, score in scored[:limit]:
        row = conn.execute("SELECT * FROM chunks WHERE id = ?", (cid,)).fetchone()
        if row and score > 0:
            out.append({**dict(row), "score": score})
    return out


def rrf_fuse(rankings, k=RRF_K):
    """把多路排名融合成一路。rank 从 1 开始。

    返回 [(chunk, score, {路名: 排名})]，按 score 降序。
    """
    scores, ranks = {}, {}
    for name, hits in rankings.items():
        for rank, hit in enumerate(hits, 1):
            cid = hit["id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
            ranks.setdefault(cid, {})[name] = rank

    order = sorted(scores, key=lambda c: -scores[c])
    return [(cid, scores[cid], ranks[cid]) for cid in order]


def apply_filters(conn, hits, dir_filter=None, language=None):
    """元数据过滤。单项目里最有用的是「目录」。

    同名符号满天飞时（utils.py / types.py / validate 到处都是），
    限定目录是唯一能快速消歧的手段。
    """
    if not dir_filter and not language:
        return hits
    out = []
    for hit in hits:
        chunk = hit["chunk"]
        if dir_filter and dir_filter not in chunk["file"]:
            continue
        if language and chunk["language"] != language:
            continue
        out.append(hit)
    return out


def retrieve(conn, query, top_n=10, dir_filter=None, only=None, verbose=False, depth=None):
    """跑三路召回 + RRF 融合。

    only 用来做消融实验（见 4_ablation.py）：
    only="exact" 就只跑精确那一路，看它自己能答对多少。

    每路先按 depth 召回，融合后再截到 top_n。为什么不能直接按 top_n 召回：

      假设某 chunk 在两路都排第 5，另一 chunk 只在两路排第 1。
      如果每路只取前 4，前者的「两路第 5」就被抹掉了，
      融合时只剩后者，排序直接反转。

      融合的价值恰恰来自「在**更多**路里都出现」，
      召回太浅等于把这个信号掐死在源头。

    depth 可以手动调小来亲眼看到这个反转，见 main() 里的对照输出：

        python3 3_retrieve.py "verify_password" --depth 1
    """
    vecs = load_vectors(conn)
    depth = depth if depth is not None else top_n * RECALL_DEPTH

    sources = {}
    if only in (None, "exact"):
        sources["exact"] = search_exact(conn, query, limit=depth)
    if only in (None, "bm25"):
        sources["bm25"] = search_bm25(conn, query, limit=depth)
    if only in (None, "vector"):
        sources["vector"] = search_vector(conn, query, limit=depth, vecs=vecs)

    fused = rrf_fuse(sources, k=RRF_K)

    by_id = {}
    for hits in sources.values():
        for h in hits:
            by_id[h["id"]] = h

    out = []
    for cid, score, ranks in fused[:top_n]:
        chunk = by_id[cid]
        out.append({"chunk": chunk, "score": score, "ranks": ranks})
    return apply_filters(conn, out, dir_filter=dir_filter)


# ---------------------------------------------------------------- 主流程


def main():
    ap = argparse.ArgumentParser(description="三路召回 + RRF 融合")
    ap.add_argument("query", nargs="?", default="密码是怎么校验的")
    ap.add_argument("--dir", default=None, help="只保留路径里含该字符串的 chunk")
    ap.add_argument("--only", choices=["exact", "bm25", "vector"], default=None)
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument(
        "--depth", type=int, default=None,
        help=f"每路先召回多少条再融合（默认 top x {RECALL_DEPTH}）。"
             f"故意调小能亲眼看到排序反转，试试 --depth 1",
    )
    args = ap.parse_args()

    if not DB_PATH.exists():
        sys.exit("先跑 python tutorial/2_index.py")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    banner(f"查询：{args.query}" + (f"   [仅 {args.only}]" if args.only else ""))

    depth = args.depth if args.depth is not None else args.top * RECALL_DEPTH
    show_n = min(args.top, depth)  # 展示条数不超过实际召回，免得看着比融合的多

    vecs = load_vectors(conn)
    sources = {}
    if args.only in (None, "exact"):
        sources["exact"] = search_exact(conn, args.query, limit=show_n)
    if args.only in (None, "bm25"):
        sources["bm25"] = search_bm25(conn, args.query, limit=show_n)
    if args.only in (None, "vector"):
        sources["vector"] = search_vector(conn, args.query, limit=show_n, vecs=vecs)

    print(f"（每路展示 top-{show_n}；融合时每路实际召回 {depth} 条）\n")
    for name, title in (("exact", "① 精确"), ("bm25", "② BM25"), ("vector", "③ 向量")):
        if name in sources:
            print_hits(title, [{"chunk": h, "score": h.get("score", 0)} for h in sources[name]])

    results = retrieve(
        conn, args.query, top_n=args.top, dir_filter=args.dir, only=args.only, depth=args.depth
    )

    banner("RRF 融合后")

    if not results:
        print("  三路都没召回任何东西。")
        print("  排查顺序：切片是否切碎 -> 排除清单是否把目标文件排掉了 -> 中文分词")
        return

    print(f"  {'chunk':46s} 精确  BM25  向量     RRF")
    print("  " + "-" * 74)
    for r in results:
        c = r["chunk"]
        label = f"{c['file']}:{c['start_line']} {c['name']}"
        label = label[:46]
        rk = r["ranks"]
        cells = [
            f"{rk[name]:^5d}" if name in rk else "  -  "
            for name in ("exact", "bm25", "vector")
        ]
        print(f"  {label:46s} " + " ".join(cells) + f"  {r['score']:.5f}")

    top = results[0]
    banner("RRF 得分是怎么算出来的（以第一名为例）")
    print(f"  {top['chunk']['breadcrumb']}\n")
    for name, rank in top["ranks"].items():
        print(f"    {name:7s} 第 {rank} 名  ->  1 / ({RRF_K} + {rank}) = {1/(RRF_K+rank):.5f}")
    print(f"    {'合计':7s} {'':9s}     {top['score']:.5f}")
    print()
    print("  注意看：融合分数不是「谁的分数高谁赢」，而是「谁在更多路里都靠前」。")
    print("  只在一路排第一、另外两路没进的，会被三路都靠前的挤下去。")

    if len(top["ranks"]) >= 2 and min(top["ranks"].values()) > 1:
        print()
        print("  ⚠ 这里有个权衡要看清楚：k=60 把名次差异压得很平。")
        print(f"    第 1 名得 {1/(RRF_K+1):.5f}，第 5 名得 {1/(RRF_K+5):.5f}，只差 "
              f"{(1/(RRF_K+1))/(1/(RRF_K+5))-1:.0%}。")
        print("    于是「三路都排第 5」会压过「一路第 1、一路第 15」。")
        print("    这在真 embedding 下通常是对的（多路都沾边 = 真相关），")
        print("    但本教程用的是假向量，它给的排名本身是噪声，")
        print("    所以你会看到一些不太合理的排序 —— 那是向量的锅，不是 RRF 的。")
        print()
        print("    缓解办法（真实工程三选一）：")
        print("      · 调小 k（比如 10~20），放大名次之间的差异")
        print("      · 控制召回深度，别让「在多路出现」变得太廉价")
        print("      · 加一层重排模型，让模型直接判断相关性")

    if args.depth is not None:
        normal_depth = args.top * RECALL_DEPTH
        if depth != normal_depth:
            banner(f"对照实验：把召回深度改回默认的 {normal_depth} 条")
            normal = retrieve(
                conn, args.query, top_n=args.top, dir_filter=args.dir,
                only=args.only, depth=normal_depth,
            )
            for i, r in enumerate(normal[:3], 1):
                c = r["chunk"]
                ranks = r["ranks"]
                marks = []
                for name in ("exact", "bm25", "vector"):
                    if name in ranks:
                        marks.append(str(name) + "#" + str(ranks[name]))
                print(f"  {i}. [" + "/".join(marks) + f"] {c['file']}:{c['start_line']} {c['name']}")
            print()
            print(f"  和上面 depth={depth} 的结果对比一下。召回太浅时，")
            print("  有的 chunk 压根没机会进入融合，于是「在几路里都排第 5」")
            print("  这个信号被掐死在源头，排序直接反转。")
            print("  真实工程每路常常召回 top-50 ~ top-200，最后只给用户看 5 条，")
            print("  就是为了保住这个信号。")

    banner("第一名原文")
    c = top["chunk"]
    print(f"  {c['file']}:{c['start_line']}-{c['end_line']}   {c['signature']}")
    print()
    for line in c["code"].splitlines():
        print(f"    {line}")

    conn.close()


if __name__ == "__main__":
    main()
