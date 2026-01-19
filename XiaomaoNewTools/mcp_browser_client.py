import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


HELP = """Commands:
  pages                     列出页面
  open <url>                新开页面并打开 url
  goto <url>                当前选中页导航到 url
  js <expr>                 执行 JS 表达式（返回结果），如：js document.title
  fn <function>             执行 JS 函数字符串，如：fn () => document.title
  screenshot                截图（返回内容看 server）
  console                   列出 console messages
  network                   列出 network requests
  help                      帮助
  quit                      退出
"""


async def main():
    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "chrome-devtools-mcp@latest", "--browser-url=http://127.0.0.1:9222"],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("MCP REPL connected. Type 'help'.")

            while True:
                cmd = input("> ").strip()
                if not cmd:
                    continue
                if cmd in ("quit", "exit"):
                    return
                if cmd == "help":
                    print(HELP)
                    continue

                try:
                    if cmd == "pages":
                        r = await session.call_tool("list_pages", {})
                        print(r.content[0].text)

                    elif cmd.startswith("open "):
                        url = cmd[5:].strip()
                        r = await session.call_tool("new_page", {"url": url})
                        print(r.content[0].text)

                    elif cmd.startswith("goto "):
                        url = cmd[5:].strip()
                        r = await session.call_tool("navigate_page", {"url": url})
                        print(r.content[0].text)

                    elif cmd.startswith("js "):
                        expr = cmd[3:].strip()
                        r = await session.call_tool("evaluate_script", {"function": f"() => ({expr})"})
                        print(r.content[0].text)

                    elif cmd.startswith("fn "):
                        fn = cmd[3:].strip()
                        r = await session.call_tool("evaluate_script", {"function": fn})
                        print(r.content[0].text)

                    elif cmd == "screenshot":
                        r = await session.call_tool("take_screenshot", {})
                        print(r)

                    elif cmd == "console":
                        r = await session.call_tool("list_console_messages", {})
                        print(r)

                    elif cmd == "network":
                        r = await session.call_tool("list_network_requests", {})
                        print(r)

                    else:
                        print("Unknown command. Type 'help'.")

                except Exception as e:
                    print("Error:", e)


if __name__ == "__main__":
    asyncio.run(main())
