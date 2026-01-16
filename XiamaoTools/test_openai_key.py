#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenAI API密钥可用性测试脚本 - 最终修复版
功能：验证API密钥设置和连接状态
版本：完全兼容OpenAI Python库 1.61.1
日期：2025-09-22（最终版）
"""

import os
import sys
import time
from datetime import datetime
from pathlib import Path

# .env 文件支持（可选）
try:
    from dotenv import load_dotenv

    load_dotenv()
    ENV_LOADED = True
except ImportError:
    ENV_LOADED = False

# 全局导入 OpenAI 相关模块
try:
    import openai
    from openai import OpenAI

    OPENAI_AVAILABLE = True
    print(f"✓ OpenAI库全局导入成功，版本：{openai.__version__}")
except ImportError as e:
    OPENAI_AVAILABLE = False
    print(f"✗ OpenAI库导入失败：{e}")
    print("💡 解决方法：pip install openai==1.61.1")
    sys.exit(1)


def print_header():
    """打印测试标题"""
    print("\n" + "=" * 60)
    print("🔑 OpenAI API 密钥可用性测试（最终修复版）")
    print(f"🕐 测试时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📦 OpenAI版本：{openai.__version__}")
    print("=" * 60)


def check_api_key():
    """检查API密钥设置状态"""
    print("\n📋 第1步：API密钥检查")
    print("-" * 30)

    # 获取API密钥
    api_key = os.environ.get('OPENAI_API_KEY')

    if not api_key:
        print("  ✗ 错误：未找到 OPENAI_API_KEY 环境变量")
        if ENV_LOADED:
            print("  ⚠  .env 文件加载成功，但未找到 OPENAI_API_KEY")
        print("  💡 解决方法：")
        print("     export OPENAI_API_KEY='sk-your-key'")
        print("     或在 .env 文件中添加：OPENAI_API_KEY=sk-your-key")
        return False, None

    # 基本格式验证
    key_length = len(api_key)
    key_prefix = api_key[:8]

    print(f"  ✓ API密钥已设置（长度：{key_length}字符）")
    print(f"  ✓ 密钥前缀：{key_prefix}...")

    # 更新密钥格式验证（支持新版项目密钥）
    if api_key.startswith('sk-proj-'):
        print("  ✓ 密钥类型：项目密钥（sk-proj-）✓")
        if key_length < 100 or key_length > 200:
            print("  ⚠  警告：项目密钥长度异常（正常范围：100-200字符）")
        else:
            print("  ✓ 密钥长度：符合项目密钥标准")
    elif api_key.startswith('sk-'):
        print("  ✓ 密钥类型：传统密钥（sk-）✓")
        if key_length < 40 or key_length > 60:
            print("  ⚠  警告：传统密钥长度异常（正常范围：40-60字符）")
        else:
            print("  ✓ 密钥长度：符合传统密钥标准")
    else:
        print("  ⚠  警告：API密钥格式异常（应以 'sk-' 或 'sk-proj-' 开头）")
        return False, api_key

    print("  ✓ 密钥格式基本验证通过")
    return True, api_key


def test_client_initialization(api_key):
    """测试OpenAI客户端初始化"""
    print("\n🔌 第2步：客户端初始化测试")
    print("-" * 30)

    try:
        client = OpenAI(
            api_key=api_key,
            timeout=15.0,
            max_retries=0  # 不自动重试，便于诊断
        )
        print("  ✓ OpenAI客户端初始化成功")

        # 测试客户端基本属性
        print(f"  ✓ API基础URL：{client.base_url}")
        print(f"  ✓ API密钥类型：{api_key[:10]}...（已验证）")
        return True, client

    except openai.AuthenticationError as e:
        print(f"  ✗ 认证错误：{str(e)[:100]}...")
        print("  💡 可能原因：")
        print("     • API密钥无效或已过期")
        print("     • 账户被暂停")
        return False, None

    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)
        print(f"  ✗ 客户端初始化失败")
        print(f"  ❌ 类型：{error_type}")
        print(f"  ❌ 信息：{error_msg}")

        if "invalid api key" in error_msg.lower():
            print("  💡 诊断：API密钥格式错误或无效")
        elif "network" in error_msg.lower():
            print("  💡 诊断：网络连接问题")
        elif "timeout" in error_msg.lower():
            print("  💡 诊断：连接超时，检查网络")

        return False, None


def test_models_list(client):
    """测试模型列表获取（兼容OpenAI 1.61.1）"""
    print("\n📋 第3步：模型列表测试（轻量级API调用）")
    print("-" * 30)

    try:
        print("  🔄 正在请求模型列表...")
        start_time = time.time()

        # OpenAI 1.61.1兼容写法：不使用limit参数
        models = client.models.list()
        end_time = time.time()

        print(f"  ✓ 模型列表获取成功（耗时：{end_time - start_time:.2f}秒）")

        # 只显示前3个模型
        model_names = [model.id for model in models.data[:3]]
        total_count = len(models.data)
        print(f"  ✓ 可用模型（前3个）：{', '.join(model_names)}")
        print(f"  ✓ 总模型数：{total_count}")

        # 检查常见模型
        common_models = ["gpt-3.5-turbo", "gpt-4", "gpt-4o", "gpt-4o-mini"]
        all_model_names = [model.id for model in models.data]
        available_common = [m for m in common_models if any(m in model_name for model_name in all_model_names)]
        if available_common:
            print(f"  ✓ 常用模型可用：{', '.join(available_common[:2])}...")
        else:
            print("  ⚠  未找到常用模型，可能权限受限")

        return True

    except openai.AuthenticationError as e:
        print(f"  ✗ 认证失败：{str(e)[:100]}...")
        print("  💡 可能原因：")
        print("     • API密钥无效或已过期")
        print("     • 账户余额不足")
        print("     • 账户被暂停或限制")
        return False

    except openai.PermissionDeniedError as e:
        print(f"  ✗ 权限拒绝：{str(e)[:100]}...")
        print("  💡 可能原因：")
        print("     • 账户无权访问API")
        print("     • 组织策略限制")
        return False

    except openai.RateLimitError as e:
        print(f"  ✗ 速率限制：{str(e)[:100]}...")
        print("  💡 建议：")
        print("     • 等待1分钟后重试")
        print("     • 检查API使用配额")
        print("     • 升级付费计划")
        return False

    except openai.APIError as e:
        status_code = getattr(e, 'status_code', '未知')
        print(f"  ✗ API错误（状态码：{status_code}）：{str(e)[:100]}...")
        if status_code == 402:
            print("  💡 诊断：账户余额不足，请充值")
        elif status_code == 429:
            print("  💡 诊断：请求频率过高，请稍后重试")
        return False

    except Exception as e:
        print(f"  ✗ 未知错误：{type(e).__name__}: {str(e)[:100]}...")
        return False


def test_chat_completion(client):
    """测试聊天完成（完整API调用）"""
    print("\n💬 第4步：聊天完成测试（完整API调用）")
    print("-" * 30)

    try:
        print("  🔄 正在发送测试消息...")
        start_time = time.time()

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",  # 使用最基础的模型
            messages=[
                {
                    "role": "system",
                    "content": "你是一个简洁的助手。请用中文回复。"
                },
                {
                    "role": "user",
                    "content": "请回复'测试成功'三个字，不要添加其他内容。"
                }
            ],
            max_tokens=10,
            temperature=0.1,
        )

        end_time = time.time()
        content = response.choices[0].message.content.strip()
        total_tokens = getattr(response.usage, 'total_tokens', '未知')

        print(f"  ✓ 聊天完成成功（耗时：{end_time - start_time:.2f}秒）")
        print(f"  ✓ 模型响应：'{content}'")
        print(f"  ✓ 令牌使用：{total_tokens}")

        # 验证响应内容
        if "测试成功" in content:
            print("  ✓ 响应验证：完全符合预期")
        else:
            print(f"  ⚠  响应验证：内容异常（预期：'测试成功'）")

        return True

    except openai.NotFoundError as e:
        print(f"  ✗ 模型未找到：{str(e)[:100]}...")
        print("  💡 可能原因：")
        print("     • 模型名称错误")
        print("     • 账户无权访问该模型")
        print("  💡 建议：尝试使用 gpt-4o-mini")
        return False

    except openai.AuthenticationError as e:
        print(f"  ✗ 认证失败：{str(e)[:100]}...")
        return False

    except openai.APIError as e:
        status_code = getattr(e, 'status_code', '未知')
        print(f"  ✗ API错误（状态码：{status_code}）：{str(e)[:100]}...")
        if status_code == 402:
            print("  💡 账户余额不足，请充值")
        return False

    except Exception as e:
        print(f"  ✗ 未知错误：{type(e).__name__}: {str(e)[:100]}...")
        return False


def generate_final_report(key_valid, client_valid, models_valid, chat_valid):
    """生成最终测试报告（修复参数名）"""
    print("\n" + "=" * 60)
    print("📊 测试报告总结")
    print("=" * 60)

    # 测试结果汇总
    results = {
        "API密钥设置": key_valid,
        "客户端初始化": client_valid,
        "模型列表获取": models_valid,
        "聊天完成": chat_valid
    }

    # 计算整体状态
    passed_count = sum(results.values())
    total_count = len(results)
    overall_status = "✅ 完全可用" if passed_count == total_count else "⚠  部分可用" if passed_count > 0 else "❌ 不可用"

    print(f"整体状态：{overall_status}")
    print(f"通过测试：{passed_count}/{total_count}")
    print("\n详细结果：")
    print("-" * 30)

    for test_name, passed in results.items():
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"  {test_name:<15} {status}")

    print("\n" + "=" * 60)

    if passed_count == total_count:
        print("🎉 恭喜！您的OpenAI API配置完全正常")
        print("\n🚀 下一步建议：")
        print("  • 可以开始开发OpenAI集成功能")
        print("  • 监控API使用量和费用：https://platform.openai.com/usage")
        print("  • 考虑设置使用限制和错误处理")
        print("  • 定期轮换API密钥（每3-6个月）")

    elif passed_count > 0:
        print("⚠  部分功能可用，需要修复")
        print("\n🔧 需要修复的测试：")
        failed_tests = [name for name, passed in results.items() if not passed]
        for test in failed_tests:
            print(f"  • {test}")
        print("\n💡 请查看上述详细错误信息进行修复")

    else:
        print("💥 所有测试都失败了")
        print("\n🚨 紧急修复步骤：")
        print("  1. 检查API密钥是否正确复制（从OpenAI官网）")
        print("  2. 验证网络连接：ping api.openai.com")
        print("  3. 检查OpenAI账户状态和余额：https://platform.openai.com/account")
        print("  4. 重新生成API密钥")

    print(f"\n📞 如需帮助，请提供此报告的完整输出")
    print(f"🔗 OpenAI状态：{openai.__version__}")
    print("=" * 60)


def main():
    """主测试函数（修复调用顺序）"""
    print_header()

    # 初始化测试结果
    test_results = {}

    # 测试1：API密钥检查
    key_valid, api_key = check_api_key()
    test_results['key_valid'] = key_valid

    if not key_valid:
        generate_final_report(key_valid=key_valid, client_valid=False, models_valid=False, chat_valid=False)
        sys.exit(1)

    # 测试2：客户端初始化
    client_valid, client = test_client_initialization(api_key)
    test_results['client_valid'] = client_valid

    if not client_valid:
        generate_final_report(key_valid=key_valid, client_valid=client_valid, models_valid=False, chat_valid=False)
        sys.exit(1)

    # 测试3：模型列表
    models_valid = test_models_list(client)
    test_results['models_valid'] = models_valid

    # 测试4：聊天完成
    chat_valid = test_chat_completion(client)
    test_results['chat_valid'] = chat_valid

    # 生成最终报告（使用正确参数名）
    generate_final_report(
        key_valid=test_results['key_valid'],
        client_valid=test_results['client_valid'],
        models_valid=test_results['models_valid'],
        chat_valid=test_results['chat_valid']
    )

    # 退出状态码
    exit_code = 0 if all([test_results['key_valid'], test_results['client_valid'], test_results['models_valid'],
                          test_results['chat_valid']]) else 1
    sys.exit(exit_code)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠  测试被用户中断")
        sys.exit(130)
    except Exception as e:
        print(f"\n💥 脚本执行异常：{type(e).__name__}: {str(e)}")
        print("请检查Python环境和依赖安装")
        sys.exit(1)