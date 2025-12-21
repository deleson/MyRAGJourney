# core/retrievers.py

from pgvector.django import CosineDistance
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from .models import DocumentChunk
from .utils import get_embedding, get_reranker, get_llm


class BaseRetriever:
    """
    检索器基类：定义标准接口
    增加 user 参数用于权限控制
    """

    def query(self, text: str, kb_id: int = None, doc_id: int = None, top_k: int = 3):
        raise NotImplementedError("必须在子类中实现 query 方法")

    def _get_base_queryset(self, kb_id=None, doc_id=None):
        """
        通用过滤逻辑：
        2. 必须是已发布的文档 (status='active')
        3. 可选：特定 kb_id 或 doc_id
        """
        # 基础查询集：所有切片
        qs = DocumentChunk.objects.all()


        # 2. 状态过滤：只查审核通过的
        qs = qs.filter(document__status='active')

        # 3. 范围过滤
        if doc_id:
            qs = qs.filter(document_id=doc_id)
        elif kb_id:
            qs = qs.filter(document__kb__id=kb_id)

        return qs


class VectorRetriever(BaseRetriever):
    """
    标准向量检索器 (Phase 1-3 的逻辑)
    """

    def query(self, text: str, kb_id: int = None, doc_id: int = None, top_k: int = 3):
        query_vector = get_embedding(text)
        qs = self._get_base_queryset( kb_id, doc_id)

        if not qs.exists(): return []

        return qs.annotate(
            distance=CosineDistance('embedding', query_vector)
        ).order_by('distance')[:top_k]


class RerankRetriever(BaseRetriever):
    """
    重排序检索器：先向量检索召回 Top N，再用 Cross-Encoder 精排取 Top K
    """

    def query(self, text: str, kb_id: int = None, doc_id: int = None, top_k: int = 3):
        query_vector = get_embedding(text)
        qs = self._get_base_queryset( kb_id, doc_id)

        if not qs.exists(): return []

        # 1. 海选
        candidates = qs.annotate(
            distance=CosineDistance('embedding', query_vector)
        ).order_by('distance')[:15]

        if not candidates: return []

        # 2. 精排
        reranker = get_reranker()
        pairs = [[text, c.content] for c in candidates]
        scores = reranker.predict(pairs)

        for i, c in enumerate(candidates):
            c.score = float(scores[i])

        candidates = list(candidates)
        candidates.sort(key=lambda x: x.score, reverse=True)
        return candidates[:top_k]



