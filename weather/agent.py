import json
import sys

from dotenv import load_dotenv
from anthropic import Anthropic

from tools import TOOLS,execute_tool

load_dotenv()
client= Anthropic()

MAX_ITERATIONS=10;
SYSTEM_PROMPT="You are a helpful assistant"

def run_agent(user_message,history=None):
    messages=[]
    if history:messages.extend(history)
    messages.append({"role":"user","content":user_message})

    for _ in range(MAX_ITERATIONS):
        response=client.messages.create(model="claude-opus-4-8",
                                        system=SYSTEM_PROMPT,
                                        max_tokens=1024,
                                        tools=TOOLS,
                                        messages=messages)
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason == "tool_use":
            tool_results = []
            for content in response.content:
                try:

                    if content.type == "text":
                        print(content.text)
                    if content.type == "tool_use":
                        args = content.input
                        result=execute_tool(content.name,args)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": content.id,
                            "content": result if isinstance(result, str) else json.dumps(result)
                        })
                except Exception as e:
                    result=f"Error: {e}"
            if len(tool_results)>0:
                messages.append({"role": "user", "content": tool_results})
        elif response.stop_reason == "end_turn":
            return response.content[0].text


if __name__ == "__main__":
    response=run_agent("""Find info on AI agents
                 and check if i'm free after 2pm""")
    print(response)
