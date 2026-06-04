"""所有 Agent 的共用框架。

設計重點：
- get_llm() 是「唯一」決定要用哪個 LLM 的地方。之後要從 OpenAI 換成本地模型，
  只需要改這一個函數，其他 Agent 完全不用動。
- create_agent() 用 LangGraph 的 create_react_agent 建立 Agent，回傳的本身就是
  一個 LangGraph graph，所以日後可以直接接進更大的 LangGraph 流程。
- 透過 MemorySaver checkpointer 提供對話記憶（呼叫時帶 thread_id 即可分辨對話）。
"""

import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

load_dotenv()


def get_llm():
    """建立並回傳 LLM 實例。

    *** 換模型只需改這裡 ***
    例如要換成本地的 Ollama 模型：
        from langchain_ollama import ChatOllama
        return ChatOllama(model="llama3.1", temperature=0)
    其餘 Agent 程式碼都不需要更動。
    """
    return ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        api_key=os.getenv("OPENAI_API_KEY"),
        temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
    )


def create_agent(tools, system_prompt, with_memory=True):
    """所有 Agent 的統一建立入口。

    Args:
        tools: 這個 Agent 可以使用的工具清單（list）。
        system_prompt: 系統提示詞，定義 Agent 的角色與行為。
        with_memory: 是否讓這個 Agent 自帶對話記憶。
            - True（預設）：單獨使用時帶記憶。每個 Agent 各自擁有一個
              MemorySaver，彼此隔離；同一個 Agent 用 thread_id 區隔不同對話。
            - False：要把這個 Agent 當成節點接進更大的 LangGraph 流程時用，
              記憶交由「父層流程」統一管理，避免兩層 checkpointer 互相打架。

    Returns:
        一個可直接 invoke、也可接入 LangGraph 的 agent graph。
    """
    return create_react_agent(
        model=get_llm(),
        tools=tools,
        prompt=system_prompt,
        checkpointer=MemorySaver() if with_memory else None,
    )