class HybridRetriever(BaseRetriever):
    """
    混合检索器：向量检索 + 全文检索 -> RRF 融合 -> Rerank 重排序
    """

    def query(self, text: str, kb_id: int = None, doc_id: int = None, top_k: int = 3, needs_rerank: bool = True):
        # 1. 基础过滤
        qs = self._get_base_queryset(kb_id, doc_id)
        if not qs.exists(): return []

        # --- A. 向量召回 (Semantic Search) ---
        # 扩大召回范围到 Top 20，给 RRF 更多素材
        query_vector = get_embedding(text)
        vector_candidates = qs.annotate(
            distance=CosineDistance('embedding', query_vector)
        ).order_by('distance')[:20]

        # --- B. 关键词召回 (Full-Text Search) ---
        # 同样扩大到 Top 20
        sv = SearchVector('content')
        sq = SearchQuery(text)
        keyword_candidates = qs.annotate(
            search=sv,
            rank=SearchRank(sv, sq)
        ).filter(
            search=sq
        ).order_by('-rank')[:20]

        # --- C. RRF 融合算法 (核心优化) ---
        rrf_k = 60  # 工业界常用的平滑常数
        fused_scores = {}  # {doc_id: rrf_score}
        doc_map = {}  # {doc_id: chunk_object} 用于最后取对象

        # 1. 处理向量结果 (rank 从 0 开始)
        for rank, doc in enumerate(vector_candidates):
            doc_map[doc.id] = doc
            if doc.id not in fused_scores: fused_scores[doc.id] = 0
            # 排名越靠前(rank小)，分数越高
            fused_scores[doc.id] += 1 / (rrf_k + rank + 1)

        # 2. 处理关键词结果
        for rank, doc in enumerate(keyword_candidates):
            doc_map[doc.id] = doc
            if doc.id not in fused_scores: fused_scores[doc.id] = 0
            fused_scores[doc.id] += 1 / (rrf_k + rank + 1)

        # 3. 按 RRF 分数排序 (从高到低)
        sorted_ids = sorted(fused_scores, key=fused_scores.get, reverse=True)

        # 取 RRF 排序后的 Top 20 进入重排序阶段
        # 这里的 20 是为了保证送给 Reranker 的都是精品
        final_candidates = [doc_map[uid] for uid in sorted_ids[:20]]

        if not final_candidates:
            return []

        # 优化开关：如果是 MultiQuery 调用，直接返回 RRF 结果，不再重排以节省时间
        if not needs_rerank:
            # MultiQuery 会自己做汇总重排，这里返回 Top 10 给它即可
            return final_candidates[:10]

        print(
            f"🔍 [Hybrid+RRF] 向量召回 {len(vector_candidates)} + 关键词召回 {len(keyword_candidates)} -> 融合后送入重排 {len(final_candidates)}")

        # --- D. 重排序 (Rerank) ---
        # 使用 Cross-Encoder 对 RRF 选出的高质量候选者进行最终打分
        reranker = get_reranker()
        pairs = [[text, c.content] for c in final_candidates]
        scores = reranker.predict(pairs)

        for i, c in enumerate(final_candidates):
            c.score = float(scores[i])

        # 最终排序：分数从高到低
        final_candidates.sort(key=lambda x: x.score, reverse=True)

        return final_candidates[:top_k]



class MultiQueryRetriever(BaseRetriever):
    """
    多路查询检索器：
    LLM 改写问题 -> 并发调用 Hybrid (无重排) -> 汇总去重 -> 最终重排序
    """

    def __init__(self):
        self.child_retriever = HybridRetriever()
        self.llm = get_llm()

    def generate_queries(self, original_query):
        """完整还原：让 AI 生成 3 个相似问题"""
        template = """你是一个专业的文档检索助手。
请针对用户的问题，生成 3 个不同版本的搜索查询，以便从数据库中检索相关文档。
请直接提供 3 个替代查询，每行一个，不要包含序号(1. 2. 3.)或解释。

原始问题：{question}
"""
        prompt = ChatPromptTemplate.from_template(template)

        # 定义一个简单的解析函数
        def parse_lines(text):
            lines = text.strip().split("\n")
            return [line.strip() for line in lines if line.strip()]

        chain = prompt | self.llm | StrOutputParser() | parse_lines

        try:
            queries = chain.invoke({"question": original_query})
            queries.append(original_query)
            return list(set(queries))
        except Exception as e:
            print(f"⚠️ 查询生成失败: {e}")
            return [original_query]

    def query(self, text: str, kb_id: int = None, doc_id: int = None, top_k: int = 3):
        # 1. 生成查询
        generated_queries = self.generate_queries(text)
        print(f"💡 [Multi-Query] 生成查询: {generated_queries}")

        all_candidates = {}

        for q in generated_queries:
            # 🔥 关键：传递 参数给子检索器
            results = self.child_retriever.query(q, kb_id, doc_id, top_k=5, needs_rerank=False)
            for doc in results:
                if doc.id not in all_candidates:
                    all_candidates[doc.id] = doc

        unique_candidates = list(all_candidates.values())
        if not unique_candidates: return []

        print(f"🔍 [Multi-Query] 汇总召回 {len(unique_candidates)} 个切片...")

        # 最终重排序
        reranker = get_reranker()
        pairs = [[text, c.content] for c in unique_candidates]
        scores = reranker.predict(pairs)

        for i, c in enumerate(unique_candidates):
            c.score = float(scores[i])

        unique_candidates.sort(key=lambda x: x.score, reverse=True)
        print(f"最后的候选人-{unique_candidates}")
        return unique_candidates[:top_k]



