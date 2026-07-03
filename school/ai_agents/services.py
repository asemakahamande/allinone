import os
import json
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage
from .tools import TOOLS_MAP

def get_llm():
    return ChatAnthropic(
        model_name="claude-3-haiku-20240307", 
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "dummy-key-for-now"),
        temperature=0.7
    )

def get_system_prompt_for_role(role, context_data=None):
    context_data = context_data or {}
    base_identity = "Your name is Avese, a female AI assistant. "
    
    if role == 'student':
        return base_identity + "You are a friendly, encouraging academic tutor for a student. You explain concepts clearly without giving direct answers to exam questions. You have access to database tools to check their grades and attendance."
    elif role == 'teacher':
        return base_identity + "You are a helpful teaching assistant. You assist class and subject teachers with grading, brainstorming lesson plans, and writing report card comments. You have tools to check class performance."
    elif role == 'admin':
        return base_identity + "You are a professional school operations manager. You assist the administrative team with school data, drafting emails, and summarizing statistics. You can generate and fetch report card PDFs using your tools."
    elif role == 'parent':
        student_name = context_data.get('student_name', 'your child')
        school_name = context_data.get('school_name', 'the school')
        return base_identity + f"You are a friendly parent liaison for {school_name}. You help parents understand their child ({student_name})'s academic progress, give advice on studying at home, and explain school policies. Under no circumstances should you provide data about any student other than {student_name}."
    return base_identity + "You are a helpful assistant for the school."

def process_chat_message(user, role, message, history=None, context_data=None):
    """
    Process a chat message using LangChain and Claude.
    """
    llm = get_llm()
    system_prompt = get_system_prompt_for_role(role, context_data)
    
    messages = [SystemMessage(content=system_prompt)]
    if history:
        for msg in history:
            # Assuming history is a list of dicts: [{'role': 'user', 'content': 'hi'}]
            # In a real app, we'd map this to HumanMessage/AIMessage
            pass
            
    messages.append(HumanMessage(content=message))
    
    try:
        response = llm.invoke(messages)
        return response.content
    except Exception as e:
        return f"I'm sorry, I encountered an error: {str(e)}"
