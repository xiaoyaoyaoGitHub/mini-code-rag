
import typer
from pathlib import Path
from rich.console import Console
from .config import load_config, Config
from .scan import file_stats,render_stats
from .parse import iter_chunks

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
    iter_chunks(cfg)


@app.command()
def chunk(config: str = typer.Option("config.yaml")):
    """ 阶段 1：解析与切片 """
    run_chunk(config)

if __name__ == "__main__":
    app()