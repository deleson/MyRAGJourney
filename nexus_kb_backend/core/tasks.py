import os
from celery import shared_task
from django.conf import settings
from .models import Document, DocumentChunk

# LangChain 组件
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_community.document_loaders import TextLoader, PyPDFLoader, Docx2txtLoader
from langchain_huggingface import HuggingFaceEmbeddings

# 🔥🔥🔥 新增导入：用于摘要生成 🔥🔥🔥
from .utils import get_llm
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser


from .models import ChatSession, UserMemory  # 导入新模型
from .utils import get_embedding  # 导入向量化函数




# 配置模型路径
MODEL_PATH = os.path.join(settings.BASE_DIR, "local_models", "AI-ModelScope", "bge-small-zh-v1___5")


@shared_task
def process_document_task(doc_id,auto_activate=True):
    """
    后台任务：多格式文档处理 + 自动摘要
    """
    print(f"🔥 [Celery] 开始处理文档 ID: {doc_id}")

    try:
        doc = Document.objects.get(id=doc_id)
        doc.status = 'processing'
        doc.save()

        file_path = doc.file.path
        file_ext = os.path.splitext(file_path)[1].lower()
        print(f"📂 加载文件: {file_path} (类型: {file_ext})")

        final_splits = []
        raw_text_for_summary = ""  # 用于生成摘要的原材料

        # === 分支 A: Markdown 文件 ===
        if file_ext == '.md':
            with open(file_path, encoding='utf-8') as f:
                text = f.read()

            # Markdown 特有处理
            raw_text_for_summary = text  # MD 直接有全文，存起来

            headers_to_split_on = [
                ("#", "Header 1"), ("##", "Header 2"), ("###", "Header 3"),
                ("####", "Header 4"), ("#####", "Header 5"), ("######", "Header 6"),
            ]
            md_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on, strip_headers=False)
            md_splits = md_splitter.split_text(text)

            text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
            final_splits = text_splitter.split_documents(md_splits)

        # === 分支 B: PDF 文件 ===
        elif file_ext == '.pdf':
            loader = PyPDFLoader(file_path)
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
            final_splits = loader.load_and_split(text_splitter)

        # === 分支 C: Word 文件 (.docx) ===
        elif file_ext == '.docx':
            loader = Docx2txtLoader(file_path)
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
            final_splits = loader.load_and_split(text_splitter)

        # === 分支 D: 纯文本 (.txt) ===
        elif file_ext == '.txt':
            loader = TextLoader(file_path, encoding='utf-8')
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
            final_splits = loader.load_and_split(text_splitter)

        else:
            raise ValueError(f"不支持的文件格式: {file_ext}")

        print(f"✂️ 切分完成，共 {len(final_splits)} 个片段")


        # === 🔥🔥🔥 优化版：生成摘要逻辑 (首尾拼接) 🔥🔥🔥 ===
        print("📝 正在生成文档摘要...")
        try:
            # 1. 准备摘要素材 (raw_text_for_summary)
            if not raw_text_for_summary:
                # 针对 PDF/Word：如果没有全文，我们就拼凑切片
                # 策略：如果切片少，拼全部；如果切片多，取【前15个】和【后15个】
                if len(final_splits) <= 30:
                    raw_text_for_summary = "\n".join([c.page_content for c in final_splits])
                else:
                    head_part = "\n".join([c.page_content for c in final_splits[:15]])
                    tail_part = "\n".join([c.page_content for c in final_splits[-15:]])
                    raw_text_for_summary = f"{head_part}\n\n......\n\n{tail_part}"

            # 2. 字符级截断 (双重保险：防止 Markdown 全文太长)
            # 目标：总共 8000 字
            limit = 8000
            if len(raw_text_for_summary) > limit:
                half = limit // 2
                # 取前 4000 + 后 4000
                summary_content = raw_text_for_summary[:half] + "\n\n...[中间内容已省略]...\n\n" + raw_text_for_summary[
                                                                                                   -half:]
            else:
                summary_content = raw_text_for_summary

            # 3. 调用 LLM 生成
            summary_template = """你是一个专业的文档助手。请阅读以下文档片段（包含开头和结尾），生成一份精简的摘要（200字以内），重点概括其核心内容和结论。

        文档片段：
        {content}
        """
            prompt = ChatPromptTemplate.from_template(summary_template)
            llm = get_llm()
            chain = prompt | llm | StrOutputParser()

            summary = chain.invoke({"content": summary_content})

            # 4. 保存
            doc.summary = summary
            doc.save(update_fields=['summary'])
            print(f"✅ 摘要生成完毕 (基于首尾拼接): {summary[:30]}...")

        except Exception as e:
            print(f"⚠️ 摘要生成失败 (跳过): {e}")
        # === 🔥🔥🔥 摘要逻辑结束 🔥🔥🔥 ===

        # --- 数据清洗与注入 (Breadcrumbs / Page Numbers) ---
        processed_texts_for_embedding = []
        chunks_to_create = []

        for i, split in enumerate(final_splits):
            raw_metadata = split.metadata
            page_content = split.page_content

            # 1. 构建注入文本 (给 AI 看的上下文)
            if 'Header 1' in raw_metadata:
                header_values = raw_metadata.values()
                header_context = " > ".join(str(v) for v in header_values)
                injected_content = f"【章节: {header_context}】\n{page_content}"
            elif 'page' in raw_metadata:
                page_num = raw_metadata['page'] + 1
                injected_content = f"【第 {page_num} 页】\n{page_content}"
                raw_metadata['page_label'] = f"第 {page_num} 页"
            else:
                injected_content = page_content

            processed_texts_for_embedding.append(injected_content)

            # 2. 准备数据库对象
            chunk = DocumentChunk(
                document=doc,
                chunk_index=i,
                content=injected_content,  # 存注入后的文本
                meta_info=raw_metadata,  # 存原始元数据
            )
            chunks_to_create.append(chunk)

        # 4. 向量化
        print(f"🧠 加载模型: {MODEL_PATH}")
        embedding_model = HuggingFaceEmbeddings(model_name=MODEL_PATH)
        embeddings = embedding_model.embed_documents(processed_texts_for_embedding)

        # 5. 保存
        for i, chunk in enumerate(chunks_to_create):
            chunk.embedding = embeddings[i]

        DocumentChunk.objects.bulk_create(chunks_to_create)

        final_status = 'active' if auto_activate else 'reviewing'

        doc.status = 'completed'
        doc.status = final_status
        doc.save()
        print(f"✅ 文档处理完成！")

    except Exception as e:
        print(f"❌ 处理失败: {e}")
        doc.status = 'failed'
        doc.error_message = str(e)
        doc.save()


