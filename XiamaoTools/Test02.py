"""
所谓回文数，就是说一个数字从左边读和从右边读的结果是一模一样的，比如12321，131，1221。
写出一个程序找出给定数字范围内的回文数，比如输入10000，即找出0～10000之内的回文数。"""


# def is_palindrome(number):
#     var = str(number)[::-1]
#     # var = "".join(reversed(str(number)))
#     if number == int(var):
#         return True
#     else:
#         return False
#
# def find_palindrome_number(number):
#     palindrome_list = []
#     for i in range(number):
#         if is_palindrome(i):
#             palindrome_list.append(i)
#     print(palindrome_list)
# if __name__ == '__main__':
#     find_palindrome_number(10000)


from openai import OpenAI

client = OpenAI()

response = client.chat.completions.create(
    model="gpt-3.5-turbo",  # 或 "gpt-4"、"gpt-4o" 等
    messages=[
        {"role": "user", "content": "Write a short bedtime story about a unicorn."}
    ]
)

print(response.choices[0].message.content)
