# frontend/pages/1_📚_知识库对话.py
import streamlit as st
import requests
import json
import time
# ✅ 正确导入：直接从同级 lib 导入
from frontend_lib import (
    init_state, get_kbs, get_docs, get_sessions, get_session_history,
    delete_session, clear_docs_cache, upload_file_api, BACKEND_URL,auth_check,get_headers
)

st.set_page_config(page_title="知识库对话", layout="wide", page_icon="📚")
init_state()

# 🔥🔥🔥 核心：放置安检门 🔥🔥🔥
# 如果没登录，代码会在这里 st.stop()，下面的所有代码都不会执行
auth_check()


# --- 侧边栏 ---
with st.sidebar:
    st.title("📚 RAG 控制台")

    # 1. 会话管理
    if st.button("➕ 新建对话", width='stretch'):
        st.session_state.current_session_id = None
        st.session_state.messages = []
        st.rerun()

    with st.container(height=300, border=False):
        sessions = get_sessions(session_type='rag')
        for sess in sessions:
            col1, col2 = st.columns([0.8, 0.2])
            is_active = (sess['id'] == st.session_state.current_session_id)
            label = f"{'🟢' if is_active else '⚪'} {sess['title']}"
            with col1:
                if st.button(label, key=f"s_{sess['id']}", width='stretch'):
                    st.session_state.current_session_id = sess['id']
                    st.session_state.messages = get_session_history(sess['id'])
                    st.rerun()
            with col2:
                if st.button("🗑️", key=f"d_{sess['id']}"):
                    if delete_session(sess['id']):
                        if is_active:
                            st.session_state.current_session_id = None
                            st.session_state.messages = []
                        st.rerun()

    st.divider()

    # 2. 知识库配置
    kbs = get_kbs()
    kb_opts = {k['name']: k['id'] for k in kbs}


    def on_kb_change():
        st.session_state.doc_idx = 0  # 重置文档选择


    sel_kb_name = st.selectbox("选择知识库", options=kb_opts.keys(), index=0 if kbs else None, on_change=on_kb_change)
    sel_kb_id = kb_opts.get(sel_kb_name)

    # 3. 文档与上传
    doc_id = None
    if sel_kb_id:
        docs = get_docs(sel_kb_id)
        doc_map = {"🔍 全库检索": None}
        for d in docs: doc_map[f"📄 {d.get('name')}"] = d['id']

        sel_doc_label = st.selectbox("检索范围", options=list(doc_map.keys()))
        doc_id = doc_map.get(sel_doc_label)

        with st.expander("📂 上传文件"):
            up_file = st.file_uploader("Upload", type=["pdf", "txt", "md", "docx"])
            if up_file and st.button("上传"):
                with st.spinner("上传中..."):
                    resp = upload_file_api(up_file, sel_kb_id)
                    if resp and resp.status_code == 201:
                        st.toast("上传成功!", icon="🎉")
                        clear_docs_cache()
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("上传失败")

# --- 主界面 ---
st.subheader("📚 知识库问答")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("sources"):
            with st.expander("参考来源"):
                for s in msg["sources"]: st.info(s['content'])

if prompt := st.chat_input("输入问题..."):
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        try:
            payload = {
                "query": prompt, "kb_id": sel_kb_id, "doc_id": doc_id,
                "session_id": st.session_state.current_session_id
            }
            # 调用普通 Chat 接口
            with requests.post(f"{BACKEND_URL}/chat/", json=payload, stream=True, headers=get_headers()) as resp:
                if resp.status_code == 200:
                    def streamer():
                        for line in resp.iter_lines():
                            if line:
                                data = json.loads(line)
                                if data['type'] == 'meta':
                                    if not st.session_state.current_session_id:
                                        st.session_state.current_session_id = data['session_id']
                                    resp._sources = data['sources']
                                elif data['type'] == 'content':
                                    yield data['chunk']


                    full = st.write_stream(streamer())
                    sources = getattr(resp, '_sources', [])
                    if sources:
                        with st.expander("参考来源"):
                            for s in sources: st.info(s['content'])

                    st.session_state.messages.append({"role": "assistant", "content": full, "sources": sources})

                    if len(st.session_state.messages) <= 2: time.sleep(0.5); st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")