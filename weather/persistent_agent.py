import json
import os

from dotenv import load_dotenv
from anthropic import Anthropic


load_dotenv()
client=Anthropic()

MEMORY_FILE="/Users/yuvaltav/PycharmProjects/weather/weather/agent_memory.json"
SYSTEM_PROMPT="you are a helpful assistant"

MAX_ITERATIONS=10

tools=[{
        "name": "check_calendar",
        "description": "Get the calendar for specific day.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "date'"
                }
            },
            "required": ["date"]
        }
    },
    {
        "name": "save_preferences",
        "description": "save user preferences.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "key'"
                },
                "value": { "type": "string",
                            "description": "value'"}
            },
            "required": ["key", "value"]
        }
    }
]

def load_memory():
    if not os.path.exists(MEMORY_FILE):
        return {}
    with open(MEMORY_FILE) as f:
        if os.path.getsize(MEMORY_FILE) == 0:
            print("File is empty")
            return {}
        return json.load(f)

def save_memory(data):
    with open(MEMORY_FILE, "w") as f:
        json.dump(data,f,indent=2)

def check_calendar(date):
    return f"Standup 9am , Review 2pm"


def save_preferences(key,value):
    memory=load_memory()
    memory[key]=value
    save_memory(memory)
    return f"Saved key {key} value {value}"

def agent_persist(args):
    memory=load_memory()

    if memory:
        system_prompt=f"""you are helpful assistant
                        know user preference {json.dumps(memory)}"""
    else:
        system_prompt="you are helpful assistant"

    messages=[{"role":"user","content":args}]
    for i in range(MAX_ITERATIONS):
        try:
            response=client.messages.create(model="claude-opus-4-8",
                                        system=system_prompt,
                                        max_tokens=1024,
                                        tools=tools,
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
                            if content.name == "check_calendar":
                                result=check_calendar(**args)
                            if content.name == "save_preferences":
                                result=save_preferences(args["key"],args["value"])

                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": content.id,
                                "content": result if isinstance(result, str) else json.dumps(result)
                        })
                    except Exception as e:
                        result = f"Error: {e}"
                if len(tool_results) > 0:
                    messages.append({"role": "user", "content": tool_results})
            elif response.stop_reason == "end_turn":
                return response.content[0].text
        except Exception as e:
            result = f"Tool Error: (e)"

if __name__ == "__main__":
    response=agent_persist("""schedule a lunch meeting for me this week""")
    print(response)