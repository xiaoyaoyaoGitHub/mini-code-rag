from pathlib import Path
import yaml
from  dataclasses import dataclass, field

# 自动成成类的样板方法 不用手写__init__/__repr__/__eq__
@dataclass
class Project:
    root: str
    name: str

@dataclass
class Exclude:
    dirs:list[str]
    patterns: list[str]
    content_markers: list[str]
    scan_head_lines: int
    max_file_bytes: int
    exclude_tests: bool

@dataclass
class Chunking:
    units:list[str]
    max_lines: int
    breadcrumb_sep: str
    embed_breadcrumb: bool

@dataclass
class Embedding:
    provider: str
    model: str
    dimension: bool
    batch_size: int

@dataclass
class Store:
    backend: str
    path: str
    fts_tokenizer: str
    path_jsonl: str

@dataclass
class Retrieval:
    top_k: int
    rrf_k: int
    filters: dict

@dataclass
class Generation:
    provider: str | None
    model: str | None
    cite_sources: bool
    fallback_text: str

@dataclass
class Config:
    project:Project
    languages: dict[str, str]
    exclude: Exclude
    chunking:Chunking
    extract_calls: bool
    embedding: Embedding
    store: Store
    retrieval: Retrieval
    generation: Generation
    # repr=False — 打印时不显示  compare=False — 比较时忽略
    _source_path: Path = field(default = Path('config.yaml'), repr=False, compare=False)

    @property
    def root(self) -> Path:
        """ 获取解析项目的绝对路径 后续路径都从该处获取 """
        return Path(self.project.root).resolve()

    def ext_to_lang(self, ext: str) -> str | None:
        return self.languages.get(ext, None)

    @property
    def chunks_path(self) -> Path :
        return Path(self.root / self.store.path_jsonl).resolve()

    # sql 数据路径
    @property
    def store_path(self) -> Path:
        return Path(f"{self.project.root}/{self.store.path}" ).resolve()

    # 更新 config.yaml 中的 dimension
    def save_dimension(self,dim:int):
        """ 首次运行探测到向量维度后回写 yaml """
        self.embedding.dimension = dim
        raw = yaml.safe_load(self._source_path.read_text(encoding="utf-8"))
        raw.setdefault('embedding',{})["dimension"] = dim
        self._source_path.write_text(
            yaml.dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

def load_config(path: str | Path = 'config.yaml'):
    # 加载配置文件
    # 获取绝对
    path = Path(path).resolve()
    # path.read_text(encoding="utf-8") 输出为字符串
    # safe_load 解析 yaml返回 dict/list 不会执行危险代码  load会执行恶意代码
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    # print(f"raw:{raw}")
    cfg = Config(
        project = Project(**raw["project"]),
        languages = raw.get("languages",{}),
        exclude = Exclude(**raw.get('exclude',{})),
        chunking = Chunking(**raw.get('chunking', {})),
        extract_calls = raw.get('extract_calls', True),
        embedding = Embedding(**raw.get("embedding",{})),
        store=Store(**raw.get("store", {})),
        retrieval = Retrieval(**raw.get("retrieval",{})),
        generation = Generation(**raw.get("generation",{})),
        _source_path=path
    )

    # 判断解析项目的地址是否存在
    if not cfg.root.exists():
        raise FileNotFoundError(f"project.root 不存在：{cfg.root}")

    if not cfg.languages:
        raise ValueError("languages为空，至少配置一个扩展名 -> 语言映射")

    return cfg

