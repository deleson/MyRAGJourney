# download_model.py
from modelscope import snapshot_download
import os

print("🚀 正在通过阿里魔搭下载 BGE-Reranker 模型...")
print("   (目标: Xorbits/bge-reranker-base)")

save_dir = os.path.join(os.getcwd(), "nexus_kb_backend", "local_models")

# 下载 Embedding 模型 (如果之前没下过，防呆)
model_dir2 = snapshot_download('AI-ModelScope/bge-small-zh-v1.5', cache_dir=save_dir)

# 🔥 下载 Reranker 模型 🔥
model_dir = snapshot_download(
    'Xorbits/bge-reranker-base',
    cache_dir=save_dir
)

print(f"\n✅ 下载完成！")
print(f"📂 模型保存在: {model_dir} 和 {model_dir2}")