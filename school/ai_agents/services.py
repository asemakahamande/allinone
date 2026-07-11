import os
import json
import logging
from pypdf import PdfReader
try:
    import docx
except ImportError:
    docx = None
try:
    from langchain_anthropic import ChatAnthropic
    from langchain_core.messages import SystemMessage, HumanMessage
    _LANGCHAIN_AVAILABLE = True
except ImportError:
    _LANGCHAIN_AVAILABLE = False
    ChatAnthropic = None
    SystemMessage = None
    HumanMessage = None
from .tools import TOOLS_MAP

def get_llm():
    if not _LANGCHAIN_AVAILABLE:
        return None
    return ChatAnthropic(
        model_name="claude-3-haiku-20240307", 
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "dummy-key-for-now"),
        temperature=0.7
    )

def get_system_prompt_for_role(role, context_data=None):
    context_data = context_data or {}
    base_identity = "Your name is Avese, a female AI assistant. "
    
    if role == 'student':
        return base_identity + "You are a friendly, encouraging academic tutor for a student. You explain concepts clearly without giving direct answers to exam questions. Your main goal is to help them in their learning processes."
    elif role == 'teacher':
        return base_identity + "You are a helpful teaching assistant. You assist class and subject teachers with grading, brainstorming lesson plans, and writing report card comments. You have tools to check class performance."
    elif role == 'admin':
        return base_identity + "You are a professional school operations manager. You assist the administrative team with school data, drafting emails, and summarizing statistics. You can generate and fetch report card PDFs using your tools."
    elif role == 'parent':
        student_name = context_data.get('student_name', 'your child')
        school_name = context_data.get('school_name', 'the school')
        return base_identity + f"You are a friendly parent liaison for {school_name}. You help parents understand their child ({student_name})'s academic progress, give advice on studying at home, and explain school policies. Under no circumstances should you provide data about any student other than {student_name}."
    return base_identity + "You are a helpful assistant for the school."

def process_chat_message(user, role, message, history=None, context_data=None, extracted_text=None):
    """
    Process a chat message using LangChain and Claude.
    """
    if not _LANGCHAIN_AVAILABLE:
        return "AI chat is currently unavailable (langchain_anthropic not installed)."
    
    llm = get_llm()
    system_prompt = get_system_prompt_for_role(role, context_data)
    
    # LangChain Agent setup
    from langchain.agents import AgentExecutor, create_tool_calling_agent
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
    
    # Define role-based tool access
    ALLOWED_TOOLS = {
        'admin': list(TOOLS_MAP.keys()),  # Admin gets all tools
        'teacher': [
            'get_class_performance', 
            'get_class_view_tool', 
            'get_student_analytics_tool', 
            'get_my_results',
            'get_student_report_cards_pdf',
            'mark_attendance_tool',
            'pull_attendance_tool',
            'create_cbt_exam_tool',
            'add_cbt_question_tool',
            'send_report_to_parent_tool',
            'check_assignment_submissions_tool',
            'check_and_send_assignment_deadline_reminders_tool',
            'get_assignment_submission_answers_tool',
            'grade_assignment_submission_tool'
        ],
        'student': [], # Purely conversational for learning processes
        'parent': [] # Purely conversational for parent guidance
    }
    
    # Get allowed tool names for this role, default to empty
    allowed_tool_names = ALLOWED_TOOLS.get(role, [])
    
    # We load our actual tools from the map, filtering by allowed tools
    tool_list = [TOOLS_MAP[name] for name in allowed_tool_names if name in TOOLS_MAP]
    
    final_input = message
    if extracted_text:
        final_input = f"{message}\n\n[User attached file content for reference]:\n{extracted_text}"
        
    # If a role has no tools, we just use the LLM directly
    if not tool_list:
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=final_input)
        ]
        try:
            response = llm.invoke(messages)
            return response.content
        except Exception as e:
            import traceback
            traceback.print_exc()
            return f"I'm sorry, I encountered an error: {str(e)}"
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="chat_history", optional=True),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])
    
    school_id = context_data.get('school_id') if context_data else None
    
    if not school_id and tool_list:
        return "Security Error: Missing school context. Cannot execute tools."
        
    from .tools import set_agent_context
    if school_id:
        set_agent_context(school_id)
        system_prompt += f"\n\nCRITICAL: You are operating in School ID: {school_id}. You MUST pass school_id={school_id} to any tool that requires it. Never use a different school ID."
        # Recreate prompt with updated system prompt
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])
        
    try:
        agent = create_tool_calling_agent(llm, tool_list, prompt)
        agent_executor = AgentExecutor(agent=agent, tools=tool_list, verbose=True)
        
        final_input = message
        if extracted_text:
            final_input = f"{message}\n\n[User attached file content for reference]:\n{extracted_text}"
            
        # Execute the agent
        response = agent_executor.invoke({
            "input": final_input,
            "chat_history": [] # Pass history here if available
        })
        
        return response.get("output", "I'm sorry, I couldn't formulate a response.")
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"I'm sorry, I encountered an error: {str(e)}"

def extract_text_from_file(file_path, page_from=None, page_to=None):
    """Extracts text from PDF or DOCX, optionally slicing by page range."""
    text = ""
    ext = os.path.splitext(file_path)[1].lower()
    
    if ext == '.pdf':
        try:
            reader = PdfReader(file_path)
            start = max(0, page_from - 1) if page_from else 0
            end = min(len(reader.pages), page_to) if page_to else len(reader.pages)
            for i in range(start, end):
                page_text = reader.pages[i].extract_text()
                if page_text:
                    text += page_text + "\n"
        except Exception as e:
            logging.error(f"Error reading PDF {file_path}: {e}")
            
    elif ext in ['.doc', '.docx']:
        if not docx:
            return "DOCX processing is not available."
        try:
            doc = docx.Document(file_path)
            for para in doc.paragraphs:
                text += para.text + "\n"
        except Exception as e:
            logging.error(f"Error reading DOCX {file_path}: {e}")
            
    return text

def summarize_material(text, subject_name="General"):
    if not _LANGCHAIN_AVAILABLE:
        return "AI summarization is currently unavailable."
    
    llm = get_llm()
    system_prompt = f"You are an expert AI teaching assistant for {subject_name}. Your task is to summarize the following study material clearly and comprehensively."
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Please provide a structured summary of the following material. Use Markdown headings and bullet points.\n\nMaterial:\n{text}")
    ]
    
    try:
        response = llm.invoke(messages)
        return response.content
    except Exception as e:
        return f"Error generating summary: {str(e)}"

def generate_questions_from_material(text, num_questions=10, question_type="mixed", subject_name="General"):
    if not _LANGCHAIN_AVAILABLE:
        return "AI question generation is currently unavailable."
    
    llm = get_llm()
    system_prompt = f"You are an expert AI teaching assistant for {subject_name}. Your task is to generate {num_questions} exam/quiz questions based ONLY on the provided material."
    
    if question_type == "mcq":
        type_instruction = "multiple-choice questions (with 4 options each)"
    elif question_type == "essay":
        type_instruction = "essay or short-answer questions"
    else:
        type_instruction = "a mix of multiple-choice and short-answer questions"
        
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Please generate {num_questions} {type_instruction} based on the following material. Provide the answers or grading rubrics at the end.\n\nMaterial:\n{text}")
    ]
    
    try:
        response = llm.invoke(messages)
        return response.content
    except Exception as e:
        return f"Error generating questions: {str(e)}"
