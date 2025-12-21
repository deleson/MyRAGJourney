import os

# 🔥🔥🔥 新增：Matplotlib 全局配置 (必须在 import pyplot 之前) 🔥🔥🔥
import matplotlib
# 1. 强制使用非交互式后端 (解决 RuntimeError 和 Thread 报错)
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# 2. 解决中文乱码 (Windows下通常用 SimHei 或 Microsoft YaHei)
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False # 解决负号显示问题



from langchain_core.tools import tool
from pydantic import BaseModel, Field
from langchain_tavily import TavilySearch
from .models import Document
from .retrievers import MultiQueryRetriever
from langchain_experimental.tools import PythonREPLTool
# --- 1. 初始化 Tavily 工具 ---
# 使用 Community 版本，参数名通常是 max_results (旧版) 或 k (新版)
# 为了保险，我们初始化时不传参数，在 invoke 时传
tavily_client = TavilySearch()


# --- 2. 定义输入结构 (Schema) ---
# 这是给 DeepSeek 看的“说明书”，告诉它必须传什么参数，不能乱传

class WebSearchInput(BaseModel):
    query: str = Field(description="需要搜索的关键词或问题")


class KBQueryInput(BaseModel):
    query: str = Field(description="用户的具体问题")
    kb_id: int = Field(description="知识库的ID (整数)")


class DBStatInput(BaseModel):
    kb_id: int = Field(description="知识库的ID (整数)")


# --- 3. 定义工具函数 ---

@tool
def search_web(query: str) -> str:
    """
    联网搜索工具。
    当用户询问当前发生的新闻、实时信息（如股价、天气）、或者知识库里没有的通用知识时，必须使用此工具。
    输入应该是一个具体的搜索查询语句。
    """
    print(f"🌐 [Tool] 正在搜索互联网 (Tavily): {query}")
    try:
        # invoke 返回的可能是 List 也可能是 Dict，取决于版本
        raw_response = tavily_client.invoke({
            "query": query,
            "k": 6
        })

        # 兼容性处理：如果返回的是字典，取 'results' 字段
        if isinstance(raw_response, dict) and 'results' in raw_response:
            results = raw_response['results']
        elif isinstance(raw_response, list):
            results = raw_response
        else:
            return "未找到相关网络结果(格式错误)。"

        if not results:
            return "未找到相关网络结果。"

        # 格式化结果
        context_list = []
        for res in results:
            # 提取字段 (加上默认值防崩)
            url = res.get('url', '')
            content = res.get('content', '')
            title = res.get('title', '')
            # 拼装成 AI 易读的格式
            context_list.append(f"标题: {title}\n来源: {url}\n内容: {content}")

        return "\n---\n".join(context_list)

    except Exception as e:
        return f"搜索失败: {e}"


@tool(args_schema=KBQueryInput)
def query_knowledge_base(query: str, kb_id: int) -> str:
    """
    内部知识库检索工具。
    当用户询问关于公司内部文档、具体业务细节、规章制度时，必须使用此工具。
    """
    print(f"📚 [Tool] 正在查询知识库 (KB: {kb_id}): {query}")
    try:
        retriever = MultiQueryRetriever()
        # 注意：这里我们调用的是内部逻辑，不需要 Pydantic，直接传参
        chunks = retriever.query(text=query, kb_id=kb_id, top_k=3)

        if not chunks:
            return "知识库中未找到相关内容。"

        results = []
        for c in chunks:
            source = c.document.name
            meta = c.meta_info if hasattr(c, 'meta_info') else {}
            header_path = " > ".join(map(str, meta.values())) if meta else ""
            content = f"来源: {source} ({header_path})\n内容: {c.content}\n"
            results.append(content)

        return "\n---\n".join(results)
    except Exception as e:
        return f"检索出错: {str(e)}"


@tool(args_schema=DBStatInput)
def get_db_stat(kb_id: int) -> str:
    """
    数据库统计工具。
    当用户询问“有多少个文件”、“文件列表是什么”时使用。
    """
    print(f"📊 [Tool] 正在统计数据库 (KB: {kb_id})")
    try:
        count = Document.objects.filter(kb_id=kb_id).count()
        names = list(Document.objects.filter(kb_id=kb_id).order_by('-created_at').values_list('name', flat=True)[:10])
        return f"当前知识库 (ID: {kb_id}) 共有 {count} 个文档。\n最新文档列表（部分）: {', '.join(names)}"
    except Exception as e:
        return f"统计出错: {str(e)}"


python_repl_tool = PythonREPLTool()

# 导出
ALL_TOOLS = [search_web, query_knowledge_base, get_db_stat,python_repl_tool]