import os
from celery import Celery

# 设置默认的 Django 配置文件
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# 创建 Celery 实例
app = Celery('nexus_kb')

# 从 Django settings.py 中读取配置，所有以 CELERY_ 开头的配置项
app.config_from_object('django.conf:settings', namespace='CELERY')

# 自动发现所有已注册 App 下的 tasks.py
app.autodiscover_tasks()

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')