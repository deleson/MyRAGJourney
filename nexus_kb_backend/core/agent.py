# core/agent.py

# ✅ 引入 LangGraph 预构建的 React Agent
# 它底层自动处理 Tool Calling 循环和状态管理
from  langchain.agents import create_agent
from .utils import get_llm
from .tools import ALL_TOOLS
import os
from django.conf import settings





def create_nexus_agent(memories: str = ""):
    # 1. 准备路径变量
    # 物理路径: F:/.../nexus_kb_backend/media/charts
    charts_dir = os.path.join(settings.MEDIA_ROOT, 'charts')

    # 确保文件夹存在 (关键！防止 AI 报错)
    if not os.path.exists(charts_dir):
        os.makedirs(charts_dir)

    # 图片 URL 前缀: http://127.0.0.1:8000/media/charts
    # 注意：这里写死了本地地址，生产环境应该读取 ALLOWED_HOSTS
    charts_url_prefix = "http://127.0.0.1:8000/media/charts"

    # 2. 准备工具和 LLM
    llm = get_llm()
    tools = ALL_TOOLS

    # 🔥 动态注入记忆
    memory_section = ""
    if memories:
        memory_section = f"\n\n【用户长期记忆】(请利用这些信息更好地服务用户):\n{memories}\n"


    # 3. 定义更严谨的 Prompt
    # 🔥 我们把 charts_dir 和 charts_url_prefix 填进去 🔥
    system_prompt = f"""你是一个全能型的企业智能助手 Nexus。
    {memory_section}
    你拥有以下工具：
    1. search_web: 查外部信息。
    2. query_knowledge_base: 查内部文档。
    3. get_db_stat: 查统计。
    4. python_repl: 执行 Python 代码。

    决策逻辑：
    - 优先查内网，内网没有再联网。
    - 遇到计算或绘图需求，必须使用 python_repl。

    【关于画图的严格指令】：
    如果你需要生成图表：
    1. 使用 matplotlib 绘图。
    2. **严禁调用 plt.show()**，这会导致服务器崩溃。
    3. **必须**将图片保存到此绝对路径：`{charts_dir}/<文件名>.png`
    4. 设置字体以支持中文（代码中无需再次设置，环境已预设）。
    5. 在回答中，**必须**使用 Markdown 图片格式返回：`![图表]({charts_url_prefix}/<文件名>.png)`
    6. 不要使用 plt.show()，因为我看不到。
    """

    # 4. 创建并编译图
    # state_modifier 参数对应旧版的 system_message
    graph = create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt
    )

    return graph