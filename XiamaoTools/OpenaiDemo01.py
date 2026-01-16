from openai import OpenAI
client = OpenAI()

response = client.chat.completions.create(
    model="gpt-5",  # 建议使用官方支持的模型名，如 gpt-3.5-turbo 或 gpt-4
    messages=[
        {"role": "user", "content": "写一个关于独角兽的睡前短篇故事."}
    ]
)

print(response.choices[0].message.content)