@shared_task
def extract_user_memory_task(session_id):
    """
    记忆提取任务：分析会话，提取用户特征存入 UserMemory
    """
    print(f"🧠 [Memory] 开始分析会话: {session_id}")

    try:
        session = ChatSession.objects.get(id=session_id)
        # 获取最近的对话 (例如最近 4 条，包含 User 和 AI 的交互)
        # 我们只关心 User 说的话，但 AI 的回复有助于理解上下文
        messages = session.messages.order_by('-created_at')[:4]
        if not messages: return

        # 拼接对话文本
        conversation_text = ""
        for msg in reversed(messages):
            conversation_text += f"{msg.role}: {msg.content}\n"

        # --- 1. 使用 LLM 提取事实 ---
        extract_prompt = """你是一个专业的记忆助理。请分析下面的对话，提取关于"User"的关键个人信息、偏好、职业背景或具体需求。

规则：
1. 只提取**长期有效**的信息（如"用户是程序员"），忽略临时指令（如"帮我搜一下天气"）。
2. 如果没有有价值的信息，返回 "无"。
3. 如果有，请用简练的陈述句输出，每条一行。

对话内容：
{text}
"""
        prompt = ChatPromptTemplate.from_template(extract_prompt)
        llm = get_llm()
        chain = prompt | llm | StrOutputParser()

        result = chain.invoke({"text": conversation_text})

        if "无" in result or not result.strip():
            print("🧠 [Memory] 未发现新记忆")
            return

        # --- 2. 存入数据库 ---
        facts = [f.strip() for f in result.split('\n') if f.strip()]

        # 这里的 session.user 可能为空（如果是旧数据），做个防呆
        if not session.user:
            return

        for fact in facts:
            # 查重 (简单查重：如果内容完全一样就不存了)
            # 进阶查重可以用向量相似度，这里先做简单的
            if UserMemory.objects.filter(user=session.user, content=fact).exists():
                continue

            # 向量化
            emb = get_embedding(fact)

            UserMemory.objects.create(
                user=session.user,
                content=fact,
                embedding=emb
            )
            print(f"✅ [Memory] 新增记忆: {fact}")

    except Exception as e:
        print(f"❌ [Memory] 提取失败: {e}")