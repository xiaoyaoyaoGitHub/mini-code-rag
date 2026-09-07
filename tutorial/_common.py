"""几个脚本共用的小工具。只读这个目录下的玩具库。"""

import math
import re
import zlib
from pathlib import Path

TUTORIAL = Path(__file__).resolve().parent
REPO = TUTORIAL / "toy_repo"
OUT = TUTORIAL / "_out"
# 别写 mkdir(exist_ok=True)：某些环境的安全守卫会把「已存在」当错误处理。
# 先判断再建，重跑就不会触发。
if not OUT.exists():
    OUT.mkdir(parents=True)

DB_PATH = OUT / "index.db"
CHUNKS_PATH = OUT / "chunks.jsonl"

VEC_DIM = 512


def load_script(filename):
    """按文件名加载同目录的脚本，返回模块对象。

    文件名以数字开头（2_index.py）没法直接 import —— Python 标识符
    不能以数字开头。所以走 importlib 动态加载。

    被加载的脚本都有 __main__ 保护，加载时只定义函数，不会执行主流程。
    """
    import importlib.util

    path = TUTORIAL / filename
    modname = "step_" + filename.replace(".", "_")
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def banner(text):
    """打印一个分隔标题，方便在终端里看清跑到哪一步了。"""
    print()
    print("=" * 68)
    print(text)
    print("=" * 68)


def hash_vector(text, dim=VEC_DIM):
    """造一个「假向量」：字符 3-gram + hashing trick。

    这不是真的 embedding。它只认识字符层面的重叠，不认识语义 ——
    「校验密码」和 verify_password 在它眼里毫无关系，向量相似度接近 0。

    留着它是有意的：
      1. 让你零依赖就能看清「向量检索」的完整流程
      2. 让你亲眼看到假向量失效的边界，从而理解
         为什么真实工程必须上 BGE-M3 / Qwen3-Embedding 这类模型
    """
    vec = [0.0] * dim
    low = text.lower()
    for i in range(len(low) - 2):
        gram = low[i : i + 3]
        vec[zlib.crc32(gram.encode()) % dim] += 1.0

    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def cosine(a, b):
    """余弦相似度。两个向量都已归一化，所以点积就是余弦。"""
    return sum(x * y for x, y in zip(a, b))


def norm_symbol(name):
    """符号名归一化，让下面几种写法都能对上同一个符号：

        UserService.login / user_service_login / userservicelogin / USER_SERVICE_LOGIN

    精确命中那一路全靠这个函数。大小写和下划线是最常见的漏召回原因。
    """
    if not name:
        return ""
    s = re.sub(r"(?<!^)(?=[A-Z])", "_", name)
    s = s.lower().replace("_", "")
    return s


def fmt_hit(hit, idx=0):
    """把一条命中格式化成一行。格式刻意和正式工程的一致。"""
    c = hit["chunk"]
    where = f"{c['file']}:{c['start_line']}-{c['end_line']}"
    return f"  {idx:2d}. [{hit['score']:.4f}] {c['kind']:8s} {c['name'][:28]:28s} {where}"


def print_hits(title, hits):
    """打印一组命中结果。"""
    print(f"\n--- {title} ---")
    if not hits:
        print("  (无命中)")
        return
    for i, h in enumerate(hits, 1):
        print(fmt_hit(h, i))
