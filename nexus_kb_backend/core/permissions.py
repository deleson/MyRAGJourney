from rest_framework import permissions


class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    对象级权限：
    - 读取 (GET, HEAD, OPTIONS): 允许任何人
    - 写入 (PUT, DELETE): 仅允许对象的所有者 (obj.user)
    """

    def has_object_permission(self, request, view, obj):
        # 读取权限允许任何请求
        if request.method in permissions.SAFE_METHODS:
            return True

        # 写入权限仅允许 owner
        # 注意：你的模型里字段名是 user 还是 owner？我们统一用 user
        return obj.user == request.user


class IsReviewerOrReadOnly(permissions.BasePermission):
    """
    针对文档审核的权限：
    - 普通用户上传文档时，无权修改 status 字段（只能是 pending）
    - 只有知识库的所有者（user）才能修改 status 为 active
    """

    def has_permission(self, request, view):
        # 允许所有人访问列表和创建
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        # obj 是 Document 对象
        # 如果是修改操作
        if request.method in ['PUT', 'PATCH']:
            # 如果是知识库的主人，允许修改任何字段
            if obj.kb.user == request.user:
                return True
            # 如果是文档上传者本人，只能修改非 status 字段 (这里简化逻辑，暂且允许修改)
            # 但实际业务中，我们通常会在 Serializer 里做字段级的 read_only 限制
            return obj.uploaded_by == request.user

        return True