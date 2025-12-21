import streamlit as st
import time
from frontend_lib import (
    init_state, get_kbs, get_docs,
    delete_document_api, update_document_status_api,auth_check
)

st.set_page_config(page_title="文档管理", layout="wide", page_icon="📁")
init_state()


# 🔥🔥🔥 放置安检门 🔥🔥🔥
# 如果没登录，代码会在这里 st.stop()，下面的所有代码都不会执行
auth_check()

# 检查登录
if not st.session_state.token:
    st.warning("请先前往 [用户中心] 登录")
    st.stop()

st.title("📁 文档资源管理器")

# 1. 顶部栏：选择知识库
kbs = get_kbs()
if not kbs:
    st.info("暂无知识库")
    st.stop()

kb_names = {k['name']: k['id'] for k in kbs}
selected_kb_name = st.selectbox("当前查看的知识库", list(kb_names.keys()))
selected_kb_id = kb_names[selected_kb_name]

st.divider()

# 2. 文档网格展示
docs = get_docs(selected_kb_id)

if not docs:
    st.info("该库为空，请去 [知识库对话] 页面上传文件。")
else:
    # 模拟 Windows 大图标：每行 4 个
    cols_per_row = 4
    rows = [docs[i:i + cols_per_row] for i in range(0, len(docs), cols_per_row)]

    for row in rows:
        cols = st.columns(cols_per_row)
        for idx, doc in enumerate(row):
            with cols[idx]:
                # 使用 container 模拟卡片效果
                with st.container(border=True):
                    # 图标 (根据后缀名稍微变一下)
                    icon = "📄"
                    if doc['file'].endswith('.pdf'):
                        icon = "📕"
                    elif doc['file'].endswith('.docx'):
                        icon = "📘"

                    st.markdown(f"### {icon}")
                    st.text(doc.get('name', '未命名'))

                    # 状态标签
                    status = doc['status']
                    status_color = {
                        "active": "green",
                        "pending": "orange",
                        "reviewing": "blue",
                        "failed": "red"
                    }.get(status, "grey")
                    st.markdown(f":{status_color}[{status}]")

                    # --- 操作按钮区 ---
                    # 只有 reviewing 状态显示“通过”按钮
                    if status == 'reviewing':
                        if st.button("✅ 通过", key=f"pass_{doc['id']}"):
                            if update_document_status_api(doc['id'], 'active'):
                                st.toast("审核通过！")
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error("无权限")

                    # 删除按钮
                    if st.button("🗑️ 删除", key=f"del_doc_{doc['id']}"):
                        if delete_document_api(doc['id']):
                            st.toast("删除成功")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error("删除失败 (无权限)")