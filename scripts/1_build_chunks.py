#!/usr/bin/env python3
"""阶段 1：解析切片 -> data/chunks.jsonl。

  python scripts/1_build_chunks.py
  python scripts/1_build_chunks.py --config test_config.yaml

跑完先看数据再往下走：随机抽 20 个 chunk，确认没有半个函数、没有单独的 import 段、
面包屑读得懂。这一步偷懒，后面所有环节都是白干。
"""

import sys

from code_rag.cli import run_chunk


def _config_arg() -> str:
    if "--config" in sys.argv:
        i = sys.argv.index("--config")
        return sys.argv[i + 1] if i + 1 < len(sys.argv) else "config.yaml"
    return "config.yaml"


def main() -> None:
    run_chunk(_config_arg())


if __name__ == "__main__":
    main()
