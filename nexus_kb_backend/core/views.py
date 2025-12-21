import json
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from .models import Document, KnowledgeBase
from .tasks import process_document_task,extract_user_memory_task
from .utils import get_llm
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from rest_framework.generics import ListAPIView
from .serializers import KnowledgeBaseSerializer, DocumentSerializer
from .models import  ChatSession, ChatMessage # 导入新模型
from .serializers import ChatMessageSerializer # 导入序列化器
from .serializers import ChatSessionSerializer
from django.http import StreamingHttpResponse
from .retrievers import VectorRetriever, RerankRetriever,HybridRetriever,MultiQueryRetriever
from .agent import create_nexus_agent
from langchain_core.messages import HumanMessage, AIMessage,ToolMessage

# 权限
from .permissions import IsOwnerOrReadOnly,IsReviewerOrReadOnly
from rest_framework import status, permissions
from .serializers import UserRegistrationSerializer
from .models import UserMemory
from pgvector.django import CosineDistance
from .utils import get_embedding


# 1. 头部补充导入
from django.contrib.auth.models import User
from django.db.models import Count
from django.db.models.functions import TruncDate
from datetime import timedelta
from django.utils import timezone
from rest_framework.permissions import IsAdminUser


from rest_framework import viewsets



class UserRegistrationView(APIView):
    """用户注册"""
    permission_classes = [permissions.AllowAny] # 允许任何人访问

    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "注册成功，请登录"}, status=201)
        return Response(serializer.errors, status=400)


class DocumentManageView(APIView):
    """
    文档管理：删除 或 修改状态(审核)
    URL: /api/documents/<int:pk>/
    """

    def delete(self, request, pk):
        try:
            doc = Document.objects.get(pk=pk)
            # 权限检查：只有上传者或管理员(is_staff)能删
            if doc.uploaded_by != request.user and not request.user.is_staff:
                return Response({"error": "无权删除"}, status=403)

            doc.delete()  # 级联删除会删掉 chunks
            return Response({"message": "删除成功"}, status=204)
        except Document.DoesNotExist:
            return Response({"error": "文档不存在"}, status=404)

    def patch(self, request, pk):
        """用于修改状态 (例如审核通过)"""
        try:
            doc = Document.objects.get(pk=pk)
            new_status = request.data.get('status')

            # 权限检查：只有管理员(is_staff)或者是知识库的主人能审核
            # 这里简化逻辑：假设只有系统管理员(is_staff)能审核通过
            if not request.user.is_staff:
                return Response({"error": "只有管理员可以执行审核操作"}, status=403)

            if new_status:
                doc.status = new_status
                doc.save()
                return Response({"message": "状态更新成功", "status": doc.status})
            return Response({"error": "未提供状态"}, status=400)

        except Document.DoesNotExist:
            return Response({"error": "文档不存在"}, status=404)





class UploadDocumentView(APIView):
    # 支持文件上传
    parser_classes = (MultiPartParser, FormParser)
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        kb_id = request.data.get('kb_id') # 前端传来的知识库ID

        if not file_obj or not kb_id:
            return Response({"error": "缺少文件或知识库ID"}, status=status.HTTP_400_BAD_REQUEST)

        # 1. 检查 KB 是否存在
        try:
            kb = KnowledgeBase.objects.get(id=kb_id)
        except KnowledgeBase.DoesNotExist:
            return Response({"error": "知识库不存在"}, status=status.HTTP_404_NOT_FOUND)

        # 2. 判断状态
        # 如果上传者 == 知识库主人 -> 直接处理 (pending -> active)
        # 如果上传者 != 知识库主人 -> 需要审核 (pending -> reviewing)
        is_owner = (kb.user == request.user)
        initial_status = 'pending' # 都要先经过 Celery 处理


        doc = Document.objects.create(
            kb=kb,
            file=file_obj,
            name=file_obj.name,
            uploaded_by=request.user,  # 🔥 记录上传者
            status=initial_status
        )

        # 3. 触发 Celery (需要在 Task 里加个逻辑：处理完后是变成 active 还是 reviewing)
        # 我们传个标记给 Task
        process_document_task.delay(doc.id, auto_activate=is_owner)

        msg = "上传成功，正在处理..." if is_owner else "上传成功，等待管理员审核..."
        return Response({"message": msg, "doc_id": doc.id}, status=201)


