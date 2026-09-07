#!/usr/bin/env python3
"""第 4 步：消融实验 —— 关掉某一路，看命中率掉多少。

    python tutorial/4_ablation.py

这是整个教程最有价值的一步。它会打出一张表，让你亲眼看到
「精确命中 > BM25 > 向量」这句话是怎么来的，而不是听我说的。

四种配置跑同一批问题：
  仅精确 / 仅 BM25 / 仅向量 / 三路 RRF

再附两组针对性演示：
  A. 中文查询下向量那一路为什么崩（假向量的边界）
  B. 同名符号下目录过滤怎么救命

跑完你会明白：为什么不能只上向量检索。
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DB_PATH, banner, load_script  # noqa: E402

idx = load_script("2_index.py")
ret = load_script("3_retrieve.py")

TOP_K = 5

# 问题和期望答案对照 tutorial/toy_repo/README.md 的答案表。
# expect 是文件路径片段，top-5 里任一 chunk 的路径含任一片段即算命中。
CASES = [
    {"q": "verify_password", "kind": "精确", "expect": ["utils/crypto.py"]},
    {"q": "validate_user", "kind": "精确", "expect": ["api/login.py", "service/user_service.py"]},
    {"q": "hash password", "kind": "模糊", "expect": ["utils/crypto.py"]},
    {"q": "下单时怎么扣库存", "kind": "模糊", "expect": ["service/order_service.py"]},
    {"q": "数据库连接在哪", "kind": "模糊", "expect": ["db/connection.py"]},
    {"q": "手机号格式怎么校验", "kind": "模糊", "expect": ["utils/validate.py"]},
    {"q": "登录时密码是怎么校验的", "kind": "中文", "expect": ["utils/crypto.py", "service/user_service.py"]},
    {"q": "取消订单", "kind": "中文", "expect": ["service/order_service.py", "api/order.py"]},
]


def disp_width(text):
    """显示宽度：中文占两列，英文占一列。

    终端对齐必须按显示宽度补空格，否则中英混排的表必然错位。
    """
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)


def pad(text, width):
    """按显示宽度右补空格。"""
    return text + " " * max(0, width - disp_width(text))


def rank_of_first_hit(results, expect):
    """第一次命中的名次（从 1 开始），没命中返回 None。

    返回名次而不是布尔值，是为了区分两种情况：
      命中在第 1 名  -> 排序没问题
      命中在第 4 名  -> 召回到了但排得靠后，该调融合或加重排
    只看 top-5 命中率会把第二种当成成功，从而掩盖真问题。
    """
    for i, r in enumerate(results, 1):
        if any(e in r["chunk"]["file"] for e in expect):
            return i
    return None


def top1_file(results):
    """第一名落在哪个文件，打不出来就给短横。"""
    if not results:
        return "—"
    return results[0]["chunk"]["file"]


def run(conn, query, only=None, dir_filter=None):
    return ret.retrieve(conn, query, top_n=TOP_K, only=only, dir_filter=dir_filter)


def main():
    if not DB_PATH.exists():
        sys.exit("先跑 python tutorial/2_index.py")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    configs = [
        ("仅精确", "exact"),
        ("仅 BM25", "bm25"),
        ("仅向量", "vector"),
        ("三路 RRF", None),
    ]

    banner("消融实验：关掉某一路会怎样")

    ranks = {}
    for case in CASES:
        for name, only in configs:
            ranks[(case["q"], name)] = rank_of_first_hit(run(conn, case["q"], only=only), case["expect"])

    col = 13
    head = "  " + pad("问题", 26) + pad("类型", 6) + "".join(pad(n, col) for n, _ in configs)
    print(head)
    print("  " + "-" * (disp_width(head) - 2))

    for case in CASES:
        line = "  " + pad(case["q"][:24], 26) + pad(case["kind"], 6)
        for name, _ in configs:
            rank = ranks[(case["q"], name)]
            line += pad(str(rank) if rank else "—", col)
        print(line)

    print("  " + "-" * (disp_width(head) - 2))

    stat = {}
    for name, _ in configs:
        got = [ranks[(c["q"], name)] for c in CASES]
        stat[name] = (
            sum(1 for r in got if r == 1),
            sum(1 for r in got if r and r <= TOP_K),
        )

    line = "  " + pad("命中 top-1", 26) + pad("", 6)
    line += "".join(pad(f"{stat[n][0]}/{len(CASES)}", col) for n, _ in configs)
    print(line)

    line = "  " + pad(f"命中 top-{TOP_K}", 26) + pad("", 6)
    line += "".join(pad(f"{stat[n][1]}/{len(CASES)}", col) for n, _ in configs)
    print(line)

    print()
    print("  格子里是「首次命中的名次」，— 表示 top-5 内没找到。")

    banner("怎么读这张表")

    e1, e5 = stat["仅精确"]
    b1, b5 = stat["仅 BM25"]
    v1, v5 = stat["仅向量"]
    f1, f5 = stat["三路 RRF"]

    print(f"  · 仅精确：top-1 {e1}/{len(CASES)}，top-5 {e5}/{len(CASES)}")
    print("    模糊和中文问题上基本全灭 —— 问「密码怎么校验」，")
    print("    它跟 verify_password 一个字符都对不上。但它一旦命中，名次必然是 1。")
    print()
    print(f"  · 仅 BM25：top-1 {b1}/{len(CASES)}，top-5 {b5}/{len(CASES)}")
    print("    覆盖最广的一路，因为关键词能同时吃下英文符号名和中文注释。")
    print("    单跑它其实已经不错 —— 这就是为什么 BM25 常常比向量更实用。")
    print()
    print(f"  · 仅向量：top-1 {v1}/{len(CASES)}，top-5 {v5}/{len(CASES)}")
    print("    注意 top-1 和 top-5 的差距：召回到了，但排得靠后。")
    print("    假向量只认字符重叠，会把名字长的测试函数排到业务代码前面。")
    print()
    print(f"  · 三路 RRF：top-1 {f1}/{len(CASES)}，top-5 {f5}/{len(CASES)}")
    print("    不是简单相加，是把三路互补的部分拼起来。")
    print("    任何一路单跑都有明显盲区，融合后盲区被互相补掉。")
    print()
    if f1 <= max(b1, e1, v1):
        print("  ⚠ 一句实话：在这个 33 个 chunk 的玩具库上，三路融合并没有打过单跑 BM25。")
        print("    两个原因：")
        print("      1. 库太小，BM25 几乎能覆盖全部内容，融合没有发挥空间")
        print("      2. 教程用的是假向量，它贡献的更多是噪声而不是互补信息")
        print("    融合的收益要到「库变大 + 换成真 embedding」之后才会显现。")
        print("    这一步要看的是机制（三路各自擅长什么），不是分数。")
        print()
    print("  结论：向量是兜底，不是主力。真实工程里大部分收益")
    print("  来自「精确 + 关键词」两路，向量负责接住前面接不住的长尾。")

    banner("A. 中文查询下，向量那一路为什么崩")
    q = "登录时密码是怎么校验的"
    print(f"  查询：{q}\n")
    for name, only in (("BM25", "bm25"), ("向量", "vector")):
        results = run(conn, q, only=only)
        print(f"  {name:6s} top1 -> {top1_file(results)}")
    print()
    print("  原因：本教程的向量是「字符 3-gram」造的假向量，只认字符重叠。")
    print("  「密码」和 verify_password 没有任何共同字符，余弦接近 0。")
    print("  BM25 能撑住，是因为索引时做过中文 2-gram 展开。")
    print()
    print("  这不是 bug，是刻意暴露的：它说明为什么真实工程必须换")
    print("  BGE-M3 / Qwen3-Embedding 这类真模型 —— 它们见过中英对齐，")
    print("  能把「密码校验」和 verify_password 映射到相近的向量上。")

    banner("B. 同名符号：目录过滤怎么救命")
    q = "validate_user"
    print(f"  查询：{q}（toy_repo 里有两处同名函数，做的事完全不同）\n")

    for label, d in (("不限目录", None), ("限定 service", "service")):
        results = run(conn, q, only=None, dir_filter=d)
        print(f"  {label}：")
        for r in results[:3]:
            print(f"      {r['chunk']['file']}:{r['chunk']['start_line']}  {r['chunk']['signature']}")
        print()

    print("  单项目里 index.ts / types.ts / utils.py 满天飞，")
    print("  同名符号是最高频的干扰源。限定目录是成本最低的消歧手段 ——")
    print("  这也是为什么元数据过滤的第一个维度是「目录」而不是项目名。")

    banner("还有一路没进这张表")
    print("  「verify_password 被谁调用」这类问题，三路召回都答不了。")
    print("  它走 calls 表，是确定性查询，不打分：\n")
    for row in idx.callers_of(conn, "verify_password"):
        print(f"      {row['file']}:{row['start_line']}  {row['name']}")

    conn.close()


if __name__ == "__main__":
    main()
