# 实现说明

`src/code_rag/` 是 `tutorial/` 的工程化实现：同一套流程（AST 切片 → 混合检索 → 增量更新），
换上了 tree-sitter（多语言）、真 embedding、sqlite-vec ANN。

跑通教程理解原理后，看这份文档对照 `src/` 的工程化写法。

## 文件清单

| 文件 | 内容 | 对应 tutorial |
|---|---|---|
| `config.py` | dataclass 加载 YAML、路径解析、维度回写 | — |
| `scan.py` | 三层排除 + 7 组统计 + stats.md 渲染 | `_common.py` 的排除逻辑 |
| `parse.py` | **tree-sitter 多语言切片**（Python/JS/TS/Go/Java/Rust/Rb） | `1_chunk.py` |
| `embed.py` | LocalEmbedder(sentence-transformers) + APIEmbedder + 维度探测 | `hash_vector`（假向量） |
| `store.py` | SqliteStore：6 张表 + 三路查询 + 删除清理 | `2_index.py` |
| `retrieve.py` | 三路召回 + RRF + 元数据过滤 + build_prompt + generate | `3_retrieve.py` + `5_ask.py` |
| `update.py` | file_hash 比对 + 增量处理 + 删除清理 | `6_update.py` |
| `cli.py` | typer 五子命令 + 编排逻辑 | — |
| `graph.py` | **LangGraph 版检索管线** + LangChain Embeddings 包装 | — |

## 和 tutorial 的关键区别

| 维度 | tutorial | src/ |
|---|---|---|
| 解析 | Python `ast`（单语言） | tree-sitter（9 种语言，`LANG_SPECS` 配置） |
| 向量 | 假向量（字符 3-gram hashing） | sentence-transformers（BGE-M3 / MiniLM） |
| 向量查询 | 全表扫余弦 | sqlite-vec ANN（`WHERE embedding MATCH ? AND k = ?`） |
| 存储 | sqlite3 裸 SQL | `SqliteStore` 类，实现 `VectorStore` 协议 |
| 入口 | `argparse` 脚本 | typer CLI（`code-rag` 命令）+ scripts 薄封装 |
| 生成 | 不调模型，规则拼答案 | 支持 openai / anthropic / ollama / vllm，provider=null 时回退规则拼装 |

## 怎么跑

### 用你的真实项目

```bash
# 1. 改 config.yaml 里的 project.root 指向你的项目
# 2. 按顺序跑
python scripts/0_stats.py          # 盘点 → stats.md
python scripts/1_build_chunks.py   # 切片 → data/chunks.jsonl
python scripts/2_build_index.py    # 建索引 → data/index.db（首次下载 BGE-M3 ~2GB）
python scripts/3_ask.py "你的问题"
python scripts/4_update.py         # 增量更新

# 或用 typer CLI
code-rag stats / chunk / index / ask / update
```

### 用 toy_repo 快速验证

`test_config.yaml` 用 `all-MiniLM-L6-v2`（80MB）替代 BGE-M3，方便快速跑通：

```bash
python scripts/0_stats.py --config test_config.yaml
python scripts/1_build_chunks.py --config test_config.yaml
python scripts/2_build_index.py --config test_config.yaml
python scripts/3_ask.py "verify_password" --config test_config.yaml --debug
python scripts/4_update.py --config test_config.yaml
```

## 端到端验证结果（toy_repo）

```
stats:  11 文件 / 保留 10 / 排除 1（generated/api_client.py）
chunk:  33 个 chunk（23 function / 6 method / 4 class）
index:  chunks=33  fts=33  symbols=39  vecs=33  calls=54  file_hash=10
ask:    "verify_password"      → 第一名 utils/crypto.py:18 ✓
        "密码是怎么校验的"      → 命中 crypto.py + user_service.py ✓
update: 新增 1 文件 → 处理 1 chunk；删除 → 清理 1 文件 ✓
```

## 模仿时的重点

按这个顺序看，每个文件都和 tutorial 对应：

### 1. `parse.py` — 最值得琢磨（效果上限所在）

