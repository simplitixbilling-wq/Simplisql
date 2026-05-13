"""
AI Module
---------
AI assistant functionality for SimplSQL.

Components:
- AIAssistantDialog: Main AI chat interface
- AI Providers: OpenAI, Anthropic, Gemini integrations
- Context Builder: Prepare context for AI queries
- Config Manager: AI configuration and history
"""

from .ai_assistant_new import AIAssistantDialog

__all__ = ['AIAssistantDialog']
