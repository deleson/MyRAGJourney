import os
from django.conf import settings
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_openai import ChatOpenAI
from sentence_transformers import CrossEncoder # <--- 新增：用于重排序

# --- 1. Embedding 模型路径 ---
EMBED_MODEL_PATH = os.path.join(settings.BASE_DIR, "local_models", "AI-ModelScope", "bge-small-zh-v1___5")

# --- 2. Reranker 模型路径 (自动适配下载后的文件夹名) ---
# 注意：ModelScope 下载后文件夹名可能是 Xorbits/bge-reranker-base 或其他，请去文件夹确认一下
# 这里假设是 Xorbits/bge-reranker-base
RERANK_MODEL_PATH = os.path.join(settings.BASE_DIR, "local_models", "Xorbits", "bge-reranker-base")

# --- 3. 全局预加载 ---
print(f"⏳ [Init] 正在加载 Embedding 模型...")
embedding_model = HuggingFaceEmbeddings(model_name=EMBED_MODEL_PATH)

print(f"⏳ [Init] 正在加载 Reranker 模型...")
# CrossEncoder 是专门做重排序的
reranker_model = CrossEncoder(RERANK_MODEL_PATH, max_length=512)

print("✅ [Init] 模型加载完毕")

def get_embedding(text):
    return embedding_model.embed_query(text)

def get_reranker():
    return reranker_model

def get_llm():
    return ChatOpenAI(
        model="deepseek-chat",
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com",
        temperature=0.3
    )