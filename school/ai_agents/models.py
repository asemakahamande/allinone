from django.db import models
from django.contrib.auth.models import User

class ChatConversation(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="chat_conversations")
    title = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - {self.title or 'Conversation ' + str(self.id)}"

class ChatMessage(models.Model):
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
        ('system', 'System'),
        ('tool', 'Tool'),
    ]

    conversation = models.ForeignKey(ChatConversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # For tool calls
    tool_name = models.CharField(max_length=255, blank=True, null=True)
    tool_call_id = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"{self.role} message in {self.conversation}"
