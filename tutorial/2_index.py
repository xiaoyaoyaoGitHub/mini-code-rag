#!/usr/bin/env python3
"""第 2 步：建索引 —— 让 chunk 能被三种方式查到。

    python tutorial/2_index.py

建四张表，对应三种召回方式 + 一张调用关系表：

  chunks       主表，存元信息和原文
  chunks_fts   FTS5，负责「关键词」召回（BM25）
  symbols      归一化符号名 -> chunk_id，负责「精确」召回
  chunk_vecs   向量，负责「语义」召回
  calls        调用关系，负责「这函数被谁调用」

为什么是三种？因为它们各自擅长完全不同的问题：

  问 verify_password        -> 精确命中，另外两路都可能被别的密码函数干扰
  问「密码怎么校验」        -> 关键词 + 语义，光靠精确一个字都对不上
  问「这函数被谁调用」      -> 只有 calls 能答，向量必错

跑完请重点看最后那组对比：
  搜 verify 有结果，搜「密码」会看到中文在 FTS5 里的真实处境
"""

import json
import re
import sqlite3
import sys
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    CHUNKS_PATH,
    DB_PATH,
    VEC_DIM,
    banner,
    hash_vector,
    norm_symbol,
)

SCHEMA = """
CREATE TABLE chunks (
  id          TEXT PRIMARY KEY,
  project     TEXT,
  file        TEXT,
  start_line  INTEGER,
  end_line    INTEGER,
  language    TEXT,
  kind        TEXT,
  name        TEXT,
  breadcrumb  TEXT,
  signature   TEXT,
  docstring   TEXT,
  code        TEXT,
  imports     TEXT,
  embed_text  TEXT
);

-- 用 contentless 之外的普通 fts5 表，自己 join chunks。
-- 不上 external content（content='chunks'）：那种模式下
-- delete 要手动维护同步，是真实工程里很常见的索引错乱来源。
CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id UNINDEXED, tokens);

CREATE TABLE symbols (
  norm      TEXT,
  chunk_id  TEXT
);

CREATE TABLE chunk_vecs (
  chunk_id  TEXT PRIMARY KEY,
  vec       BLOB
);

CREATE TABLE calls (
  chunk_id  TEXT,
  callee    TEXT
);
"""

INDEXES = """
CREATE INDEX idx_chunks_file   ON chunks(file);
CREATE INDEX idx_symbols_norm  ON symbols(norm);
CREATE INDEX idx_calls_callee  ON calls(callee);
"""

CJK = r"㐀-鿿"

# 虚词字。中文 2-gram 会切出大量「这个」「的了」这类碎片，
# 它们只贡献噪声：查询里带一个「这个」，就会命中所有注释里写过「这个」的代码。
#
# 注意只放纯虚词。别把「用」「做」「时」放进来 ——
# 那会连「用户」「做到」「同时」这些实词一起误伤。
STOP_CHARS = set("的了是在和就都也很到说要去会着这那你我他吗呢吧啊个把被让给但而或太更最")


def expand_cjk(text):
    """把文本切成 FTS5 能索引的 token 串。

    FTS5 默认的 unicode61 分词器按空格切词。中文没有空格，
    于是「校验用户密码」会被当成**一个** token。
    后果：搜「密码」搜不到，因为索引里根本没有「密码」这个 token ——
    只有「校验用户密码」这一整块。

    解决办法（零依赖版）：中文按 2-gram 展开再入索引，查询时同样展开。
    真实工程里可以换 jieba 分词，效果更好，但 2-gram 已经能工作。
    """
    out = []
    for tok in re.findall(rf"[{CJK}]+|[A-Za-z_][A-Za-z0-9_]*|\d+", text or ""):
        if re.match(rf"[{CJK}]", tok):
            if len(tok) == 1:
                if tok not in STOP_CHARS:
                    out.append(tok)
            else:
                # 含虚词的 2-gram 一律丢掉：「这个」「验的」都是噪声
                out += [
                    gram
                    for gram in (tok[i : i + 2] for i in range(len(tok) - 1))
                    if not (gram[0] in STOP_CHARS or gram[1] in STOP_CHARS)
                ]
        else:
            out.append(tok)
    return " ".join(out)


