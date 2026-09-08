import openai
from fastapi import FastAPI
from openai import OpenAI


client = OpenAI()
app = FastAPI()

@app.post("/generate")
def generate(prompt : str):
    #response=ollama.chat(model="mistral",messages=[{"role":"user","content":prompt}])
    response = client.chat.completions.create(
        model="gpt-5.6-sol",
      #  response_format={"type": "json_object"},
        messages=[
            {"role": "user",
             "content": "Extract the names and ages of people mentioned into a JSON array: 'John is 34 and his sister Mary is 29.'"}
        ])

    return {"response":response["message"]["content"]}

