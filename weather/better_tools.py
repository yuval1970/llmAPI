from dotenv import load_dotenv
from anthropic import Anthropic


load_dotenv()
client=Anthropic()

SYSTEM_PROMPT="you are a helpful assistant"

tools=[{
        "name": "search",
        "description": "searches things",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "query'"
                }
            },
            "required": ["query"]
        }
    },{
    "name": "get_info",
"description": "Gets infromation",
"input_schema": {
    "type": "object",
    "properties": {
        "topic": {
            "type": "string",
            "description": "topic'"
        }
    },
    "required": ["topic"]
}
}
]

def get_info(topic):
    return f"this is the topic {topic}"

def search(query):
    return f"search {query}"

def execute_tool(name,args):
    if name == "get_info":
        return get_info(args)
    elif name == "search":
        return search(args)
    else:
        return f"no such tool {name}"

messages = [{"role":"user","content":"search for me something"}]
while True:
    response=client.messages.create(model="claude-opus-4-8",
                                            system=SYSTEM_PROMPT,
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
                    result = execute_tool(content.name, args)
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
        print(response.content[0].text)
