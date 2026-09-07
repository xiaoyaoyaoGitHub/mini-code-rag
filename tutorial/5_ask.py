#!/usr/bin/env python3
"""第 5 步：问答 —— 把检索结果喂给模型。

    python tutorial/5_ask.py "登录时密码是怎么校验的"
    python tutorial/5_ask.py "这个项目用 Redis 做缓存吗"   # 库里没有，看兜底

这一步不调真模型（保持零依赖），而是把**拼好的 prompt 完整打出来**。
因为整个 RAG 里最值得琢磨的东西就在这里：模型到底看到了什么。

生成环节有三个硬性要求，缺一个这系统就不能用：

  1. 每个片段必须带 `文件:行号`
     没有出处，用户没法验证，答案再对也不可信。

  2. 强制引用来源
     不引用就没法做「来源对不对 / 答案对不对」的分别统计，
     出了问题你根本不知道该改检索还是改 prompt。

  3. 检索为空时直接说没找到，不许硬编
     RAG 最典型的翻车：库里根本没有，模型照样编一段像模像样的答案。
     必须在 prompt 里写死兜底话术，并且**代码层面直接短路不调模型**。
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DB_PATH, banner, load_script  # noqa: E402

ret = load_script("3_retrieve.py")
idx = load_script("2_index.py")

SYSTEM = """你是这个代码库的助手。只根据下面给出的代码片段回答问题。

