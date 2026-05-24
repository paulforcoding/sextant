"""
端到端测试：两个 project session 同时保持，跨项目发通知。
"""
import asyncio, json
from mcp.client.streamable_http import streamable_http_client
from mcp import ClientSession


async def session_worker(url: str, label: str, actions: list):
    """保持一个 session 并执行一系列操作。actions 中的每个元素是 ('call_tool', name, args)。"""
    async with streamable_http_client(url) as (read, write, get_sid):
        async with ClientSession(read, write) as session:
            await session.initialize()
            sid = get_sid()
            print(f"  [{label}] connected, sid={sid[:12]}...")

            results = []
            for action in actions:
                if action[0] == "call_tool":
                    _, name, args = action
                    result = await session.call_tool(name, args)
                    text = result.content[0].text
                    try:
                        data = json.loads(text)
                    except (json.JSONDecodeError, TypeError):
                        data = text
                    print(f"  [{label}] {name}: {data}")
                    results.append((name, data))
                elif action[0] == "sleep":
                    await asyncio.sleep(action[1])

            return results


async def test():
    # 两个 session 同时保持：sextant 发消息，ncp 等着收
    async with asyncio.TaskGroup() as tg:
        # ncp 先启动（它会先 ping 注册，然后等待）
        ncp_task = tg.create_task(
            session_worker(
                "http://127.0.0.1:19876/mcp?project=ncp",
                "ncp",
                [
                    ("call_tool", "ping", {}),
                    ("sleep", 5),  # 等待 sextant 发消息
                    ("call_tool", "ping", {}),  # 第二次 ping，验证 session 还在
                ],
            )
        )

        # 等 ncp 注册完
        await asyncio.sleep(2)

        # sextant 连接、ping、发消息
        sextant_task = tg.create_task(
            session_worker(
                "http://127.0.0.1:19876/mcp?project=sextant",
                "sextant",
                [
                    ("call_tool", "ping", {}),
                    (
                        "call_tool",
                        "send_message",
                        {
                            "to": "ncp",
                            "subject": "跨项目测试通知",
                            "body": "如果你看到这条消息，说明 MCP notification 推送成功！",
                        },
                    ),
                    ("call_tool", "list_projects", {}),
                ],
            )
        )


if __name__ == "__main__":
    asyncio.run(test())
