import streamlit as st
import time
from frontend_lib import init_state, login_api, register_api,logout_api

st.set_page_config(page_title="用户中心", page_icon="👤")
init_state()

st.title("👤 用户中心")

# --- 场景 A: 已登录 ---
if st.session_state.token:
    username = st.session_state.user_info.get('username', '')
    st.success(f"🎉 欢迎回来, **{username}**!")

    st.info("您可以直接点击左侧侧边栏访问功能页面。")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🚀 进入 RAG 对话", width='stretch'):
            st.switch_page("pages/1_知识库对话.py")
    with col2:
        if st.button("📂 管理文档", width='stretch'):
            st.switch_page("pages/3_文档管理.py")

    st.divider()

    # 🔥 修改注销按钮逻辑
    if st.button("注销登录", type="secondary"):
        logout_api() # 调用封装好的清理函数
        st.rerun()   # 刷新页面

# --- 场景 B: 未登录 ---
else:
    tab1, tab2 = st.tabs(["🔑 登录", "✨ 注册新账号"])

    with tab1:
        with st.form("login_form"):
            st.subheader("登录")
            username = st.text_input("用户名")
            password = st.text_input("密码", type="password")
            submitted = st.form_submit_button("登录", width='stretch')

            if submitted:
                if not username or not password:
                    st.error("请输入用户名和密码")
                elif login_api(username, password):
                    st.toast("登录成功！正在跳转...", icon="🎉")
                    time.sleep(0.5)
                    st.rerun()  # 刷新页面进入“已登录”状态
                else:
                    st.error("用户名或密码错误")

    with tab2:
        with st.form("register_form"):
            st.subheader("注册")
            new_user = st.text_input("设置用户名")
            new_pass = st.text_input("设置密码", type="password")
            email = st.text_input("邮箱 (可选)")
            reg_submitted = st.form_submit_button("注册", width='stretch')

            if reg_submitted:
                if not new_user or not new_pass:
                    st.error("用户名和密码不能为空")
                elif register_api(new_user, new_pass, email):
                    st.success("✅ 注册成功！请切换到登录标签页进行登录。")
                else:
                    st.error("注册失败，用户名可能已存在。")