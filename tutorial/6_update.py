#!/usr/bin/env python3
"""第 6 步：增量更新 —— 决定这套东西能不能长期用。

    python tutorial/6_update.py

第一次全量建索引很爽，但代码天天在变。全量重 embed 又慢又贵，
跑几次之后你就懒得更新了 —— 然后索引一天天过期，
三个月后这套系统给出的答案全是错的，最后没人用。

很多内部工具就是这么死的。

增量更新的逻辑只有三步：
  1. file_hash 表记住每个文件的 sha256
  2. 重新扫描比对，得到 added / changed / deleted
  3. 只处理这些文件

真正的坑在第 3 步的 deleted：
  **只测新增、不测删除是最常见的遗漏。**
  后果不是报错，而是索引里堆满「幽灵 chunk」——
  文件早删了，检索照样返回它的路径，用户点开发现文件不存在。

本脚本在索引的副本上演示（不动主库），会先演一遍错误做法，再演正确做法。
"""

import hashlib
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DB_PATH, OUT, REPO, banner, load_script  # noqa: E402

idx = load_script("2_index.py")

DEMO_DB = OUT / "demo_update.db"

# 删除一个文件时，这五张表必须一起清。少清一张就留垃圾。
TABLES_WITH_CHUNK_ID = ("chunks", "chunks_fts", "symbols", "chunk_vecs", "calls")


def sha256_of(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def init_file_hash(conn):
    """建 file_hash 表并填入当前索引里所有文件的真实 sha256。"""
    conn.execute("CREATE TABLE IF NOT EXISTS file_hash (path TEXT PRIMARY KEY, sha TEXT)")
    files = [r[0] for r in conn.execute("SELECT DISTINCT file FROM chunks")]
    for rel in files:
        path = REPO / rel
        if path.exists():
            conn.execute(
                "INSERT OR REPLACE INTO file_hash VALUES (?,?)", (rel, sha256_of(path))
            )
    conn.commit()


def diff_hashes(conn, current):
    """比对出 added / changed / deleted。"""
    old = dict(conn.execute("SELECT path, sha FROM file_hash").fetchall())
    added = [p for p in current if p not in old]
    deleted = [p for p in old if p not in current]
    changed = [p for p in current if p in old and old[p] != current[p]]
    return sorted(added), sorted(changed), sorted(deleted)


def delete_by_file(conn, rel):
    """把一个文件的索引清干净 —— 五张表一张都不能少。

    这是本步骤唯一「必须写对」的函数。
    """
    ids = [r[0] for r in conn.execute("SELECT id FROM chunks WHERE file = ?", (rel,))]
    for cid in ids:
        conn.execute("DELETE FROM chunks WHERE id = ?", (cid,))
        conn.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (cid,))
        conn.execute("DELETE FROM symbols WHERE chunk_id = ?", (cid,))
        conn.execute("DELETE FROM chunk_vecs WHERE chunk_id = ?", (cid,))
        conn.execute("DELETE FROM calls WHERE chunk_id = ?", (cid,))
    conn.execute("DELETE FROM file_hash WHERE path = ?", (rel,))
    conn.commit()
    return len(ids)


def orphan_count(conn):
    """统计孤儿记录：chunk 主表已经没了，但附属表里还留着。

    用来验证「清理是否彻底」。
    """
    live = {r[0] for r in conn.execute("SELECT id FROM chunks")}
    total = 0
    for table, col in (("chunks_fts", "chunk_id"), ("symbols", "chunk_id"),
                       ("chunk_vecs", "chunk_id"), ("calls", "chunk_id")):
        for (cid,) in conn.execute(f"SELECT DISTINCT {col} FROM {table}"):
            if cid not in live:
                total += 1
    return total


def main():
    if not DB_PATH.exists():
        sys.exit("先跑 python tutorial/2_index.py")

    # 在副本上演示，主库保持完整，后面的脚本还要用
    shutil.copyfile(DB_PATH, DEMO_DB)
    conn = sqlite3.connect(DEMO_DB)
    conn.row_factory = sqlite3.Row

    init_file_hash(conn)

    banner("第 6 步：增量更新")

    tracked = dict(conn.execute("SELECT path, sha FROM file_hash").fetchall())
    print(f"  已跟踪 {len(tracked)} 个文件\n")
    print("  file_hash 表长这样（路径 -> sha256 前 12 位）：")
    for path, sha in list(tracked.items())[:5]:
        print(f"      {path:28s} {sha[:12]}")
    print("      ...")

    banner("模拟一次代码变更")

    current = dict(tracked)
    current.pop("utils/crypto.py", None)      # 这个文件被删了
    current["main.py"] = "sha-of-modified"    # 这个文件被改了
    current["utils/cache.py"] = "sha-of-new"  # 这个是新增的

    added, changed, deleted = diff_hashes(conn, current)
    print(f"  added   : {added}")
    print(f"  changed : {changed}")
    print(f"  deleted : {deleted}")
    print()
    print("  全量重建要处理 10 个文件，增量只处理 3 个 —— 这就是意义所在。")

    banner("错误做法：只处理 added / changed，忘了 deleted")

    target = deleted[0]
    print(f"  假设 {target} 已经从磁盘上删掉了，但索引里没清理。\n")

    hits = idx.search_exact(conn, "verify_password", limit=3)
    print(f"  这时检索 verify_password，返回：")
    for h in hits:
        print(f"      {h['file']}:{h['start_line']}  {h['signature']}")
    print()
    print("  看，还能查到。用户拿着路径点过去，文件根本不存在。")
    print("  这就是幽灵 chunk —— 不报错、不崩溃，只是静静地让答案失效。")
    print("  而且它只增不减：每删一个文件，垃圾就多一批。")

    banner("正确做法：删除要清五张表")

    n = delete_by_file(conn, target)
    print(f"  从 {target} 清掉了 {n} 个 chunk\n")
    print("  清理的表：")
    for table in TABLES_WITH_CHUNK_ID:
        print(f"      - {table}")
    print()
    print("  少清任何一张都会留孤儿记录。清完后检查一下：")

    orphans = orphan_count(conn)
    print(f"      孤儿记录数 = {orphans}   {'✓ 干净' if orphans == 0 else '✗ 还有残留'}")

    print()
    print("  再检索一次 verify_password：")
    hits = idx.search_exact(conn, "verify_password", limit=3)
    if hits:
        for h in hits:
            print(f"      {h['file']}:{h['start_line']}")
    else:
        print("      (无命中)  ✓ 幽灵已清除")

    banner("验收清单")

    print("  1. 改 1 个文件后跑更新，日志里应该只有 1 个被处理")
    print("     —— 不是「看起来很快」，而是要打印出处理了哪几个文件")
    print()
    print("  2. 用 git 交叉验证：")
    print("     git log --name-only -20 --pretty=format: | sort -u")
    print("     拿这份文件列表和 diff 结果对一遍，数量级应该吻合")
    print()
    print("  3. 必须单独测删除路径")
    print("     —— 只测新增不测删除，是这个环节最常见的遗漏")
    print()
    print("  4. 挂 git hook（可选）：")
    print("     # .git/hooks/post-commit")
    print("     ./.venv/bin/python scripts/4_update.py >> .update.log 2>&1 &")
    print()
    print("     放后台跑，别让每次提交都卡住几秒。")

    print()
    print(f"  演示库：{DEMO_DB}（主库 {DB_PATH.name} 未被改动）")

    conn.close()


if __name__ == "__main__":
    main()
