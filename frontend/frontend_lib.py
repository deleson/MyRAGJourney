import streamlit as st
import requests
import extra_streamlit_components as stx
import datetime
import time

# --- 全局配置 ---
BACKEND_URL = "http://127.0.0.1:8000/api"


# --- Cookie 管理器 ---
def get_cookie_manager():
    return stx.CookieManager()


cookie_manager = get_cookie_manager()


# --- 辅助函数 ---
def fetch_user_me(token):
    try:
        resp = requests.get(f"{BACKEND_URL}/users/me/", headers={"Authorization": f"Bearer {token}"}, timeout=3)
        return resp.json() if resp.status_code == 200 else None
    except:
        return None


def get_token():
    return st.session_state.get("token")


def get_headers():
    token = get_token()
    return {"Authorization": f"Bearer {token}"} if token else {}


# --- 核心：API 请求 (带缓存) ---
@st.cache_data(ttl=60, show_spinner=False)
def _fetch_kbs(token):
    if not token: return []
    try:
        resp = requests.get(f"{BACKEND_URL}/knowledge-bases/", headers={"Authorization": f"Bearer {token}"})
        return resp.json() if resp.status_code == 200 else []
    except:
        return []


def get_kbs(): return _fetch_kbs(get_token())


@st.cache_data(ttl=60, show_spinner=False)
def _fetch_docs(token, kb_id):
    if not token: return []
    try:
        resp = requests.get(f"{BACKEND_URL}/documents/?kb_id={kb_id}", headers={"Authorization": f"Bearer {token}"})
        return resp.json() if resp.status_code == 200 else []
    except:
        return []


def get_docs(kb_id): return _fetch_docs(get_token(), kb_id)


def clear_docs_cache():
    _fetch_docs.clear()
    _fetch_kbs.clear()


# --- 核心：会话与登录 ---

def get_sessions(session_type=None):
    if not get_token(): return []
    try:
        url = f"{BACKEND_URL}/chat/sessions/"
        # 🔥 如果传了类型，拼接到 URL 上
        if session_type:
            url += f"?type={session_type}"

        resp = requests.get(url, headers=get_headers())
        return resp.json() if resp.status_code == 200 else []
    except:
        return []


def get_session_history(session_id):
    if not get_token(): return []
    try:
        resp = requests.get(f"{BACKEND_URL}/chat/sessions/?id={session_id}", headers=get_headers())
        return resp.json() if resp.status_code == 200 else []
    except:
        return []


# 🔥 核心修正：初始化状态 (含自动恢复会话)
def init_state():
    # 1. 基础占位
    if "current_session_id" not in st.session_state: st.session_state.current_session_id = None
    if "messages" not in st.session_state: st.session_state.messages = []
    if "user_info" not in st.session_state: st.session_state.user_info = {}
    if "token" not in st.session_state: st.session_state.token = None

    # 2. Cookie 自动登录
    if not st.session_state.token:
        token_from_cookie = cookie_manager.get("nexus_token")
        if token_from_cookie:
            user_data = fetch_user_me(token_from_cookie)
            if user_data:
                st.session_state.token = token_from_cookie
                st.session_state.user_info = user_data

                # 🔥 自动恢复最近会话
                if not st.session_state.current_session_id:
                    sessions = get_sessions()
                    if sessions:
                        latest = sessions[0]['id']
                        st.session_state.current_session_id = latest
                        st.session_state.messages = get_session_history(latest)
            else:
                # Token 无效，清理 (加key防止冲突)
                cookie_manager.delete("nexus_token", key="del_invalid_init")


# 🔥 核心修正：注销
def logout_api():
    # 1. 清空内存
    st.session_state.token = None
    st.session_state.user_info = {}
    st.session_state.messages = []
    st.session_state.current_session_id = None

    # 2. 清空 Cookie (加key防止冲突)
    cookie_manager.delete("nexus_token", key="del_logout")

    # 3. 清除缓存，防止下一个用户看到上一个用户的数据
    clear_docs_cache()


def login_api(username, password):
    try:
        resp = requests.post(f"{BACKEND_URL}/token/", json={"username": username, "password": password})
        if resp.status_code == 200:
            data = resp.json()
            token = data['access']

            # 🔥🔥🔥 修正：登录成功后，立刻用 Token 去换取完整用户信息 (包含 is_staff) 🔥🔥🔥
            user_data = fetch_user_me(token)

            if user_data:
                st.session_state.token = token
                st.session_state.user_info = user_data  # 这里面就有 is_staff 了
            else:
                # 兜底：万一 fetch 失败，至少能登录，但没权限
                st.session_state.token = token
                st.session_state.user_info = {"username": username}

            # 写入 Cookie
            expires = datetime.datetime.now() + datetime.timedelta(days=7)
            cookie_manager.set("nexus_token", token, expires_at=expires)

            init_state()
            return True
        return False
    except Exception as e:
        print(f"Login Error: {e}")
        return False


def register_api(username, password, email=""):
    try:
        resp = requests.post(f"{BACKEND_URL}/register/",
                             data={"username": username, "password": password, "email": email})
        return resp.status_code == 201
    except:
        return False


def delete_session(session_id):
    try:
        resp = requests.delete(f"{BACKEND_URL}/chat/sessions/?id={session_id}", headers=get_headers())
        return resp.status_code == 204
    except:
        return False


def delete_document_api(doc_id):
    try:
        resp = requests.delete(f"{BACKEND_URL}/documents/{doc_id}/", headers=get_headers())
        clear_docs_cache()
        return resp.status_code == 204
    except:
        return False


def update_document_status_api(doc_id, status):
    try:
        resp = requests.patch(f"{BACKEND_URL}/documents/{doc_id}/", json={"status": status}, headers=get_headers())
        clear_docs_cache()
        return resp.status_code == 200
    except:
        return False


def upload_file_api(file, kb_id):
    try:
        file.seek(0)
        mime = file.type or "application/octet-stream"
        files = {"file": (file.name, file, mime)}
        data = {"kb_id": kb_id}
        resp = requests.post(f"{BACKEND_URL}/upload/", files=files, data=data, headers=get_headers())
        return resp
    except:
        return None


def auth_check():
    if not st.session_state.token:
        st.warning("⚠️ 请先登录")
        if st.button("去登录", type="primary"):
            st.switch_page("pages/0_用户中心.py")
        st.stop()
    else:
        username = st.session_state.user_info.get("username", "Unknown")
        with st.sidebar:
            st.markdown(f"👤 **{username}**")
            if st.button("注销", key="sidebar_logout", use_container_width=True):
                logout_api()
                st.rerun()
            st.divider()


def submit_feedback_api(msg_id, rating, comment=""):
    try:
        resp = requests.patch(
            f"{BACKEND_URL}/messages/{msg_id}/feedback/",
            json={"rating": rating, "comment": comment},
            headers=get_headers()
        )
        return resp.status_code == 200
    except: return False



def get_admin_stats():
    """获取看板数据"""
    if not st.session_state.token: return None
    try:
        resp = requests.get(f"{BACKEND_URL}/admin/dashboard/", headers=get_headers())
        if resp.status_code == 200:
            return resp.json()
        return None
    except: return None