class ChatView(APIView):
    def post(self, request, *args, **kwargs):
        # 1. 接收参数
        query = request.data.get('query')
        kb_id = request.data.get('kb_id')
        doc_id = request.data.get('doc_id')
        session_id = request.data.get('session_id')

        if not query:
            return Response({"error": "缺少 query"}, status=status.HTTP_400_BAD_REQUEST)

        # --- A. 获取/创建会话 ---
        session = None
        if session_id:
            try:
                session = ChatSession.objects.get(id=session_id)
            except ChatSession.DoesNotExist:
                session = ChatSession.objects.create(id=session_id, title=query[:20],user=request.user)
        else:
            # 🔥 显式标记为 rag
            session = ChatSession.objects.create(
                title=query[:20],
                user=request.user,
                session_type='rag'
            )

        # --- B. 保存用户提问 ---
        ChatMessage.objects.create(session=session, role='user', content=query)

        # --- C. 准备上下文 ---
        try:
            # 使用多路查询检索器
            retriever = MultiQueryRetriever()
            print("FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF")
            print(request.user)
            chunks = retriever.query(text=query, kb_id=kb_id, doc_id=doc_id, top_k=5)
            # print(f"this is chunks {chunks}")
        except Exception as e:
            return Response({"error": f"检索失败: {str(e)}"}, status=500)

        # 统计信息
        doc_count = 0
        doc_list_str = ""
        if kb_id:
            doc_count = Document.objects.filter(kb_id=kb_id).count()
            doc_names_qs = Document.objects.filter(kb_id=kb_id).values_list('name', flat=True)[:20]
            doc_list_str = ", ".join(doc_names_qs)

        # 组装 Context
        context_pieces = []
        sources_list = []
        for c in chunks:
            meta = c.meta_info if hasattr(c, 'meta_info') else {}
            header_text = f" (章节: {' > '.join(map(str, meta.values()))})" if meta else ""
            piece = f"--- 来源: {c.document.name}{header_text} ---\n{c.content}"
            context_pieces.append(piece)

            dist = getattr(c, 'distance', 0)
            sources_list.append({
                "id": c.id,
                "content": c.content[:100] + "...",
                "score": dist,
                "metadata": c.meta_info
            })

        context_text = "\n\n".join(context_pieces)

        # 🔥🔥🔥 1. 新增：获取摘要逻辑 (放在定义生成器之前) 🔥🔥🔥
        doc_summary = ""
        if doc_id:
            try:
                current_doc = Document.objects.get(id=doc_id)
                if current_doc.summary:
                    doc_summary = f"【当前文档摘要】：{current_doc.summary}\n\n"
            except Exception:
                pass

        # --- D. 定义生成器 ---
        def stream_generator():
            meta_data = {
                "type": "meta",
                "sources": sources_list,
                "session_id": str(session.id)
            }
            yield json.dumps(meta_data, ensure_ascii=False) + "\n"

            # 🔥🔥🔥 2. 修改：Prompt 模板加入 {summary} 🔥🔥🔥
            template = """你是一个专业的公司助手。
【统计信息】：
- 文档总数：{doc_count}
- 文档列表：{doc_list}

{summary}

请结合【历史对话】和【背景知识】回答用户问题。
如果不属于【历史对话】和【背景知识】的问题，直接拒绝回答，不要引入背景外的文档或知识。
回答要尽可能的专业和全面，但知识不能脱离背景

【历史对话】：
{history}

【背景知识】：
{context}

【用户问题】：
{question}
"""
            prompt = ChatPromptTemplate.from_template(template)
            llm = get_llm()
            chain = prompt | llm | StrOutputParser()

            # 获取历史记录
            history_msgs = ChatMessage.objects.filter(session=session).order_by('-created_at')[:6]
            history_text = ""
            for msg in reversed(history_msgs):
                if msg.content == query and msg.role == 'user': continue
                history_text += f"{msg.role}: {msg.content}\n"
            # print(f"最终提交 history: {history_text},\
            #     \ncontext: {context_text},\
            #     \nquestion: {query},\
            #     \ndoc_count: {doc_count},\
            #     \ndoc_list: {doc_list_str},\
            #     \nsummary: {doc_summary}")

            full_answer = ""
            # 🔥🔥🔥 3. 修改：传参时加入 summary 🔥🔥🔥
            for chunk in chain.stream({
                "history": history_text,
                "context": context_text,
                "question": query,
                "doc_count": doc_count,
                "doc_list": doc_list_str,
                "summary": doc_summary  # <--- 注入摘要变量
            }):
                full_answer += chunk
                yield json.dumps({"type": "content", "chunk": chunk}, ensure_ascii=False) + "\n"

            # 保存 AI 回答
            ChatMessage.objects.create(
                session=session,
                role='assistant',
                content=full_answer,
                sources=sources_list
            )

            if history_msgs.count() < 2:
                session.title = query[:20]
                session.save()

        return StreamingHttpResponse(stream_generator(), content_type='application/x-ndjson')

