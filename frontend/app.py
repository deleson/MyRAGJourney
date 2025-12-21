import streamlit as st

st.set_page_config(
    page_title="Nexus AI",
    layout="wide",
    page_icon="🤖"
)

st.title("🤖 欢迎使用 Nexus AI 知识库系统")

st.markdown("""
### 这里是企业级智能助手控制台

请在左侧侧边栏选择你需要的功能：

#### 📚 **1. 知识库对话 (RAG)**
*   **适用场景**：查询公司内部文档、规章制度、合同细节。
*   **特点**：严谨、准确、基于事实。
*   **核心技术**：混合检索 (Hybrid Search) + 重排序 (Rerank)。

#### 🕵️ **2. 全能智能体 (Agent)**
*   **适用场景**：不知道答案在哪里，或者需要联网搜索、统计数据。
*   **特点**：智能、灵活、能使用工具。
*   **核心技术**：LangGraph + Tool Calling + 联网搜索 (Tavily)。

---
*Powered by DeepSeek & LangGraph*
""")