def index_text(chunk):
    """拼出要进 FTS5 的全文。权重靠重复实现：名字和面包屑多写几遍。

    这是个土办法，但很有效 —— 名字里出现的词，相关性天然应该更高。
    正式工程里可以用 FTS5 的 column 权重做同样的事。
    """
    parts = [
        chunk["name"],
        chunk["name"],
        chunk["breadcrumb"].replace(" › ", " "),
        chunk["docstring"],
        chunk["signature"],
        chunk["code"],
    ]
    return expand_cjk(" ".join(p for p in parts if p))


def load_chunks():
    """读第 1 步的产物。"""
    return [json.loads(line) for line in CHUNKS_PATH.read_text(encoding="utf-8").splitlines() if line]


def embedding_text(chunk):
    """和第 1 步里那个是同一个东西，这里再实现一遍是为了让脚本独立可读。"""
    parts = [
        f"# {chunk['breadcrumb']}",
        chunk["signature"],
        chunk["docstring"],
        chunk["code"],
    ]
    return "\n".join(p for p in parts if p)


# ---------------------------------------------------------------- 建库


def connect(fresh=True):
    """连库。fresh=True 时先删旧库 —— 教程里每次都重建，省得状态混乱。"""
    if fresh and DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn):
    conn.executescript(SCHEMA)
    conn.executescript(INDEXES)