class KnowledgeBaseViewSet(viewsets.ModelViewSet):
    """
    知识库管理：增删改查
    自动生成: GET /, POST /, GET /:id/, PUT /:id/, DELETE /:id/
    """
    serializer_class = KnowledgeBaseSerializer
    permission_classes = [permissions.IsAuthenticated] # 仅限登录用户

    def get_queryset(self):
        # 只能看到自己的
        return KnowledgeBase.objects.filter(user=self.request.user).order_by('-created_at')

    def perform_create(self, serializer):
        # 创建时自动关联当前用户
        serializer.save(user=self.request.user)


class DocumentViewSet(viewsets.ModelViewSet):
    """
    文档管理：列表、详情、删除、修改状态
    注意：上传功能依然由 UploadDocumentView 处理（为了逻辑清晰）
    """
    serializer_class = DocumentSerializer
    permission_classes = [permissions.IsAuthenticated]
    # 允许的方法：查列表(list), 查详情(retrieve), 删除(destroy), 局部更新(partial_update)
    # 禁用 create，因为上传逻辑太复杂，单独处理
    http_method_names = ['get', 'delete', 'patch', 'head', 'options']

    def get_queryset(self):
        # 核心逻辑：用户隔离
        qs = Document.objects.filter(kb__user=self.request.user)

        # 支持按 kb_id 过滤 (?kb_id=1)
        kb_id = self.request.query_params.get('kb_id')
        if kb_id:
            qs = qs.filter(kb_id=kb_id)

        return qs.order_by('-created_at')


class ChatSessionView(APIView):
    """会话管理：获取列表 / 获取详情"""

    def get(self, request):
        # 如果传了 id，就获取单条会话的历史记录
        session_id = request.query_params.get('id')

        if session_id:
            try:
                session = ChatSession.objects.get(id=session_id,user=request.user)
                messages = session.messages.all()
                return Response(ChatMessageSerializer(messages, many=True).data)
            except ChatSession.DoesNotExist:
                return Response({"error": "会话不存在"}, status=404)

            # 🔥🔥🔥 修改列表获取逻辑 🔥🔥🔥
        qs = ChatSession.objects.filter(user=request.user)

        # 获取 URL 参数 ?type=agent
        session_type = request.query_params.get('type')
        if session_type:
            qs = qs.filter(session_type=session_type)

        sessions = qs.order_by('-updated_at')
        return Response(ChatSessionSerializer(sessions, many=True).data)


    # 🔥🔥🔥 新增 DELETE 方法 🔥🔥🔥
    def delete(self, request):
        session_id = request.query_params.get('id')
        if not session_id:
            return Response({"error": "缺少 id 参数"}, status=400)

        try:
            # 级联删除：删了会话，关联的消息也会自动删掉 (on_delete=CASCADE)
            ChatSession.objects.filter(id=session_id).delete()
            return Response({"message": "删除成功"}, status=204)
        except Exception as e:
            return Response({"error": str(e)}, status=500)