- `walk_def_nodes`：递归遍历 AST，带父节点链 → 面包屑全靠它
- `get_signature`：签名 = 节点开头到 body 开始之间的文本（信息密度最高）
- `extract_calls`：找 call 节点，取被调函数名，过滤内置符号
- `embedding_text`：面包屑 + 签名 + docstring + code（喂给 embedding 的不是 code）
- `LANG_SPECS`：每种语言的节点类型配置，加语言只改这里

### 2. `store.py` — 三路查询的 SQL

- `_index_text`：名字重复两遍实现权重（土办法但有效）
- `expand_cjk`：中文按 2-gram 展开，否则 FTS5 搜「密码」搜不到「校验用户密码」
- `search_exact` / `search_bm25` / `search_vector`：三路各自的 SQL
- `delete_by_file`：删一个文件要清五张表，少一张就留孤儿记录

### 3. `retrieve.py` — RRF 融合

- `rrf_fuse`：为什么不用加权平均——三路分数不可比（精确 0/1、BM25 负数、余弦 0~1）
- `is_strong`：RRF 分数本身就是相关性信号，三路都命中 ≈ 0.03+，单路勉强 ≈ 0.016
- `build_prompt`：每个片段带 `文件:行号`，强制引用来源
- `ask`：检索为空时直接短路返回兜底话术，不调模型

## LangChain / LangGraph 接入（已实现）

`src/code_rag/graph.py` 是 LangGraph 版检索管线，和 `retrieve.py`（裸版）做同一件事，
编排方式不同。两版并存，用 `--langgraph` 开关切换：

```bash
# 裸版（函数调用，一条线串下来）
code-rag ask "verify_password" --config test_config.yaml

# LangGraph 版（三路召回是并行节点，RRF 是汇聚节点）
code-rag ask "verify_password" --config test_config.yaml --langgraph
```

两版结果完全一致——LangGraph 改变的是「怎么组织流程」，不是「怎么算」。
业务逻辑（RRF 公式、过滤规则、prompt 模板、生成调用）复用 `retrieve.py`，只换编排。

### graph.py 的结构

**LangChain 包装**：`CodeEmbeddings` 把 `LocalEmbedder` 包成 `langchain_core.embeddings.Embeddings`
接口（`embed_documents` / `embed_query`），和 LangChain 生态的所有 VectorStore / Chain 兼容。

**LangGraph StateGraph**：

```
        ┌─ exact ──┐
START ──┼─ bm25 ───┼─→ fuse ─→ filter ─→ prompt ─→ generate ─→ END
        └─ vector ─┘
```

- 三个召回节点从 `START` 扇出（并行），各写各的 state key（`exact_hits` / `bm25_hits` / `vector_hits`），不冲突
- `fuse` 节点有三条入边，LangGraph 等三者都完成才执行（join 语义）
- 后半段串行：`fuse → filter → prompt → generate`

### 对照学习

| 概念 | 裸版 `retrieve.py` | 图版 `graph.py` |
|---|---|---|
| 编排 | 函数调用，一条线 | StateGraph，节点 + 边 |
| 并行 | 顺序调用三路（实际串行） | 三路并行（同一 superstep） |
| 状态传递 | 函数返回值 | `RetrievalState` 共享字典 |
| RRF 融合 | `rrf_fuse()` 函数 | `node_fuse` 节点 |
| 过滤弱结果 | `is_strong()` | `node_filter` 节点 |
| 生成 | `generate()` | `node_generate` 节点 |

看的时候重点对比：`retrieve.retrieve()`（裸版入口）和 `graph.build_graph()`（图版入口），
同一个流程两种写法。

### 验证结果（toy_repo）

```
LangGraph 版 debug 输出：
  exact:  1 条
  bm25:   5 条
  vector: 15 条
  fused:  15 条（RRF 融合后）
  过滤后: 5 条

第一名：utils/crypto.py:18  RRF=0.04815  ranks={exact:1, bm25:2, vector:4}
（和裸版完全一致）
```

## 已知限制

- 超长函数（> max_lines）未按嵌套函数再切（tutorial 也没实现）
- calls 只抽到名字，没解析到定义位置（`self.login` 只拿到 `login`）
- `LANG_SPECS` 里非 Python 语言的 docstring 抽取是简化处理
- FTS5 中文用 2-gram，效果不如 jieba 分词
- LangGraph 并行节点跨线程读 SQLite，已用 `check_same_thread=False` 解决（三路召回只读，并发安全）
