import asyncio
from modelcontextprotocol.client import Client
from modelcontextprotocol.client.stdio import StdioClientTransport

async def main():
    transport = StdioClientTransport(
        command="npx",
        args=[
            "-y",
            "chrome-devtools-mcp@latest",
            "--browser-url=http://127.0.0.1:9222"
        ]
    )

    client = Client(
        name="pycharm-mcp-client",
        version="0.1.0"
    )

    await client.connect(transport)

    # 1. 列出可用工具
    tools = await client.list_tools()
    print("Available tools:")
    for t in tools:
        print("-", t.name)

    # 2. 列出当前 Chrome tabs
    result = await client.call_tool(
        name="browser.listTabs",
        arguments={}
    )

    print("\nCurrent tabs:")
    print(result)

    await client.close()

if __name__ == "__main__":
    asyncio.run(main())
