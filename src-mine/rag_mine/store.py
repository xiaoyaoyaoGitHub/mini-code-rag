from .config import Config
import sqlite3
import json
import re

# 匹配中日韩汉字覆盖更全
CJK = r"㐀-鿿"
# 虚词字。中文 2-gram 会切出大量「这个」「的了」这类碎片，只贡献噪声。
# 只放纯虚词，别把「用」「做」「时」放进来 —— 会连「用户」「做到」一起误伤。
STOP_CHARS = set("的了是在和就都也很到说要去会着这那你我他吗呢吧啊个把被让给但而或太更最")
def expand_cjk(text:str):
    """ 是用 2-gram 属于 NLP（自然语言处理）里的 n-gram 概念 """
    # print(f"text",text)
    out = []
    for tok in re.findall(rf"[{CJK}]+|[A-Za-z_][A-Za-z0-9_]*|\d+", text or ''):
        if re.match(rf"[{CJK}]",tok):
            # print(f"CJK", tok)
            if len(tok) == 1 and tok not in STOP_CHARS:
                out.append(tok)
            else:
               for i in range(len(tok) - 1):
                   t = tok[i:i+2]
                   if t[0] not in STOP_CHARS and t[1] not in STOP_CHARS:
                       out.append(t)
        else:
            out.append(tok)
    return " ".join(out)

def norm_symbol(name:str) -> str:
    if not name:
        return ''
    s = re.sub(rf"(?<!^)(?=[A-Z])",'_', name) # camelCase => camel_case
    s = s.lower().replace("_","")
    return s

