# code-rag

> **第一次接触这套东西？先读 [`tutorial/`](tutorial/)**
> 那里是一套零依赖、能直接跑通的最小实现，每一步都把中间产物打印出来，
> 并且刻意暴露了几个真实的坑。本目录的 `src/` 是同一流程的工程化实现，
> 用 tree-sitter（多语言）+ 真 embedding + sqlite-vec 替代了教程里的简化版。
> 建议先把教程跑一遍理解原理，再看 `src/` 的工程化写法。
>
> 实现细节见 [`IMPLEMENTATION.md`](IMPLEMENTATION.md)。

单项目代码库 RAG：AST 切片 → 混合检索 → 增量更新。

```
离线（跑一次，之后只做增量）    代码文件 → AST 切片 → 嵌入 → 索引库
在线（每次提问都跑）            提问 → 三路召回 → RRF 融合 → 生成答案
```

两条链路的迭代节奏完全不同，分开看。

## 上手

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

改 `config.yaml` 里的 `project.root`，然后：

```bash
python scripts/0_stats.py        # 先看数字，回来补排除规则，再跑一次
```

## 目录

```
config.yaml            唯一的配置入口，整个工程只有 config.py 读它
scripts/
  0_stats.py           阶段 0  盘点 → stats.md
  1_build_chunks.py    阶段 1  解析切片 → data/chunks.jsonl
  2_build_index.py     阶段 2  建索引 → data/index.db
  3_ask.py             阶段 3  问答 CLI
  4_update.py          阶段 4  增量更新
src/code_rag/
  config.py            加载 / 校验 YAML，路径解析的唯一出口
  scan.py              文件遍历 + 三层排除 + 统计
  parse.py             AST 切片 ★ 决定效果上限（tree-sitter 多语言）
  embed.py             local(sentence-transformers) / api，dimension 自动探测
  store.py             SQLite + FTS5 + sqlite-vec，VectorStore 接口
  retrieve.py          三路召回 + RRF + prompt / 生成
  update.py            文件 hash 比对 + 删除清理
  cli.py               typer 入口（stats / chunk / index / ask / update）
eval/
  questions.yaml       20 题验收集（exact / fuzzy / callgraph 三类）
  run_eval.py          命中率报告 → eval/report.md
data/                  产物，不入库（index.db / chunks.jsonl）
```

## 阶段进度

| 阶段 | 内容 | 产出 | 验收 | 状态 |
|---|---|---|---|---|
| 0 | 盘点与配置 | `config.yaml` + `stats.md` | 排除比例 20–60%；top10 长文件人工看过 | ✅ |
| 1 | 解析与切片 ★ | `data/chunks.jsonl` | 抽 20 文件：无半个函数、无单独 import 段、面包裹屑读得懂 | ✅ |
| 2 | 索引与检索 ★ | `data/index.db` | 20 题 top-5 命中 ≥80% | ✅ |
| 3 | 问答 | CLI | 答案 + 来源分开统计 | ✅ |
| 4 | 增量更新 ★ | `update_index.py` | 改 1 个文件只处理 1 个；删除路径测过 | ✅ |
| 5 | 重排 + UI（可选） | — | 命中率卡在 70–80% 时再加 | ⬜ |

阶段 1、2 是真正的功夫所在，3、4 相对机械。

## 坑清单

- [ ] 生成代码排干净了没（`content_markers` 那层最容易漏，污染最重）
- [ ] chunk 里有没有半个函数 / 单独的 import 段
- [ ] 面包屑拼进 embedding 输入了没
- [ ] FTS5 中文分词处理了没（默认按空格分词，对中文几乎无效）
- [ ] `embedding.dimension` 别手填，首次运行自动探测后回写
- [ ] 增量更新的**删除**路径测了没
- [ ] 检索不到时的兜底话术加了没
- [ ] 测试文件**进**索引（`exclude_tests: false`）—— 测试名和断言是最精准的语义描述