class AgentChatView(APIView):
    def post(self, request, *args, **kwargs):
        query = request.data.get('query')
        session_id = request.data.get('session_id')

        if not query:
            return Response({"error": "缺少 query"}, status=status.HTTP_400_BAD_REQUEST)

        # 1. 会话管理
        session = None
        if session_id:
            try:
                session = ChatSession.objects.get(id=session_id)
            except ChatSession.DoesNotExist:
                session = ChatSession.objects.create(id=session_id, title=query[:20],user=request.user)
        else:
            # session = ChatSession.objects.create(title=query[:20],user=request.user)

            # 🔥 显式标记为 agent
            session = ChatSession.objects.create(
                title=query[:20],
                user=request.user,
                session_type='agent'
            )

        # 2. 保存用户提问
        ChatMessage.objects.create(session=session, role='user', content=query)

        # 3. 准备历史记录
        history_msgs = ChatMessage.objects.filter(session=session).order_by('-created_at')[:10]
        input_messages = []
        for msg in reversed(history_msgs):
            if msg.content == query and msg.role == 'user': continue
            if msg.role == 'user':
                input_messages.append(HumanMessage(content=msg.content))
            elif msg.role == 'assistant':
                input_messages.append(AIMessage(content=msg.content))

        input_messages.append(HumanMessage(content=query))

        related_memories = ""
        # 只有登录用户才有记忆
        if session.user:
            try:
                # 1. 把当前问题向量化
                q_vec = get_embedding(query)
                # 2. 在该用户的记忆库里搜 Top 3
                mems = UserMemory.objects.filter(user=session.user) \
                           .annotate(distance=CosineDistance('embedding', q_vec)) \
                           .order_by('distance')[:8]

                if mems:
                    related_memories = "\n".join([f"- {m.content}" for m in mems])
                    print(f"🧠 [Recall] 唤醒记忆:\n{related_memories}")
            except Exception as e:
                print(f"❌ [Recall] 记忆检索失败: {e}")



        # 4. 初始化 Agent
        agent_graph = create_nexus_agent(memories=related_memories)

        # 5. 定义流式生成器
        def stream_generator():
            yield json.dumps({"type": "meta", "session_id": str(session.id)}, ensure_ascii=False) + "\n"

            final_answer = ""

            print(f"🚀 [Agent] 开始思考: {query}")

            try:
                # 使用 stream_mode="updates"
                for event in agent_graph.stream({"messages": input_messages}, stream_mode="updates"):

                    # 遍历每一个节点的状态更新
                    for node_name, node_state in event.items():
                        print(f"🔄 [Graph Node] 执行节点: {node_name}")

                        # node_state['messages'] 可能是一条或多条消息
                        messages = node_state.get("messages", [])
                        # 强制转为列表处理，防止遗漏
                        if not isinstance(messages, list):
                            messages = [messages]

                        for message in messages:
                            # --- 逻辑 A: Agent 决定 (LLM) ---
                            if node_name == "agent" or node_name == "model":
                                # 1. 检查是否有工具调用
                                if hasattr(message, 'tool_calls') and message.tool_calls:
                                    for tool_call in message.tool_calls:
                                        print(f"🛠️ [Tool Call] {tool_call['name']}")
                                        yield json.dumps({
                                            "type": "status",
                                            "content": f"正在调用工具: {tool_call['name']}..."
                                        }, ensure_ascii=False) + "\n"

                                # 2. 检查是否有文本内容 (最终回答)
                                # 注意：有些模型会同时返回 tool_calls 和 content(思考过程)，这里我们优先展示 content
                                if message.content:
                                    print(f"📝 [Answer] {message.content[:50]}...")
                                    final_answer += message.content
                                    yield json.dumps({
                                        "type": "content",
                                        "chunk": message.content
                                    }, ensure_ascii=False) + "\n"

                            # --- 逻辑 B: Tools 执行结果 ---
                            elif node_name == "tools":
                                # ToolMessage 代表工具运行完了
                                if isinstance(message, ToolMessage):
                                    print(f"✅ [Tool Result] {message.name} 完成")
                                    yield json.dumps({
                                        "type": "status",
                                        "content": f"工具 {message.name} 调用完成，正在分析..."
                                    }, ensure_ascii=False) + "\n"

            except Exception as e:
                print(f"❌ [Error] {str(e)}")
                yield json.dumps({"type": "error", "content": str(e)}, ensure_ascii=False) + "\n"
                return

            # 6. 保存回答
            if final_answer:
                msg_instance = ChatMessage.objects.create(session=session, role='assistant', content=final_answer)
                yield json.dumps({
                    "type": "final",
                    "msg_id": msg_instance.id
                }, ensure_ascii=False) + "\n"
            else:
                # 如果没有最终回答 (极其罕见)，发一个兜底消息
                yield json.dumps({"type": "content", "chunk": "（Agent 未返回文本结果）"}, ensure_ascii=False) + "\n"



            if history_msgs.count() < 2:
                session.title = query[:20]
                session.save()

            # --- 🔥🔥🔥触发记忆提取并保存 (Consolidation) 🔥🔥🔥 ---
            # 只有登录用户才提取
            if session.user:
                # 异步触发，不卡顿响应
                extract_user_memory_task.delay(session.id)


        return StreamingHttpResponse(stream_generator(), content_type='application/x-ndjson')