class SqliteStore:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.path = cfg.store_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 会自动创建.db文件 check_same_thread 允许多线程共享
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._load_vec()

    def _load_vec(self):
        """ 加载向量搜索扩展 sqlite_vec 让 sqlite变相向量数据库 """
        import sqlite_vec
        self.conn.enable_load_extension(True)
        sqlite_vec.load(self.conn)
        self.conn.enable_load_extension(False)

    def count(self,table:str):
        return self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def close(self):
        self.conn.close()

    def init_schema(self):
        """ 创建表 """
        # dimension 向量的长度 既向量有多少个浮点数 [0.012, -0.034, 0.056, ..., 0.078] / 1024
        dim = self.cfg.embedding.dimension
        if dim is None:
            dim = 1024 # 向量维度默认 1024 后续再重建
            self._dim_pending = True
        else:
            self._dim_pending = False

        self.conn.executescript(f"""
            -- 创建 chunks表
            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY,
                project TEXT,
                file TEXT,
                start_line INTEGER,
                end_line INTEGER,
                language TEXT,
                kind TEXT,
                name TEXT,
                breadcrumb TEXT,
                signature TEXT,
                docstring TEXT,
                code TEXT,
                imports TEXT,
                embed_text TEXT
            );
            
            -- 创建 fts5引擎的 chunks_fts表
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5 (
                chunk_id UNINDEXED, tokens
            );
            
            -- 创建 symbols表
            CREATE TABLE IF NOT EXISTS symbols(
                norm TEXT,
                chunk_id TEXT
            );
            
            -- 创建 vec0 引擎的 chunks_vecs表
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vecs USING vec0 (
                chunk_id TEXT PRIMARY KEY,
                embedding FLOAT[{dim}]
            );
            
            -- 创建 calls 表 调用关系
            CREATE TABLE IF NOT EXISTS calls(
                chunk_id TEXT,
                callee TEXT
            );
            
            -- 创建 file_hash
            CREATE TABLE IF NOT EXISTS file_hash (
                path TEXT PRIMARY KEY,
                sha TEXT
            );
            
            -- 创建查询索引
            CREATE INDEX IF NOT EXISTS index_chunks_file ON chunks(file);
            CREATE INDEX IF NOT EXISTS index_symbol_norm ON symbols(norm);
            CREATE INDEX IF NOT EXISTS index_calls_callee ON calls(callee);
            
        """)
        self.conn.commit()

    # 生成 token 针对 chunk_fts表
    def _index_text(self,chunk:dict):
        """ 拼接出 FTS5 的全文 权重靠重复实现：名字与面包屑多谢几遍 """
        parts = [
            chunk["name"],
            chunk["breadcrumb"].replace(self.cfg.chunking.breadcrumb_sep, ' '),
            chunk["docstring"],
            chunk["signature"],
            chunk["code"]
        ]
        # 需要对中文进行分词 不然 FTS5搜索有问题
        return expand_cjk(" ".join(p for p in parts if p))

    # 生成 symbol name
    def _symbol_name(self, chunk:dict) -> list[str]:
        name = {chunk["name"]} # set 自动去重
        crumb = chunk["breadcrumb"].split(self.cfg.chunking.breadcrumb_sep)[1:]
        if len(crumb) == 0:
            return sorted(name)
        name.add(crumb[-1])
        # print(f"crumb",crumb)
        if len(crumb) > 2:
            name.add(".".join(crumb[1:]))
        return [n for n in name if n ]

    # 根据 id 删除所有表
    def _delete_chunk(self, cid):
        """ 删除所有表中对应的 chunk_id 的信息 """
        self.conn.execute("DELETE FROM chunks WHERE id = ?", (cid,))
        self.conn.execute("DELETE FROM chunks_fts WHERE chunk_id = ?",(cid, ))
        self.conn.execute("DELETE FROM symbols WHERE chunk_id = ?",(cid, ))
        self.conn.execute("DELETE FROM chunks_vecs WHERE chunk_id = ?", (cid,))
        self.conn.execute("DELETE FROM calls WHERE chunk_id = ?", (cid,))

    # 删除
    def delete_by_file(self,file):
        raw = self.conn.execute("SELECT id FROM chunks WHERE file = ?",(file,)).fetchall()
        # print('delete_by_file',dict(raw[0])["id"])
        for r in raw:
            cid = dict(r)["id"]
            self._delete_chunk(cid)
        self.conn.execute(f"DELETE FROM file_hash WHERE path = ?",(file,))
        self.conn.commit()

    # 写入
    def upsert_chunks(self, chunks:list[dict], vectors:list[list[float]]):
        """ 把 chunk 写入到 5 张表中 """
        for chunk, vec in zip(chunks, vectors):

            # 先把 已有的 id全部删除掉
            self._delete_chunk(chunk["id"])

            self.conn.execute(
                """ INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) """,
                (
                    chunk["id"],
                    chunk["project"],
                    chunk["file"],
                    chunk["start_line"],
                    chunk["end_line"],
                    chunk["language"],
                    chunk["kind"],
                    chunk["name"],
                    chunk["breadcrumb"],
                    chunk["signature"],
                    chunk["docstring"],
                    chunk["code"],
                    json.dumps(chunk["imports"], ensure_ascii=False),
                    chunk.get('embed_text','')
                )
            )
            # fts 表
            self.conn.execute(
                """ INSERT INTO chunks_fts(chunk_id, tokens) VALUES (?,?)""",
                ( chunk["id"], self._index_text(chunk) )
            )

            # symbol
            for name in self._symbol_name(chunk):
                norm = norm_symbol(name)
                if norm:
                    self.conn.execute("INSERT INTO symbols(norm, chunk_id) VALUES (?,?)",(norm, chunk["id"]))

            # 向量存储
            import sqlite_vec
            blob =  sqlite_vec.serialize_float32(vec)
            self.conn.execute(
                "INSERT INTO chunks_vecs(chunk_id, embedding) VALUES (?,?)",
                ( chunk["id"], blob )
            )

            for callee in chunk['calls']:
                self.conn.execute("INSERT INTO calls(chunk_id, callee) VALUES (?,?)",(chunk["id"], callee))

            # file_hash 表
            import hashlib
            rel_path = self.cfg.root / chunk["file"]
            if rel_path.exists():
                self.conn.execute("INSERT OR REPLACE INTO file_hash(path, sha) VALUES (?,?)",(chunk['file'], hashlib.sha256(rel_path.read_bytes()).hexdigest()))

            self.conn.commit()

    def search_exact(self, query:str, limit:int = 10) -> list[dict]:
        """ 精准查询 """
        norm = norm_symbol(query)
        if not norm:
            return []
        if len(norm) > 4:
            # 字符串长的做包含匹配
            rows = self.conn.execute("""
                SELECT c.*, 1.0 AS score 
                FROM chunks c JOIN symbols s ON s.chunk_id = c.id
                WHERE s.norm = ? OR s.norm LIKE '%' || ? || '%'
                LIMIT ?
            """,(norm, norm, limit)).fetchall()
        else:
            # 字符串短的做精准匹配
            rows = self.conn.execute("""
                SELECT c.*, 1.0 AS score 
                FROM chunks c  JOIN symbols s ON s.chunk_id = c.id
                WHERE s.norm = ? LIMIT ?                    
            """,(norm, limit))
        return [dict(r) for r in rows]

    # 语义查询
    def search_bm25(self,query: str, limit:int = 10)-> list[dict]:
        """ 关键字召回  """
        match = " OR ".join(f'"{t}"' for t in expand_cjk(query).split() if t )
        if not match:
            return []
        # bm25 返回负数，越小越相关
        rows = self.conn.execute("""
            SELECT c.*, bm25(chunks_fts) AS raw 
            FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.chunk_id
            WHERE chunks_fts MATCH ? ORDER BY raw LIMIT ?
        """,(match, limit)).fetchall()

        return [{ k:r[k] for k in r.keys() } for r in rows ]

    def search_vector(self, vec, limit):
        """ 向量检索 """
        import sqlite_vec
        blob = sqlite_vec.serialize_float32(vec)
        rows = self.conn.execute("""
            SELECT v.chunk_id, v.distance, c.* 
            FROM chunks_vecs v JOIN chunks c ON c.id = v.chunk_id
            WHERE v.embedding MATCH ? AND k = ?
            ORDER BY v.distance
        """,(blob, limit)).fetchall()

        return [ dict(r) for r in rows ]

    # 查询 hash表
    def get_file_hashes(self):
        """ 查询 hashes表数据 """
        return dict(self.conn.execute("SELECT * FROM file_hash").fetchall())