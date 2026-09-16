
from .config import Config
from .store import SqliteStore
from .embed import get_embedder,APIEmbedder
from .retrieve import rrf_fuse,is_strong,build_prompt,generate
from typing import TypedDict
from langgraph.graph import StateGraph, START, END

# 节点共享的状态
class RetrievalState(TypedDict):
    # 每个节点都需要读的字段
    query: str
    cfg: Config
    store: SqliteStore
    embedder: APIEmbedder
    # 三路各自对应的字段
    exact_hits: list[dict]
    bm25_hits: list[dict]
    vector_hits: list[dict]
    # RRF 融合后字段
    fused: list[tuple]
    # 过滤后
    results: list[dict]
    # 生成
    prompt: str
    answer: str

def _recall_depth(cfg:Config) -> int:
    """ 召回深度 """
    return cfg.retrieval.top_k * 3



def node_exact(state: RetrievalState):
    """ 精准召回 """
    cfg = state["cfg"]
    store = state['store']
    depth = _recall_depth(cfg)
    hits = store.search_exact(state["query"], limit=depth)
    # print(f"exact_hits",hits[0])
    return {"exact_hits": hits}

def node_bm25(state: RetrievalState):
    """ 关键字召回：FTS5的 bm25排序 """
    cfg = state["cfg"]
    store = state["store"]
    depth = _recall_depth(cfg)
    hits = store.search_bm25(state["query"], limit=depth)
    # print(f"bm25_hits",hits[0])
    return {"bm25_hits":hits}

def node_vector(state: RetrievalState):
    """ 向量召回 """
    cfg = state['cfg']
    store = state['store']
    embedder = state['embedder']
    depth = _recall_depth(cfg)
    query_vec = embedder.embed([state['query']])[0]
    # print(f"node_vector",query_vec)
    hits = store.search_vector(query_vec, limit=depth)
    # print(f"node_vector",hits[0])
    return {"vector_hits":hits}

def node_fuse(state: RetrievalState):
    """ RRF融合 """
    ranking = {
        "exact": state["exact_hits"],
        "bm25": state["bm25_hits"],
        "vector": state["vector_hits"]
    }
    fuse_result = rrf_fuse(ranking, state["cfg"].retrieval.rrf_k)
    # print(f"fuse_result",fuse_result)
    # 整合 chunk
    by_id:dict[str, dict] = {}
    for hits in ranking.values():
        for h in hits:
            by_id[h["id"]] = h

    results = []
    for chunk_id, score, ranks in fuse_result[:state['cfg'].retrieval.top_k]:
        chunk = by_id[chunk_id]
        results.append({"chunk":chunk, "score":score,"ranks":ranks})
    return {"fused":fuse_result, "results": results}

def node_filter(state: RetrievalState):
    """ 过滤弱结果 """
    results = [r for r in state["results"] if is_strong(r)]
    return  {"results": results}

def node_prompt(state: RetrievalState):
    """ 拼接提示词 """
    # print("state prompt", state)
    if not state["results"]:
        return {"prompt":""}
    return {"prompt":build_prompt(state["query"],state["results"])}

def node_generate(state: RetrievalState):
    """ 生成答案 """
    result = generate(state["prompt"], state["cfg"])
    # print(f"result",result)
    return {"answer":result}

def build_graph():
    """
        创建图结构
    ┌─ exact ──┐
START ─┼─ bm25 ───┼─→ fuse ─→ filter ─→ prompt ─→ generate ─→ END
    └─ vector ─┘
    """
    g = StateGraph(RetrievalState)
    g.add_node("exact", node_exact)
    g.add_node("bm25", node_bm25)
    g.add_node("vector", node_vector)
    g.add_node("fuse", node_fuse)
    g.add_node("filter",node_filter)
    g.add_node('prompt', node_prompt)
    g.add_node("generate", node_generate)

    # 创建链接关系
    g.add_edge(START, "exact")
    g.add_edge(START, "bm25")
    g.add_edge(START, "vector")

    g.add_edge("exact","fuse")
    g.add_edge("bm25","fuse")
    g.add_edge("vector","fuse")

    g.add_edge("fuse","filter")
    g.add_edge("filter","prompt")
    g.add_edge("prompt","generate")
    g.add_edge("generate", END)

    return g.compile()


# 入口查询
def ask_with_graph(query: str, cfg: Config):
    # 获取到数据库
    store = SqliteStore(cfg)
    store.init_schema()
    # 获取嵌入模型
    embedder = get_embedder(cfg)
    # 创建 graph
    graph =  build_graph()

    init_state: RetrievalState = {
        "query": query,
        "cfg": cfg,
        "store": store,
        "embedder": embedder,
        "exact_hits":[],
        "bm25_hits":[],
        "vector_hits":[],
        "fused":[],
        "results":[],
        "prompt":'',
        "answer":''
    }

    final =  graph.invoke(init_state)

    store.close()
    return {
        "answer":final["answer"],
        "results":final["results"],
        "prompt":final["prompt"]
    }