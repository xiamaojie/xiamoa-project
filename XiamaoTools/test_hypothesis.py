from hypothesis import given
from hypothesis import strategies as st


# 被测试函数
def add(a, b):
    print(a)
    return a + b


# 定义测试
@given(st.integers(), st.integers())
def test_add(a, b):
    result = add(a, b)
    print(result)
    assert result == a + b


# 运行测试
test_add()