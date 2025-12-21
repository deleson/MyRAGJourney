import streamlit as st
import pandas as pd
from frontend_lib import init_state, auth_check, get_admin_stats

st.set_page_config(page_title="数据看板", layout="wide", page_icon="📊")
init_state()
auth_check()

# 1. 权限检查
if not st.session_state.user_info.get('is_staff', False):
    st.error("🚫 权限不足：只有管理员可以访问此页面")
    st.stop()

st.title("📊 系统监控看板 (Live)")

# 2. 获取数据
with st.spinner("正在聚合全站数据..."):
    data = get_admin_stats()

if not data:
    st.error("无法获取数据，请检查网络或后端日志。")
    st.stop()

metrics = data['metrics']

# 3. 核心指标区
col1, col2, col3 = st.columns(3)

with col1:
    st.metric(
        "总用户数",
        metrics['users']['total'],
        f"+{metrics['users']['new']} 今日"
    )

with col2:
    st.metric(
        "知识库文档",
        metrics['docs']['total'],
        f"+{metrics['docs']['new']} 今日"
    )

with col3:
    st.metric(
        "总会话数",
        metrics['sessions']['total'],
        help="累计创建的聊天窗口数量"
    )

st.divider()

# 4. 差评反馈区
st.subheader("👎 最近差评反馈 (需人工介入)")

feedbacks = data['bad_feedbacks']
if feedbacks:
    # 转换为 DataFrame 方便展示
    df = pd.DataFrame(feedbacks)
    # 重命名列头使其更友好
    df.columns = ["用户", "相关问题", "AI 回答", "用户备注", "时间"]

    st.dataframe(
        df,
        width='stretch',
        hide_index=True,
        column_config={
            "AI 回答": st.column_config.TextColumn(width="medium"),
            "相关问题": st.column_config.TextColumn(width="medium"),
        }
    )
else:
    st.success("🎉 太棒了！最近没有收到差评反馈。")

st.divider()

# 5. 调用趋势图
st.subheader("📈 近7日调用量趋势")
chart_data = data['chart_data']

if chart_data:
    # Streamlit 需要 DataFrame 格式来画图
    chart_df = pd.DataFrame(
        list(chart_data.items()),
        columns=["日期", "消息数"]
    ).set_index("日期")

    st.line_chart(chart_df)
else:
    st.info("暂无足够的历史数据生成图表。")