规则：
1. 每个结论后面标注来源，格式 [文件:行号]。
2. 片段里没有的内容，直接回答"在这些片段里没有找到依据"，不要推测。
3. 如果片段之间互相矛盾，把矛盾点说出来，不要自己选一个。
4. 不要因为"看起来应该如此"就补充片段里没有的实现细节。"""


def build_prompt(query, results):
    """把检索结果拼成给模型的 prompt。

    顺序按 RRF 分数从高到低。片段之间用分隔线隔开，
    模型对「第几个片段」的感知比连续文本清晰得多。
    """
    parts = [SYSTEM, "", "## 检索到的代码片段", ""]

    for i, r in enumerate(results, 1):
        c = r["chunk"]
        parts.append(f"### 片段 {i}  {c['file']}:{c['start_line']}-{c['end_line']}")
        parts.append(f"路径：{c['breadcrumb']}")
        if c["docstring"]:
            parts.append(f"说明：{c['docstring']}")
        parts.append("")
        parts.append("```" + c["language"])
        parts.append(c["code"])
        parts.append("```")
        parts.append("")

    parts.append("## 问题")
    parts.append(query)
    parts.append("")
    parts.append("回答时记得标注来源 [文件:行号]。")
    return "\n".join(parts)


def is_strong(result, min_sim):
    """这条结果够不够强，值不值得喂给模型。

    这里有个反直觉但很有用的事实：**RRF 分数本身就是相关性信号**。

      三路都命中 -> 分数约 0.03+（每路贡献约 0.016）
      只在单路勉强命中 -> 分数约 0.016

    所以「多路都沾边」和「一路碰巧撞上」在分数上是分得开的。
    这比去卡 bm25 的绝对分数靠谱得多（bm25 的值不能跨查询比较）。

    唯一豁免：精确命中。符号名对上了就是确定性事实，
    哪怕只有这一路命中也不该丢。

    局限：这个信号依赖「每一路本身是可靠的」。
    本教程用的是假向量，它给的排名本身就是噪声，
    于是噪声查询也照样能凑出「多路命中」的高分 ——
    你会发现门槛砍掉了大部分噪声，但砍不干净。
    换成真 embedding 之后这个门槛才真正准；
    在那之前，彻底的办法是加一层重排模型。
    """
    if "exact" in result["ranks"]:
        return True
    return result["score"] >= min_sim


def mock_generate(query, results):
    """不调模型，用规则拼一个「答案长什么样」的示例。

    真模型会写出通顺的段落；这里只负责展示答案里**必须有什么**：
    每句话后面挂来源，以及片段里没有的东西不乱说。
    """
    lines = []
    for r in results[:3]:
        c = r["chunk"]
        lines.append(
            f"- {c['file']}:{c['start_line']} 的 {c['kind']} `{c['name']}` "
            f"（{c['signature']}）与这个问题相关。"
        )
        if c["docstring"]:
            lines.append(f"  说明：{c['docstring']}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="问答：检索并拼 prompt")
    ap.add_argument("query", nargs="?", default="登录时密码是怎么校验的")
    ap.add_argument("--top", type=int, default=4)
    ap.add_argument("--dir", default=None)
    ap.add_argument(
        "--min-sim",
        type=float,
        default=0.02,
        help="RRF 分数下限，低于此值的结果当噪声丢掉（0 表示不过滤）",
    )
    ap.add_argument("--no-prompt", action="store_true", help="不打 prompt，只看结果")
    args = ap.parse_args()

    if not DB_PATH.exists():
        sys.exit("先跑 python tutorial/2_index.py")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    raw = ret.retrieve(conn, args.query, top_n=args.top, dir_filter=args.dir)
    results = [r for r in raw if is_strong(r, args.min_sim)]
    dropped = len(raw) - len(results)

    banner(f"问题：{args.query}")

    if dropped:
        print(f"  （{dropped} 条因分数低于 {args.min_sim} 被判为噪声，已丢弃）\n")

    if not results:
        print("  检索结果为空 —— 没有任何一条够格喂给模型。")
        print()
        print("  这时候**不要**把空上下文丢给模型 —— 那样模型会开始编。")
        print("  正确的做法是代码层面直接短路，返回兜底话术：")
        print()
        print('    "在这些片段里没有找到依据，无法回答。"')
        print()
        print("  这是 RAG 最常见的事故来源：宁可答「不知道」，")
        print("  也不要给一个看起来很像真的错误答案。")
        print()
        print("  顺带一个反直觉的事实：如果只靠「检索结果为空」来兜底，")
        print("  这个分支几乎永远不会触发 —— 向量那一路的余弦只要 > 0 就有结果，")
        print("  而任意两段文本的字符 n-gram 几乎总能撞上一点。")
        print("  所以真正的防线是上面那道分数门槛，不是空判断。")
        conn.close()
        return

    print(f"  检索到 {len(results)} 个片段：\n")
    for i, r in enumerate(results, 1):
        c = r["chunk"]
        print(f"  [{i}] {c['file']}:{c['start_line']}-{c['end_line']}  {c['breadcrumb']}")
        print(f"      RRF {r['score']:.5f}   三路排名 {r['ranks']}")

    if not args.no_prompt:
        banner("拼给模型的 prompt（模型实际看到的就是这些）")
        print()
        print(build_prompt(args.query, results))

        banner("prompt 有多大")
        prompt = build_prompt(args.query, results)
        print(f"  字符数：{len(prompt)}")
        print(f"  片段数：{len(results)}")
        print()
        print("  真实工程里要盯这个数字：片段给太多，成本和延迟都上去了，")
        print("  而且中间的片段容易被模型忽略（lost in the middle）。")
        print("  top-4 ~ top-8 是常见区间，超过 10 就该考虑先做重排。")

    banner("答案示例（规则生成，非模型输出）")
    print()
    print(mock_generate(args.query, results))

    banner("验收：两个维度必须分开统计")
    print("  来源对不对   -> 看上面 [1] [2] 这些片段里有没有正确答案所在的文件")
    print("                 错了就是检索问题，回去改切片或排除清单")
    print()
    print("  答案对不对   -> 模型有没有基于正确片段说对话，有没有编造")
    print("                 来源对但答案错，才是生成问题，改 prompt")
    print()
    print("  混成一个数字统计就白测了 —— 两者的优化方向完全不同。")

    conn.close()


if __name__ == "__main__":
    main()
