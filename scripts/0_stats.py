#!/usr/bin/env python3
"""阶段 0：跑盘点，把结果写进 stats.md。

  python scripts/0_stats.py
  python scripts/0_stats.py --config test_config.yaml

跑完先看数字，再回头补 config.yaml 的排除规则，然后再跑一次。
别指望一次调准。
"""

import sys

from code_rag.cli import run_stats


def _config_arg() -> str:
    if "--config" in sys.argv:
        i = sys.argv.index("--config")
        return sys.argv[i + 1] if i + 1 < len(sys.argv) else "config.yaml"
    return "config.yaml"


def main() -> None:
    run_stats(_config_arg())


if __name__ == "__main__":
    main()
