#!/usr/bin/env python3
"""阶段 4：增量更新 ★ 决定这套东西能不能长期用。

  python scripts/4_update.py
  python scripts/4_update.py --config test_config.yaml

只在新增/变更的文件上重新切片 + embed，并清理已删除文件的索引。
可选挂 git hook：

  # .git/hooks/post-commit
  #!/bin/sh
  ./.venv/bin/python scripts/4_update.py >> .update.log 2>&1 &

验收：
  1. 改 1 个文件后跑更新，日志里应该只有 1 个被处理
  2. 取 `git log --name-only -20` 的文件列表交叉验证
  3. 必须测删除路径 —— 只测新增不测删除是最常见的遗漏
"""

import sys

from code_rag.cli import run_update


def _config_arg() -> str:
    if "--config" in sys.argv:
        i = sys.argv.index("--config")
        return sys.argv[i + 1] if i + 1 < len(sys.argv) else "config.yaml"
    return "config.yaml"


def main() -> None:
    run_update(_config_arg())


if __name__ == "__main__":
    main()
