import streamlit as st
import requests
import json
import time
from frontend_lib import (
    init_state, get_sessions, get_session_history, delete_session,
    BACKEND_URL, auth_check, get_headers,submit_feedback_api
)

# --- 页面配置 ---
st.set_page_config(page_title="全能智能体", layout="wide", page_icon="🕵️")
init_state()

# --- CSS 美化 ---
st.markdown("""
<style>
    /* Status 容器样式 */
    .stStatusWidget {background-color: #f8f9fa; border-radius: 8px; border-left: 4px solid #ff4b4b;}

    /* 限制图片大小 */
    div[data-testid="stChatMessage"] img {
        max-width: 450px !important;
        height: auto !important;
        border-radius: 8px;
        border: 1px solid #ddd;
        margin-top: 10px;
        margin-bottom: 10px;
    }
</style>
""", unsafe_allow_html=True)

# 权限检查
auth_check()

# --- 侧边栏 ---
with st.sidebar:
    st.title("🕵️ Agent 控制台")
    if st.button("➕ 新建任务", width='stretch'):
        st.session_state.current_session_id = None
        st.session_state.messages = []
        st.rerun()

    st.divider()

    with st.container(height=450, border=False):
        sessions = get_sessions(session_type='agent')
        for sess in sessions:
            col1, col2 = st.columns([0.8, 0.2])
            is_active = (sess['id'] == st.session_state.current_session_id)
            label = f"{'🔴' if is_active else '⚪'} {sess['title']}"

            with col1:
                if st.button(label, key=f"sa_{sess['id']}", width='stretch'):
                    st.session_state.current_session_id = sess['id']
                    st.session_state.messages = get_session_history(sess['id'])
                    st.rerun()
            with col2:
                if st.button("🗑️", key=f"da_{sess['id']}"):
                    if delete_session(sess['id']):
                        if is_active:
                            st.session_state.current_session_id = None
                            st.session_state.messages = []
                        st.rerun()

# --- 主界面 ---
st.title("🕵️ Nexus 全能智能体")
st.caption("🚀 支持联网 (Tavily)、内网查库、数据统计 | Powered by LangGraph")

# 🔥🔥🔥 1. 渲染历史记录 (修正版：只保留思考过程和反馈) 🔥🔥🔥
for msg in st.session_state.messages:
    avatar = "👤" if msg["role"] == "user" else "🕵️"

    with st.chat_message(msg["role"], avatar=avatar):
        # 1.1 显示思考过程 (Agent 特有)
        if "thoughts" in msg and msg["thoughts"]:
            with st.status("✨ 历史思考过程", state="complete", expanded=False):
                for thought in msg["thoughts"]:
                    st.write(thought)

        # 1.2 显示正文
        st.markdown(msg["content"])

        # (已删除 sources 渲染部分，因为 Agent 模式下没有结构化来源)

        # 1.3 反馈按钮 (只给 Assistant)
        if msg["role"] == "assistant":
            msg_id = msg.get("id")
            # 注意：rating 默认为 0

            if msg_id:
                fb_key = f"fb_agent_{msg_id}"


                def on_feedback_change(mid=msg_id, k=fb_key):
                    val = st.session_state.get(k)
                    api_rating = 1 if val == 1 else -1 if val == 0 else 0
                    if submit_feedback_api(mid, api_rating):
                        st.toast("反馈已提交！", icon="👍")
                    else:
                        st.toast("提交失败", icon="❌")


                # 渲染组件
                st.feedback(
                    "thumbs",
                    key=fb_key,
                    on_change=on_feedback_change,
                )