def index_chunks(conn, chunks):
    """把 chunk 写进四张表。"""
    for chunk in chunks:
        # chunks 表
        conn.execute(
            """INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                chunk["id"],
                chunk["project"],
                chunk["file"],
                chunk["start_line"],
                chunk["end_line"],
                chunk["language"],
                chunk["kind"],
                chunk["name"],
                chunk["breadcrumb"],
                chunk["signature"],
                chunk["docstring"],
                chunk["code"],
                json.dumps(chunk["imports"], ensure_ascii=False),
                embedding_text(chunk),
            ),
        )
        # chunks_fts 表
        conn.execute(
            "INSERT INTO chunks_fts(chunk_id, tokens) VALUES (?,?)",
            (chunk["id"], index_text(chunk)),
        )

        # 一个 chunk 可能对应多个可查名字：symbols表
        # 方法既要能按 login 找到，也要能按 UserService.login 找到
        names = {chunk["name"], chunk["breadcrumb"].split(" › ")[-1]}
        if len(chunk["breadcrumb"].split(" › ")) > 2:
            names.add(".".join(chunk["breadcrumb"].split(" › ")[1:]))
        for name in names:
            norm = norm_symbol(name)
            if norm:
                conn.execute("INSERT INTO symbols VALUES (?,?)", (norm, chunk["id"]))

        # chunk_vecs 表
        vec = array("f", hash_vector(embedding_text(chunk)))
        conn.execute("INSERT INTO chunk_vecs VALUES (?,?)", (chunk["id"], vec.tobytes()))

        # calls（调用关系）
        for callee in chunk["calls"]:
            conn.execute("INSERT INTO calls VALUES (?,?)", (chunk["id"], callee))

    conn.commit()


# ---------------------------------------------------------------- 三种查询


def search_exact(conn, query, limit=10):
    """精确召回：符号名归一化后直接比对。

    问 verify_password 就该拿到 verify_password 本身，
    而不是某个语义相近的密码函数。这一路优先级最高。
    """
    norm = norm_symbol(query)
    if not norm:
        return []
    rows = conn.execute(
        """SELECT c.*, 1.0 AS score FROM chunks c
           JOIN symbols s ON s.chunk_id = c.id
           WHERE s.norm = ? OR s.norm LIKE ? || '%'
           LIMIT ?""",
        (norm, norm, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def safe_match(query):
    """把用户输入转成 FTS5 能吃的查询串。

    FTS5 的 MATCH 语法很挑剔，用户输入里带个括号或星号就直接报错。
    做法：只保留词，用 OR 连接（宁可多召回，漏召回更致命）。
    """
    toks = re.findall(rf"[{CJK}]+|[A-Za-z_][A-Za-z0-9_]*|\d+", query or "")
    if not toks:
        return None
    return " OR ".join(f'"{t}"' for t in toks)


def search_bm25(conn, query, limit=10, min_score=None):
    """关键词召回：FTS5 的 bm25 排序。

    bm25() 返回的是负相关分数（越小越相关），所以 ORDER BY 升序。

    min_score 是分数门槛，默认不启用 —— 原因值得看一眼：

      safe_match 用 OR 连接所有查询词，于是「碰巧有一个词命中」也会有结果，
      连问一个库里根本没有的东西都照样返回东西。所以直觉上该设个门槛。

      但 bm25() 的返回值**不能跨查询比较** —— 它是「命中词数 × IDF」的累积值，
      问句越长、命中的词越多，绝对值就越大。同一个 -3.0，
      在长问句里可能是噪声，在短问句里可能就是唯一的正确答案。

      能用的替代方案：归一化后再切（raw / top1_raw），
      或者干脆上重排模型，让模型来判断相关性而不是靠分数硬切。
      玩具库只有 33 个 chunk，统计信号太弱，这里默认不启用。
    """
    match = safe_match(expand_cjk(query))
    if not match:
        return []

    sql = """SELECT c.*, bm25(chunks_fts) AS raw FROM chunks_fts
             JOIN chunks c ON c.id = chunks_fts.chunk_id
             WHERE chunks_fts MATCH ?"""
    params = [match]
    if min_score is not None:
        sql += " AND bm25(chunks_fts) <= ?"
        params.append(min_score)
    sql += " ORDER BY raw LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return [{"raw": r["raw"], **{k: r[k] for k in r.keys() if k != "raw"}} for r in rows]


def load_vectors(conn):
    """一次性把向量读进内存。

    玩具库 33 个 chunk，全表扫无所谓。
    真实工程到几十万 chunk 时这里会爆，必须用 sqlite-vec / Qdrant
    做近似最近邻（ANN）—— 这就是正式工程里 store.py 要抽象 VectorStore 的原因。
    """
    out = {}
    for chunk_id, blob in conn.execute("SELECT chunk_id, vec FROM chunk_vecs"):
        vec = array("f")
        vec.frombytes(blob)
        out[chunk_id] = vec
    return out


def callers_of(conn, callee):
    """查「谁调用了这个符号」—— 第四种查询，不属于三路召回。

    这是确定性查询，走 calls 表，不打分。
    向量检索答不了这类问题：它只知道语义相近，不知道边。
    """
    rows = conn.execute(
        """SELECT c.* FROM calls
           JOIN chunks c ON c.id = calls.chunk_id
           WHERE calls.callee = ?""",
        (callee,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- 主流程


def main():
    banner("第 2 步：建索引")

    chunks = load_chunks()
    print(f"读入 {len(chunks)} 个 chunk")

    conn = connect(fresh=True)
    init_schema(conn)
    index_chunks(conn, chunks)

    for table in ("chunks", "symbols", "chunk_vecs", "calls"):
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        # 表名左对齐占 12个字符宽
        print(f"  {table:12s} {n} 行")
    print(f"\n数据库：{DB_PATH}")

    banner("对比：英文 vs 中文在 FTS5 里的表现")
    print("这是整个教程里最值得看的一组对比。\n")

    for q in ("verify password", "密码 校验"):
        hits = search_bm25(conn, q, limit=3)
        print(f"查询 {q!r}  ->  {len(hits)} 条")
        for h in hits:
            print(f"    {h['breadcrumb']}")

    print()
    print("为什么中文能查到：索引时 expand_cjk 把中文按 2-gram 切开，")
    print("查询时做同样的展开。不展开的话 FTS5 会把整句中文当成一个 token，")
    print("搜「密码」永远搜不到「校验用户密码」里的那两个字。")

    banner("精确召回：符号名")
    for h in search_exact(conn, "verify_password", limit=3):
        print(f"    {h['breadcrumb']}   {h['file']}:{h['start_line']}")
    print()
    print("注意：查 verify_password 拿到的是那个函数本身。")
    print("如果这一路缺失，向量很可能返回一个不相干的密码相关函数。")

    banner("第四种查询：谁调用了 verify_password")
    for h in callers_of(conn, "verify_password"):
        print(f"    {h['breadcrumb']}   {h['file']}:{h['start_line']}")
    print()
    print("这一路不走召回，直接查 calls 表。")
    print("「被谁调用」是确定性事实，必须查表，不能靠相似度。")

    conn.close()


if __name__ == "__main__":
    main()
