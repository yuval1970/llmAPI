
from dotenv import load_dotenv
from anthropic import Anthropic
from matplotlib.font_manager import json_load

load_dotenv()
client= Anthropic()

tools = [
    {
        "name": "check_calendar",
        "description": "Get the calendar for specific day.",
        "input_schema": {
            "type": "object",
            "properties": {
                "day": {
                    "type": "string",
                    "description": "day'"
                },
                "unit": {
                    "type": "string",
                    "enum": ["sunday", "monday","tuesday","wednesday","thursday","friday","saturday"],
                    "description": "day to use"
                }
            },
            "required": ["day"]
        }
    }
]

def check_calendar(day):
    events={"monday":"Standup 9am",
            "thursday":"1pm lunch,9pm review"}
    return events.get(day.lower(),"no events")

messages=[{"role":"user",
           "content":"thursday plans? is 2pm free"}]
SYSTEM_PROMPT = ("you are a helpfull personal assistant. before every tool call,write 'Thoughts: [your reasoning]'.after every tool result , write 'Observation: [what you learned]' then decide your next step")

while True:
    response=client.messages.create(model="claude-opus-4-8",
                                        system=SYSTEM_PROMPT,
                                        max_tokens=1024,
                                        tools=tools,
                                        messages=messages)
    messages.append({"role": "assistant", "content": response.content})

    if response.stop_reason=="end_turn":
        print(response.content[0].text)
        break
    if response.stop_reason=="tool_use":
        tool_results =[]
        for content in response.content:
            if content.type=="text":
                print(content.text)
            if content.type == "tool_use":
                print(content.input.get("day"))
                result = check_calendar(content.input.get("day"))
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": content.id,
                    "content": result
                })
                messages.append({"role": "user", "content": tool_results})


