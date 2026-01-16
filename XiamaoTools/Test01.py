"""
所谓回文数，就是说一个数字从左边读和从右边读的结果是一模一样的，比如12321，131，1221。
写出一个程序找出给定数字范围内的回文数，比如输入10000，即找出0～10000之内的回文数。"""


# number = [1,3,2,6,5]
#
# def maopao_sort(list1):
#     for i in range(len(list1)):
#         for j in range(len(list1)):
#             if list1[i] < list1[j]:
#                 list1[i],list1[j] = list1[j],list1[i]
#     print(list1)
#
#
#
# maopao_sort(number)

def is_palindrome(num):
    """
    判断一个数字是否是回文数
    """
    num_str = str(num)
    print(num_str == num_str[::-1])
    return num_str == num_str[::-1]  # 判断字符串是否与其反转后的字符串相同


def find_palindromes_in_range(limit):
    """
    找出0到limit之间的所有回文数
    """
    palindromes = []
    for num in range(limit + 1):
        if is_palindrome(num):
            palindromes.append(num)
    return palindromes



# 输入上限
upper_limit = int(input("请输入上限值："))
# 找出回文数
palindromes = find_palindromes_in_range(upper_limit)

print(f"0到{upper_limit}之间的回文数有：")
print(palindromes)