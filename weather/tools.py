TOOLS=[{
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
        "name": "search_web",
        "description": "search the web",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "query"
                }
            },
            "required": ["query"]
        }
    },
{
        "name": "get_user_preferences",
        "description": "get user preferences",

        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "category"
                }
            },
            "required": ["category"]
        }
    }]
def check_calendar(date):
    return "10am : Standup , 2pm: Dentist"

def search_web(query):
    return f"Top results for {query}"

def get_user_preferences(category):
    return f"Preferences for  {category} - None"

def execute_tool(name,args):
    if name == "check_calendar":
        return check_calendar(args["date"])
    elif name == "search_web":
        return search_web(args["query"])
    elif name == "get_user_preferences":
        return get_user_preferences(args["category"])
    else:
        return "Tool Does not exists"