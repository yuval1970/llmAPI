import json
from typing import final

from dotenv import load_dotenv
from anthropic import Anthropic


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
                }
            },
            "required": ["day"]
        }
    },
{
        "name": "send_email",
        "description": "send email.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "to"
                },
                "subject": {
                    "type": "string",
                    "description": "subject"
                },
                "body": {
                    "type": "string",
                    "description": "body"
                }
            },
            "required": ["to, subject", "body"]
        }
    },
{
        "name": "search_contacts",
        "description": "search contacts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "name"
                }
            },
            "required": ["name"]
        }
    }
]

def check_calendar(day):
    events={"monday":"Standup 9am",
            "thursday":"1pm lunch,9pm review"}
    return events.get(day.lower(),"no events")

def check_input(message):
    blocked=["medical","legal","financial advice"]

    for term in blocked:
        if term in message.lower():
            return "i can only help with scheduling and contacts"
    return None

def send_email(to,subject,body):
    return f"email send to {to}"
contacts_list=[
    {
        "name": "Sarah",
        "email": "sarah@sarh.com"
    },
    {"name": "stam", "email": "stam@stam.com"}
]
def search_contacts(name):
    for contact in contacts_list:
        if name==contact["name"]:
            return contact
    return None

def flaky_tool():
    raise Exception("Service Unavailable")

def execute_tool(name,args):
    try :
        if name=="check_calendar":
            return check_calendar(args["day"])
        elif name=="send_email":
            return send_email(**args)
        elif name=="search_contacts":
            return search_contacts(args["name"])
        else:
            return "Unknown tool"
    except Exception as e:
        return f"""FError : {str(e)}.
                    "Try a different approach"""


message= "email Sarah my calendar for thursday"
messages=[{"role":"user",
           "content":message}]
SYSTEM_PROMPT = """You are a scheduling assistance. use the React pattern.
                    Thought: reason about what do next.
                    Action: call tool if needed.
                    Always end your final response with a 
                    JSON summary block:
                    {"summary":"...",
                     "actions_taken":"..."}"""
MAX_ITERATIONS=10

guard_result=check_input(message)
if guard_result:
    print("guard result") ## no API call
else:
    for iter in range(MAX_ITERATIONS):
        print("iteration ",iter)
        response=client.messages.create(model="claude-opus-4-8",
                                        system=SYSTEM_PROMPT,
                                        max_tokens=1024,
                                        tools=tools,
                                        messages=messages)
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason=="end_turn":
            print(response.content[0].text)
            stop_reason="end_turn"
            break
        if response.stop_reason=="tool_use":
            tool_results =[]
            for content in response.content:
                if content.type=="text":
                    print(content.text)
                if content.type == "tool_use":
                    args=content.input

                    if content.name=="check_calendar":
                        print(args)
                        result=execute_tool(content.name,args["day"])

                    if content.name=="send_email":
                        print(f"prepared eMail {args}")
                        confirm=input("send the email (y/n)?")
                        if confirm.lower()!="y":
                            print("email cancelled by user")
                        else:
                            result=execute_tool(content.name,**args)
                    if content.name == "search_contacts":
                        result = execute_tool(content.name, args["name"])
                    if content.name == "flaky_tool":
                        result = execute_tool(content.name, **args)

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": content.id,
                        "content":  result if isinstance(result, str) else json.dumps(result)
                    })
                    #messages.append({"role": "user", "content": tool_results})
            messages.append({"role": "user", "content": tool_results})
    if stop_reason!="end_turn":
        messages.append({"role": "user", "content": "You've reached the maximum number of iterations! , give your best answer")
        final=client.messages.create(model="claude-opus-4-8",
                                        system=SYSTEM_PROMPT,
                                        max_tokens=1024,
                                        tools=tools,
                                        messages=messages)
        print(final.content)

