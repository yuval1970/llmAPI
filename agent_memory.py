import os,json

from dotenv import load_dotenv
from anthropic import Anthropic

from tools import tools,execute_tool
from openai import OpenAI
load_dotenv()

client = Anthropic()

SYSTEM_PROMPT = "you are a helpfull personal assistant. use your tools when you need real data."

questions = ["what is on my calendar today?",
             "Tell me about the standup",
             "what time is my dentist?",
             "am i free at 3pm",
             "Summarize my day"]

for q in questions:
    messages.