#!/usr/bin/env python3
"""阶段 2：建索引 -> data/index.db。

  python scripts/2_build_index.py
  python scripts/2_build_index.py --config test_config.yaml

四张主表 + calls 表。embedding 的 dimension 首次运行自动探测并回写 config.yaml。
"""

import sys

from code_rag.cli import run_index


def _config_arg() -> str:
    if "--config" in sys.argv:
        i = sys.argv.index("--config")
        return sys.argv[i + 1] if i + 1 < len(sys.argv) else "config.yaml"
    return "config.yaml"


def main() -> None:
    run_index(_config_arg())


if __name__ == "__main__":
    main()