class UserMeView(APIView):
    """获取当前登录用户信息"""
    # 只要 Token 有效，request.user 就是当前用户
    def get(self, request):
        return Response({
            "id": request.user.id,
            "username": request.user.username,
            "email": request.user.email,
            "is_staff": request.user.is_staff
        })


class MessageFeedbackView(APIView):
    """
    提交消息反馈
    PATCH /api/messages/<int:pk>/feedback/
    """

    def patch(self, request, pk):
        try:
            # 校验权限：只能评自己的消息，或者管理员可以评
            msg = ChatMessage.objects.get(pk=pk)

            # 简单的权限检查：当前用户必须是该会话的所有者
            if msg.session.user != request.user:
                return Response({"error": "无权操作"}, status=403)

            rating = request.data.get('rating')
            comment = request.data.get('comment', '')

            if rating is not None:
                msg.rating = int(rating)
            if comment:
                msg.feedback_comment = comment

            msg.save()
            return Response({"message": "反馈已记录"}, status=200)

        except ChatMessage.DoesNotExist:
            return Response({"error": "消息不存在"}, status=404)
        except Exception as e:
            return Response({"error": str(e)}, status=500)




# ... (其他视图保持不变) ...

class AdminDashboardView(APIView):
    """
    管理员数据看板接口
    权限：仅限管理员 (IsAdminUser)
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        # 1. 核心指标卡
        total_users = User.objects.count()
        total_docs = Document.objects.count()
        # 统计总对话数（以消息条数衡量，或者以 Session 数衡量，这里用 Session）
        total_sessions = ChatSession.objects.count()

        # 计算今日新增 (可选优化，这里简单做)
        today = timezone.now().date()
        new_users = User.objects.filter(date_joined__date=today).count()
        new_docs = Document.objects.filter(created_at__date=today).count()

        # 2. 差评反馈列表 (Rating = -1)
        # 只取最近 20 条，按时间倒序
        bad_feedbacks_qs = ChatMessage.objects.filter(rating=-1) \
                               .select_related('session__user') \
                               .order_by('-created_at')[:20]

        bad_feedbacks = []
        for msg in bad_feedbacks_qs:
            bad_feedbacks.append({
                "user": msg.session.user.username if msg.session.user else "Guest",
                "query": msg.session.messages.filter(role='user', id__lt=msg.id).last().content[
                         :20] + "..." if msg.session.messages.filter(role='user',
                                                                     id__lt=msg.id).exists() else "未知问题",
                "answer": msg.content[:30] + "...",
                "comment": msg.feedback_comment or "无备注",
                "time": msg.created_at.strftime("%Y-%m-%d %H:%M")
            })

        # 3. 调用量趋势 (最近 7 天的消息量)
        last_7_days = timezone.now() - timedelta(days=7)
        # 按天分组统计
        trend_data = ChatMessage.objects.filter(created_at__gte=last_7_days,role="user") \
            .annotate(date=TruncDate('created_at')) \
            .values('date') \
            .annotate(count=Count('id')) \
            .order_by('date')

        # 格式化给前端
        chart_data = {
            # 转换 date 对象为字符串
            item['date'].strftime("%m-%d"): item['count']
            for item in trend_data
        }

        return Response({
            "metrics": {
                "users": {"total": total_users, "new": new_users},
                "docs": {"total": total_docs, "new": new_docs},
                "sessions": {"total": total_sessions},
            },
            "bad_feedbacks": bad_feedbacks,
            "chart_data": chart_data
        })