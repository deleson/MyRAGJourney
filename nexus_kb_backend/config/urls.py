"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from core.views import (
    UploadDocumentView,
    ChatView,
    ChatSessionView,
    AgentChatView,
    UserRegistrationView,
    DocumentManageView,
    UserMeView,
    MessageFeedbackView,
    AdminDashboardView,
    KnowledgeBaseViewSet, DocumentViewSet
)

from django.conf import settings
from django.conf.urls.static import static

from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)


# --- 1. 定义路由器 ---
router = DefaultRouter()
# 注册 ViewSet，router 会自动生成对应的 URL
router.register(r'knowledge-bases', KnowledgeBaseViewSet, basename='knowledgebase')
router.register(r'documents', DocumentViewSet, basename='document')


urlpatterns = [
    path('admin/', admin.site.urls),

    # 🔥🔥🔥 新增：认证接口 🔥🔥🔥
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),  # 登录 (获取 Token)
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),  # 刷新 Token

    path('api/upload/', UploadDocumentView.as_view(), name='upload'),

    # 普通 RAG 接口
    path('api/chat/', ChatView.as_view(), name='chat'),

    # 历史记录接口
    path('api/chat/sessions/', ChatSessionView.as_view(), name='chat-sessions'),

    # 列表接口
    path('api/', include(router.urls)),

    # 🔥🔥🔥 新增：Agent 专用接口 🔥🔥🔥
    path('api/agent/chat/', AgentChatView.as_view(), name='agent-chat'),

    # 用户相关
    path('api/register/', UserRegistrationView.as_view(), name='register'),

    # 文档操作 (带 ID)
    path('api/documents/<int:pk>/', DocumentManageView.as_view(), name='doc-manage'),
    path('api/users/me/', UserMeView.as_view(), name='user-me'),

    path('api/messages/<int:pk>/feedback/', MessageFeedbackView.as_view(), name='msg-feedback'),
    path('api/admin/dashboard/', AdminDashboardView.as_view(), name='admin-dashboard'),
]

# 🔥 新增：仅在 DEBUG 模式下生效
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)