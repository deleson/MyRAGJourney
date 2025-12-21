from rest_framework import serializers
from .models import KnowledgeBase, Document
from .models import ChatSession, ChatMessage
from django.contrib.auth.models import User

class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['username', 'password', 'email']

    def create(self, validated_data):
        # 使用 create_user 来正确加密密码
        user = User.objects.create_user(
            username=validated_data['username'],
            password=validated_data['password'],
            email=validated_data.get('email', '')
        )
        return user



class KnowledgeBaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeBase
        fields = ['id', 'name', 'description']

class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = ['id','name','file', 'status', 'created_at']




class ChatMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = ['id','role', 'content', 'sources', 'created_at','rating', 'feedback_comment']

class ChatSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatSession
        fields = ['id', 'title', 'updated_at']