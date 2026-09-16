import os
from dotenv import load_dotenv
from .config import Config
load_dotenv()



RRF_K = 60

# 判断得分是否适合喂给大模型
def is_strong(result, min_sim:float = 0.02)-> bool:
    """
        判断这条结果是否适合投喂给大模型
        精准匹配 直接返回
        其他则根据得分返回
    """
    if "exact" in result['ranks']:
        return True
    return result["score"] >= min_sim

# 倒数排名融合
def rrf_fuse(rankings:dict[str, list[dict]], k: int = RRF_K):
    print(f"ranking exact", len(rankings["exact"]))
    print(f"ranking bm25", len(rankings["bm25"]))
    print(f"ranking vector", len(rankings["vector"]))
    scores:dict[str, float] = {}
    ranks: dict[str,dict] = {}
    for name, hits in rankings.items():
        # 等级默认从 1 开始累加 (1,{})(2,{})
        for rank , c in enumerate(hits, 1):
            # print(f"name, rank, h",name, rank, h)
            cid = c['id']
            scores[cid] = scores.get(cid, 0.0) + 1 / (rank + k)
            ranks.setdefault(cid, {})[name] = rank
    order = sorted(scores, key=lambda c: -scores[c])
    return [(cid, scores[cid], ranks[cid]) for cid in order ]

# ---------------------------------- 提示词

SYSTEM = """你是这个代码库的助手。只根据下面给出的代码片段回答问题。

规则：
1. 每个结论后面标注来源，格式 [文件:行号]。
2. 片段里没有的内容，直接回答"在这些片段里没有找到依据"，不要推测。
3. 如果片段之间互相矛盾，把矛盾点说出来，不要自己选一个。
4. 不要因为"看起来应该如此"就补充片段里没有的实现细节。"""

def build_prompt(query, results):
    """
        根据结果拼接 prompt
    """
    parts = [SYSTEM, "", "## 检索到的代码片段",""]
    for i, result in enumerate(results, 1):
        c = result["chunk"]
        parts.append(f"###片段 {i} {c['file']}:{c['start_line']}-{c['end_line']}")
        parts.append(f"路径:{c['breadcrumb']}")
        if c.get('docstring',''):
            parts.append(f"说明:{c['docstring']}")
        parts.append("")
        parts.append("```" + c.get('language',''))
        parts.append(c["code"])
        parts.append("```")
        parts.append("")
    parts.append(f"## 问题")
    parts.append(query)
    parts.append("")
    parts.append("回答时记得标注来源 [文件:行号]")
    return '\n'.join(parts)


def generate(prompt:str, cfg:Config):
    """ 调用模型生成答案 """
    from openai import OpenAI
    client = OpenAI(
        base_url = os.environ.get("ANTHROPIC_BASE_URL"),
        api_key = os.environ.get("ANTHROPIC_API_KEY"),
    )
    response = client.chat.completions.create(
        model = cfg.generation.model,
        messages = [{"role":"user","content":prompt}]
    )
    # print(response)
    return response.choices[0].message.content