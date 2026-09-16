import os
import asyncio

from dotenv import load_dotenv
load_dotenv()

from .config import Config
from typing import Protocol

class Embedder(Protocol):
    """嵌入协议。所有实现只要满足这个接口。"""
    def embed(self,text:list[str]) -> list[list[float]]:...
    @property
    def dimension(self) -> int: ...

# 本地模型
class LocalEmbedder:
    def __init__(self):
        pass

# API模型调用
class APIEmbedder:
    """ 走HTTP调用模型 """
    def __init__(self,model:str, batch_size: int = 64, base_url: str |None = None):
        self._model = model
        self._batch_size = batch_size
        self._base_url = base_url
        self._dim = None
        self._sem = asyncio.Semaphore(batch_size)  # 限流

    def _client(self):
        from openai import AsyncOpenAI
        params = {
            "api_key": os.environ.get("ANTHROPIC_API_KEY"),
            "base_url": os.environ.get("ANTHROPIC_BASE_URL"),
        }
        return AsyncOpenAI(
            **params
        )

    async def _embed_batch(self, client, batch):
        async with self._sem:
            rep = await client.embeddings.create(
                model = self._model,
                input = batch
            )
            return rep.data

    async def embed_async(self, text: list[str]):
        client = self._client()
        out:list[list[float]] = []
        # 本模型不支持 input 传 list 类型 所以需要并发请求
        result = await asyncio.gather(*[self._embed_batch(client, t) for t in text ])
        # print("result",len(result),result[0])
        out = [vec.embedding for r in result for vec in r ]
        if self._dim is None:
            self._dim = len(out[0])
        return out

    def embed(self,text:list[str]):
        return asyncio.run(self.embed_async(text))

    # 获取维度
    @property
    def dimension(self) -> int:
        if self._dim is None:
           return  len(self.embed(["dimension probe"])[0])
        return self._dim

# 获取嵌入类
def get_embedder(cfg: Config):
    embedding = cfg.embedding
    provider = embedding.provider
    if provider == 'local':
        pass
        return
    if provider == 'API':
        return APIEmbedder(embedding.model, embedding.batch_size )
    raise ValueError(f"未知 embedding provider: {provider}")

# 获取 dimension
def probe_dimension(embedder: Embedder):
    """ 获取 dimention """
    return embedder.dimension



# 整合需要 embed的内容
def embedding_text(chunk, cfg:Config) -> str:
    parts = []
    if cfg.chunking.embed_breadcrumb:
        parts.append(f"# {chunk['breadcrumb']}")
    if chunk["signature"] and chunk["signature"] not in chunk["code"]:
        parts.append(chunk["signature"])
    if chunk["docstring"]:
        parts.append(chunk["docstring"])
    parts.append(chunk["code"])
    return "\n".join(p for p in parts if p)



