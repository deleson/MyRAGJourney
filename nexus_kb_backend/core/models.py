from django.db import models
from pgvector.django import VectorField  # 核心：Postgres 向量字段
import uuid
from django.contrib.auth.models import User
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField

class KnowledgeBase(models.Model):
    """知识库（类似文件夹）"""
    name = models.CharField(max_length=50, verbose_name="知识库名称")
    description = models.TextField(blank=True, verbose_name="描述")
    created_at = models.DateTimeField(auto_now_add=True)

    # null=True 是为了兼容旧数据（旧数据没有 owner）。
    # 生产环境建议处理完旧数据后设为 null=False
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, verbose_name="拥有者")


    def __str__(self):
        return self.name


def user_directory_path(instance, filename):
    # 文件将上传到 MEDIA_ROOT/uploads/user_<id>/<filename>
    return 'uploads/user_{0}/{1}'.format(instance.uploaded_by.name, filename)


class Document(models.Model):
    """上传的原始文档"""
    STATUS_CHOICES = [
        ('pending', '等待处理'),      # 系统正在切分向量
        ('reviewing', '待审核'),      # 🔥 新增：处理完了，等人审核
        ('active', '已发布'),         # 🔥 新增：审核通过，可被检索
        ('failed', '处理失败'),
    ]

    # 🔥 新增字段：记录是谁上传的
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="上传者")

    name = models.CharField(max_length=255, verbose_name="原始文件名", default="未命名文档")

    kb = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE, related_name='documents', verbose_name="所属知识库")
    # 可以改用使用动态路径，但是由于目前上传的文档属于公共部分，因此暂时不采用区分
    # file = models.FileField(upload_to=user_directory_path, verbose_name="文件")
    file = models.FileField(upload_to='uploads', verbose_name="文件")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="状态")
    error_message = models.TextField(blank=True, null=True, verbose_name="错误信息")
    created_at = models.DateTimeField(auto_now_add=True)
    summary = models.TextField(blank=True, null=True, verbose_name="文档摘要")


    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"


class DocumentChunk(models.Model):
    """
    文档切片与向量
    这是 RAG 的核心：替代 ChromaDB
    """
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='chunks')
    chunk_index = models.IntegerField(verbose_name="切片序号")
    content = models.TextField(verbose_name="文本内容")

    # dimensions=512 对应 bge-small-zh-v1.5
    # 如果用 text2vec-base-chinese，这里要改成 768
    # 如果用 OpenAI，这里要改成 1536
    embedding = VectorField(dimensions=512, verbose_name="向量数据")

    meta_info = models.JSONField(default=dict, verbose_name="元数据详情")

    class Meta:
        indexes = [
            # 为 content 字段创建 GIN 倒排索引，加速关键词匹配
            GinIndex(
                fields=['content'],
                name='chunk_content_gin_idx',
                opclasses=['gin_trgm_ops'] # 需要 pg_trgm 扩展
            )
        ]



    def __str__(self):
        return f"{self.document.file.name} - Chunk {self.chunk_index}"




class ChatSession(models.Model):
    """
    会话上下文
    相当于一个“聊天窗口”
    """
    SESSION_TYPES = [
        ('rag', '知识库对话'),
        ('agent', '全能智能体'),
    ]
    session_type = models.CharField(
        max_length=10,
        choices=SESSION_TYPES,
        default='rag',  # 默认旧数据都是 RAG
        verbose_name="会话类型"
    )


    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # 暂时允许为空，未来对接用户系统时可以填 user_id
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, verbose_name="所属用户")
    # owner_id = models.CharField(max_length=100, default='guest', verbose_name="归属用户")
    title = models.CharField(max_length=200, default="新会话", verbose_name="会话标题")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

class ChatMessage(models.Model):
    """
    单条消息记录
    """
    ROLE_CHOICES = [
        ('user', '用户'),
        ('assistant', 'AI助手'),
        ('system', '系统设定'),
    ]

    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, verbose_name="角色")
    content = models.TextField(verbose_name="内容")
    # 存储引用来源 (RAG 特有)，JSON格式存入
    sources = models.JSONField(default=list, blank=True, verbose_name="引用来源")
    created_at = models.DateTimeField(auto_now_add=True)


    # 🔥🔥🔥 新增：反馈字段 🔥🔥🔥
    # 1: 点赞, -1: 点踩, 0: 无
    rating = models.IntegerField(default=0, verbose_name="评分")
    # 用户填写的具体反馈意见
    feedback_comment = models.TextField(blank=True, null=True, verbose_name="反馈备注")




    class Meta:
        ordering = ['created_at'] # 按时间正序排列

    def __str__(self):
        return f"[{self.role}] {self.content[:20]}..."

class UserMemory(models.Model):
    """
    用户画像记忆表
    存储关于用户的具体事实 (Fact)，例如 "用户习惯使用 Python"
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='memories')
    content = models.TextField(verbose_name="记忆内容")

    # 向量化存储，用于检索相关记忆
    embedding = VectorField(dimensions=512, verbose_name="向量数据")

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username}: {self.content[:30]}..."