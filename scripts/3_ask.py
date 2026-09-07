#!/usr/bin/env python3
"""阶段 3：问答 CLI。

  python scripts/3_ask.py "登录时密码是怎么校验的？"
  python scripts/3_ask.py "..." --debug          # 打印三路召回各自的命中
  python scripts/3_ask.py "..." --langgraph      # 走 LangGraph 版检索管线
  python scripts/3_ask.py "..." --config test_config.yaml
  python scripts/3_ask.py "..." --no-generate    # 只看召回，不调模型（排查检索时用）

输出两块：答案 + 来源清单（文件:行号，能直接点开）。
"""

import sys

from code_rag.cli import run_ask


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    query = args[0] if args else "这个项目里密码是怎么校验的"
    debug = "--debug" in sys.argv
    no_gen = "--no-generate" in sys.argv
    use_graph = "--langgraph" in sys.argv
    config = "config.yaml"
    if "--config" in sys.argv:
        i = sys.argv.index("--config")
        config = sys.argv[i + 1] if i + 1 < len(sys.argv) else "config.yaml"
    run_ask(query, config=config, debug=debug, no_generate=no_gen, use_graph=use_graph)


if __name__ == "__main__":
    main()
