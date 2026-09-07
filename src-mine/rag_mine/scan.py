
from pathlib import Path
from .config import Config
from dataclasses import dataclass
from typing import Iterator
from collections import Counter

@dataclass
class FileEntry:
    path: Path # 绝对路径
    rel: str # 相对路径
    language: str # 语言
    ext: str # 扩展名（没有.）
    lines: int # 行数
    bytes_size: int # 文件大小

# 应该排除的
def should_exclude(path, rel, cfg:Config) -> str|None:
    """ 根据对应的规则 排除文件 """
    exclude = cfg.exclude
    parts = set(rel.split("/"))

    # 根据目录名过滤
    hit = parts & set(exclude.dirs)
    if hit:
        return f"目录名:{sorted(hit)}"

    # 文件名匹配
    for pat in exclude.patterns:
        if path.match(pat):
            return f"文件名模式:{pat}"

    # 文件内容标记
    try:
        head = "\n".join(path.read_text("utf-8").splitlines()[:exclude.scan_head_lines])
    except OSError:
        return "读不了"

    for marker in exclude.content_markers:
        if marker in head:
            return f"内容标记:{marker!r}"

    # 体积兜底
    if path.stat().st_size > exclude.max_file_bytes:
        return f"体积超限:{path.stat().st_size} bytes"

    return None

# 可迭代的文件
def iter_files(cfg: Config) -> Iterator[FileEntry]:
    # print(f"file_stats:{cfg}")
    # 找出需要索引的文件
    root = cfg.root
    # 去重
    exts = set(cfg.languages.keys())
    for path in sorted(root.rglob("*")):
        # 非文件跳过
        if not path.is_file():
            continue
        # 非对应语言 跳过
        ext = path.suffix.lstrip(".")
        if ext not in exts:
            continue
        # 命中配置文件 exclude 跳过
        rel = path.relative_to(root).as_posix()
        exclude = should_exclude(path, rel, cfg)
        if exclude:
            # print(f"exclude reason:{exclude}")
            continue

        try:
            lines = len(path.read_text(errors="ignore",encoding="utf-8").splitlines())
        except OSError:
            continue
        # 所有元信息打包成对象 后续不用重新计算
        yield FileEntry(
            path=path,
            rel=rel,
            ext=ext,
            language=cfg.ext_to_lang(ext),
            lines = lines,
            bytes_size = path.stat().st_size
        )

# 收集需要排除的文件
def list_dropped(cfg:Config) -> list[tuple[str, str]]:
    root = cfg.root
    exts = set(cfg.languages.keys())
    out = []
    if not root.exists():
        raise f"{root} 不存在"
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lstrip('.') not in exts:
            continue
        rel = path.relative_to(root).as_posix()
        reason = should_exclude(path, rel ,cfg)
        if reason:
            out.append((rel,reason))
    return out

# 扫描项目
def file_stats(cfg:Config) -> dict:
    kept = list(iter_files(cfg))
    dropped = list_dropped(cfg)
    # print(f"drap",dropped)
    total = len(kept) + len(dropped)

    # 1. 按扩展名分布
    # Counter({'js': 160, 'ts': 136, 'jsx': 4}),dict_keys(['js', 'ts', 'jsx'])
    by_ext = Counter(k.ext for k in kept)
    # print(f"by_ext:{by_ext}")

    # 2. 排除比例
    exclude_ratio = len(dropped) / total if total else 0

    # 3. 计算总行数
    total_lines = sum(k.lines for k in kept)

    # 4. 按照行数排序
    all_lines = sorted(k.lines for k in kept)
    # print(f"all_lines:{all_lines}")

    # 获取分位值
    def percentile(sorted_list,p):
        if not sorted_list:
            return 0
        return sorted_list[min(int(len(sorted_list) * p), len(sorted_list) - 1)]

    # 5. 取最长的10个文件
    longest = sorted(kept, key = lambda f:f.lines, reverse=True )[:10]

    # 6. 最大的 10个文件目录
    by_dir = Counter(k.rel.rsplit('/',1)[0] if "/" in k.rel else '.' for k in kept)
    # print(f"by_dir:{by_dir}")
    top_dirs = by_dir.most_common(10)

    # 7. 查找文件名重复的前 20 相同的文件名需要限定目录检索
    name_count = Counter(k.path.name for k in kept)
    # c > 1 代表是有重复的
    dup_names = [(n,c) for n, c in name_count.most_common(20) if c > 1]
    # print(f"dup_names:{dup_names}")

    return {
        "total":total,
        "kept_len": len(kept),
        "dropped_len": len(dropped),
        "dropped_detail":dropped,
        "exclude_ratio":exclude_ratio,
        "by_ext":by_ext,
        "total_lines":total_lines,
        "longest":longest,
        "top_dirs":top_dirs,
        "dup_names":dup_names,
        "line_p50":percentile(all_lines, 0.5),
        "line_p90":percentile(all_lines, 0.9),
        "line_max": max(all_lines) if all_lines else 0
    }

# 生成的扫描结果落盘
def render_stats(stats:dict):
    """把统计结果落盘 写入 stats.md"""
    lines = ["# 项目盘点",""]
    lines.append(f"- 总文件数：**{stats['total']}**")
    lines.append(f"- 保留：**{stats['kept_len']}**")
    lines.append(f"- 排除比例：**{stats['exclude_ratio']}**")
    lines.append(f"- 排除比例：**{stats['exclude_ratio']:.0%}**")
    lines.append(f"- 总行数：**{stats['total_lines']}**")
    lines.append("")
    lines.append("## 按照扩展名分布")
    lines.append("")
    lines.append("| 扩展名 | 文件数 |")
    lines.append("|---|---|")
    for ext, n in stats['by_ext'].most_common(20):
        lines.append(f"| .{ext} | {n} |")
    lines.append("")

    lines.append("## 行数分位")
    lines.append("")
    lines.append(f"- p50: **{stats['line_p50']}**行")
    lines.append(f"- p90: **{stats['line_p90']}**行")
    lines.append(f"- max: **{stats['line_max']}**行")
    lines.append("")

    lines.append("## 最长的 10 个文件（人工逐个看一眼）")
    lines.append("")
    for k in stats["longest"]:
        lines.append(f"- `{k.rel}` - {k.lines}行")
    lines.append("")

    if stats['dup_names']:
        lines.append("## 重复文件名 top20 (同名符号干扰源 需要限定目录检索)")
        lines.append("")
        lines.append("| 文件名 | 出现次数 |")
        lines.append("|---|---|")
        for n, c in stats['dup_names']:
            lines.append(f"|{n}|{c}|")
        lines.append("")

    if stats["dropped_detail"]:
        lines.append("## 被排除的文件")
        lines.append("")
        for rel, reason in stats["dropped_detail"]:
            lines.append(f"- {rel} - {reason}")
        lines.append("")

    return "\n".join(lines)



