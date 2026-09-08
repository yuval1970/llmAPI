
from dotenv import load_dotenv
from anthropic import Anthropic
from matplotlib.font_manager import json_load

load_dotenv()

client = Anthropic()

SYSTEM_PROMPT = "you are a helpfull personal assistant. use your tools when you need real data."

tools = [{
    "type":"function",
    "function":"check_calendar",
    "parameters":{
        "type":"object",
        "properties":{
            "date":{"type":"string"}
        },
        "required":["date"]
    }
}]

def check_calendar(date):
    return "10pm:Standup,2pm:Dentist"

messages = [{"role": "user",
                    "content": "what is the weather"}]
while True:
    response =client.completions.create(model="claude-opus-4-8",
                                        system=SYSTEM_PROMPT,
                                        max_tokens=1024,
                                        messages,
                                        tools=tools)
    messages.append({
        "role": "assistant",
        "content": response.content  # the whole content array, not just the text
    })
    message= response.content[0].text
    finish_reason = response.stop_reason
    if finish_reason == "end_turn":
        print(response.text)
        break

    if finish_reason == "tool_use":
        for block in response.content:
            if block.type == "tool_use":
                tool_name = block.name
                tool_input = block.input
                tool_id = block.id
                args=json_load(block.input)
                # run your actual function here
                result = check_calendar(args)
                messages.append({
                    "role": "user",
                    "content": result
                })


