from platform import system

from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()

client = Anthropic()

while (True):
    response= client.completions.create(model="claude-opus-4-8",
                                        system="you are helpfull assistant",
                                        max_tokens=1024,
                                        messages=[{"role": "user", "content": "what is ai"}]
    )
    finish_reason=response.stop_reason
    if (finish_reason == "stop"):
        print(response.text)
        break
    else:
        break