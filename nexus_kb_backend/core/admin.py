from django.contrib import admin
from .models import KnowledgeBase, Document, DocumentChunk,ChatMessage,ChatSession,UserMemory


@admin.register(KnowledgeBase)
class KnowledgeBaseAdmin(admin.ModelAdmin):
    list_display = ('id','name', 'created_at','user')


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ('id','name','uploaded_by','file', 'kb', 'status', 'created_at')
    list_filter = ('status', 'kb')


@admin.register(DocumentChunk)
class DocumentChunkAdmin(admin.ModelAdmin):
    list_display = ('document', 'chunk_index', 'short_content')

    def short_content(self, obj):
        return obj.content[:50] + "..."

@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ('id','user', 'title','session_type','created_at','updated_at')

@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('session','role', 'content','created_at')



@admin.register(UserMemory)
class UserMemoryAdmin(admin.ModelAdmin):
    list_display = ('user','content', 'embedding','created_at')