from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()

client = Anthropic()

response = client.messages.create(
    model="claude-opus-4-8",
    max_tokens=1024,
    temperature=0.9,
    messages=[{"role": "user", "content": "what is ai"}],
)
print(response.content[0].text)