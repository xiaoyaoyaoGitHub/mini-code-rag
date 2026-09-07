#!/usr/bin/env python3
"""跑验收集，出命中率报告 -> eval/report.md

  python eval/run_eval.py                 # 只测检索层（快，不花钱）
  python eval/run_eval.py --with-answers  # 连生成层一起跑，答案 dump 出来人工判

报告分三层看，缺一层就定位不到问题：
  1. 总体 top-5 命中率       —— 有没有到 80%
  2. 按题型分组              —— 哪类题型是短板，直接指向要改哪一层
  3. 逐题明细                —— 具体哪几题挂了

题型短板 -> 改哪里（对照表）：
  exact 低      -> symbols 表 / 归一化规则（阶段 2）
  fuzzy 低      -> 切片质量、面包屑有没有拼进 embedding 输入（阶段 1，最常见）
  callgraph 低  -> calls 表抽取不全（阶段 1 的 extract_calls）

检索命中率 <60% 时先别换 embedding 模型。按这个顺序排查：
  切片 -> 排除清单 -> 面包屑。90% 的问题在切片。

--with-answers 的输出只 dump 答案，不自动判对错 —— 「答案对不对」必须人来判。
把「来源对不对」（自动算）和「答案对不对」（人工标）混成一个数字等于白测。
"""

# TODO: load_questions(path="eval/questions.yaml") -> list[Question]
#       跳过 expect 全空的题（那是不确定答案的题，进统计就是自欺欺人）
# TODO: hit_at_k(hits, q) -> bool    file 包含 expect_files 任一 或 name/breadcrumb
#       匹配 expect_symbols 任一（大小写不敏感），top-k 内任一命中即算
# TODO: run_retrieval(questions, cfg) -> list[EvalRow]
#       EvalRow: id / type / question / top5 的 (file:line, score) / 是否命中
# TODO: run_generation(rows, cfg)    可选，答案写进 report，人工判
# TODO: render_report(rows) -> str   markdown：总体 + 分组 + 逐题明细 + 挂掉的题置顶
# TODO: 挂掉的题要在报告里把 top-5 全列出来 —— 看一眼就知道是「没召回」还是
#       「召回了但排第 6」，这两种的优化方向完全不同


def main() -> None:
    raise NotImplementedError("等 src/code_rag/retrieve.py 实现后再接上")


if __name__ == "__main__":
    main()
