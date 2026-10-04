import json

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("stub-server")


@mcp.tool()
def list_emails(query: str = "", cursor: str = "") -> str:
    data = {
        "data": {
            "emails": [
                {
                    "message_id": "123",
                    "from_address": "alice@example.com",
                    "received_time": "2026-10-03T10:00:00Z",
                    "body_text": "Let's meet",
                    "web_url": "https://mail.zoho.com/123",
                }
            ],
            "next_cursor": "cur123",
        }
    }
    return json.dumps(data)


@mcp.tool()
def list_messages(query: str = "", cursor: str = "") -> str:
    data = {
        "data": {
            "messages": [
                {
                    "message_id": "m1",
                    "sender": {"email": "bob@example.com"},
                    "created_time": "2026-10-03T11:00:00Z",
                    "content": "zoom call?",
                    "message_url": "https://cliq.zoho.com/m1",
                }
            ],
            "next_cursor": "cur456",
        }
    }
    return json.dumps(data)


if __name__ == "__main__":
    mcp.run()
