import os

import typer
import time
from pathlib import Path
from rich.console import Console
from rich.table import Table
from .config import load_config, Config
from .scan import file_stats,render_stats
from .parse import iter_chunks,write_jsonl,read_jsonl
from .embed import embedding_text,probe_dimension,get_embedder
from .store import SqliteStore

console = Console()

# 创建一个 CLI 应用对象，help 是 --help时的显示说明 @app.command() 注册命令
app = typer.Typer(help="单项目代码库 RAG：AST切片 + 混合检索 + 增量更新")



def _cfg(config: str = 'config.yaml') -> Config:
    return load_config(config)


def run_stats(config: str = 'config.yaml'):
    # 加载 config.yaml 文件
    cfg = _cfg(config)
    stats =  file_stats(cfg)
    md_content = render_stats(stats)
    md = Path("stats.md")
    md.write_text(md_content, encoding="utf-8")
    console.print(f"[green]✓[/] 盘点完成 -> {md}")
    console.print(f"总文件 {stats['total']} / 保留 {stats['kept_len']} / 排除 {stats['dropped_len']}")
    console.print(f"  排除比例 {stats['exclude_ratio']:.0%}"
                  f"（>60% 排过头，<20% 可能漏了生成代码）")
@app.command()
def stats(config:str = typer.Option("config.yaml", help="配置文件路径")):
    """ 阶段 0：盘点与配置 """
    run_stats(config)


def run_chunk(config: str = 'config.yaml'):
    cfg = _cfg(config)
    chunks = list(iter_chunks(cfg))
    write_jsonl(chunks,cfg)
    console.print(f"[green]✓[/] 切片完成")
    console.print(f"  共 {len(chunks)} 个 chunk")
    from collections import Counter
    by_kinds = Counter([c['kind'] for c in chunks ])
    for k, n in by_kinds.most_common(20):
        print(f"{k:10s}: {n}")
    return len(chunks)


@app.command()
def chunk(config: str = typer.Option("config.yaml")):
    """ 阶段 1：解析与切片 """
    run_chunk(config)


def run_index(config: str = 'config.yaml'):
    """ 建索引 -> index.db 读 chunks.jsonl -> embed -> upsert """
    cfg = _cfg(config)
    if not cfg.chunks_path.exists():
        console.print("[red]✗[/] 先跑 chunk 生成 chunks.jsonl")
        raise typer.Exit(1)
    chunks = read_jsonl(cfg.chunks_path)
    for c in chunks:
        c['embed_text'] = embedding_text(c,cfg)
    # TODO 开始创建表插入 sql
    store = SqliteStore(cfg)
    store.init_schema()

    embedder = get_embedder(cfg)
    # 首次运行探测 dimension 并回填到 config.yaml
    if cfg.embedding.dimension is None:
        dim = probe_dimension(embedder)
        cfg.save_dimension(dim)
        console.print(f"[yellow]ℹ[/] 探测到向量维度{dim} 已经回写 config.yaml")
        # 如果维度变了需要重新创建向量表
        store.conn.execute("DROP TABLE IF EXISTS chunks_vecs")
        store.conn.execute(
            f"CREATE VIRTUAL TABLE chunk_vecs USING vec0("
            f"chunk_id TEXT PRIMARY KEY, embedding FLOAT[{dim}])")
        store.conn.commit()

    texts = [ c['embed_text'] for c in chunks ]
    console.print(f"[cyan]ℹ[/] 嵌入 {len(texts)} 条文本（首次会下载模型，请等待）...")
    t0 = time.time()
    vectors = embedder.embed(texts)
    console.print(f" 嵌入完成 耗时{time.time() - t0:.1f}s ")

    # upsert TODO 记得分批 upsert 避免的单词事务太大
    store.upsert_chunks(chunks, vectors)
    console.print(f"upsert 完成 {len(chunks)}")

    # 打印 表结构
    table = Table(title = "索引表行数")
    table.add_column("表")
    table.add_column("行数", justify="right")
    for t in ("chunks","chunks_fts", "chunks_vecs","symbols", "calls", "file_hash"):
        table.add_row(t, str(store.count(t)))
    console.print(table)
    console.print(f"[green]✓[/] 索引完成 -> {cfg.store_path}")
    store.close()

@app.command()
def index(config: str = typer.Option("config.yaml")):
    """ 阶段 2：创建索引 """
    run_index()


def run_task(query:str, config:str = 'config.yaml'):
    """ 问答 检索 生成 """
    cfg = _cfg(config)
    from .graph import ask_with_graph
    ask_with_graph(query, cfg)


@app.command()
def ask(
        query: str = typer.Argument(..., help="问题"),
):
    """ 阶段 3：问答 """
    run_task(query)

if __name__ == "__main__":
    app()