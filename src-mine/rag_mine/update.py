
from .config import Config
from .store import SqliteStore
from .scan import iter_files
from dataclasses import dataclass, field
from .parse import chunk_file
from .embed import embedding_text,get_embedder

@dataclass
class UpdateReport:
    added: list[str] = field(default_factory= list)
    changed:list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)

    def total(self) -> int:
        """ 统计总数据 """
        return len(self.added)  + len(self.changed) + len(self.deleted)


def diff_hashes(store: SqliteStore, current)-> UpdateReport:
    """ 对比文件的增删改 """
    old = store.get_file_hashes()
    # print('old',old)
    # print('current',current)
    report = UpdateReport()
    report.added = sorted(p for p in current if p not in old)
    report.changed = sorted(p for p in current if p in old and old[p] != current[p])
    report.deleted = sorted(p for p in old if p not in current)
    print('report',report)
    return report

def scan_hashes(cfg):
    """ 扫描当前文件 并生成 hash """
    import hashlib
    out = {}
    for f in iter_files(cfg):
        out[f.rel] = hashlib.sha256(f.path.read_bytes()).hexdigest()
    return out


def update_apply(store: SqliteStore, cfg:Config, report: UpdateReport):
    """ 执行更新 """
    # 删除操作
    for rel in report.deleted:
        # rel 对应文件夹在路径
        store.delete_by_file(rel)

    to_process = report.added + report.changed
    if not to_process:
        return

    for rel in to_process:
        # 先删除 再重建
        store.delete_by_file(rel)

        path = cfg.root / rel
        ext = path.suffix.lstrip('.')
        language = cfg.ext_to_lang(ext)
        if not language:
            continue

        chunks = chunk_file(path, rel, language, cfg.project.name, cfg)
        if not chunks:
            continue

        texts = [embedding_text(c,cfg) for c in chunks]
        for c , t in zip(chunks, texts):
            c['embed_text'] = t
        embeder = get_embedder(cfg)
        vectors = embeder.embed(texts)
        store.upsert_chunks(chunks, vectors)






def update_index(cfg:Config):
    """ 增量更新入口 """
    store = SqliteStore(cfg)
    store.init_schema()

    # 扫描当前文件
    current =  scan_hashes(cfg)
    report = diff_hashes(store, current)
    update_apply(store, cfg, report)
    return report