# 2. 处理新输入
if prompt := st.chat_input("下达指令..."):
    with st.chat_message("user", avatar="👤"):
        st.markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant", avatar="🕵️"):
        # 状态容器
        status_container = st.status("🧠 Agent 正在思考...", expanded=True)
        # 思考缓存
        thought_buffer = []
        # 🔥 临时变量：用于在流式过程中捕获后端传回的 ID
        st.session_state.temp_latest_msg_id = None

        try:
            payload = {
                "query": prompt,
                "session_id": st.session_state.current_session_id
            }

            with requests.post(f"{BACKEND_URL}/agent/chat/", json=payload, stream=True, headers=get_headers()) as resp:
                if resp.status_code == 200:

                    def streamer():
                        for line in resp.iter_lines():
                            if line:
                                try:
                                    data = json.loads(line)
                                except:
                                    continue

                                # A. 元数据
                                if data['type'] == 'meta':
                                    if not st.session_state.current_session_id:
                                        st.session_state.current_session_id = data['session_id']

                                # B. 状态更新
                                elif data['type'] == 'status':
                                    content = data['content']
                                    log_text = f"🤖 {content}"
                                    if any(k in content for k in ["联网", "搜索", "search_web", "tavily"]):
                                        status_container.update(label="🌍 正在联网搜索...", state="running")
                                        log_text = f"🌐 {content}"
                                    elif any(k in content for k in ["知识库", "文档", "query_knowledge_base"]):
                                        status_container.update(label="📚 正在查阅知识库...", state="running")
                                        log_text = f"📚 {content}"
                                    elif any(k in content for k in ["统计", "get_db_stat"]):
                                        status_container.update(label="📊 正在统计数据...", state="running")
                                        log_text = f"📊 {content}"
                                    elif any(k in content for k in ["python", "repl", "代码"]):
                                        status_container.update(label="🐍 正在执行代码...", state="running")
                                        log_text = f"🐍 {content}"
                                    elif "完成" in content:
                                        status_container.write("✅ 步骤完成")
                                        log_text = "✅ 步骤完成"
                                    else:
                                        status_container.write(log_text)

                                    thought_buffer.append(log_text)

                                # C. 答案流 (Yield 给 write_stream)
                                elif data['type'] == 'content':
                                    yield data['chunk']

                                # 🔥🔥🔥 D. 捕获 ID (静默处理) 🔥🔥🔥
                                elif data['type'] == 'final':
                                    # 将 ID 存入 session_state，供外部使用
                                    st.session_state.temp_latest_msg_id = data['msg_id']
                                    # ⚠️ 绝对不要 yield，否则会把 JSON 打印到屏幕上
                                    continue

                                    # E. 错误
                                elif data['type'] == 'error':
                                    status_container.update(label="❌ 出错了", state="error")
                                    st.error(data['content'])


                    # 1. 执行流式输出
                    full_res = st.write_stream(streamer())

                    # 2. 更新状态栏
                    status_container.update(label="✨ 执行完成", state="complete", expanded=False)

                    # 3. 拿到刚才捕获的 ID
                    new_msg_id = st.session_state.temp_latest_msg_id

                    # 🔥🔥🔥 4. 立即渲染反馈按钮 (无需刷新) 🔥🔥🔥
                    if new_msg_id:
                        fb_key = f"fb_agent_{new_msg_id}"


                        def on_feedback_change(mid=new_msg_id, k=fb_key):
                            val = st.session_state.get(k)
                            api_rating = 1 if val == 1 else -1 if val == 0 else 0
                            if submit_feedback_api(mid, api_rating):
                                st.toast("反馈已提交！", icon="👍")
                            else:
                                st.toast("提交失败", icon="❌")


                        st.feedback("thumbs", key=fb_key, on_change=on_feedback_change)

                    # 5. 更新本地历史记录 (包含 ID，这样下次刷新也能看到按钮)
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": full_res,
                        "thoughts": thought_buffer,
                        "id": new_msg_id,  # 把 ID 存进去
                        "rating": 0
                    })

                    # 6. 仅在是“新对话”时才刷新 (为了更新侧边栏标题)
                    if len(st.session_state.messages) <= 2:
                        time.sleep(0.5)
                        st.rerun()
                else:
                    status_container.update(label="❌ 服务器错误", state="error")
                    st.error(f"Error: {resp.text}")
        except Exception as e:
            st.error(f"Network Error: {e}")