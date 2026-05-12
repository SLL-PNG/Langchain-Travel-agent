"""应用启动入口：FastAPI + 原生 HTML 前端。"""

import os
import socket

import uvicorn

from api import api_app


def _find_available_port(start_port: int, max_tries: int = 20) -> int:
    """从 start_port 开始寻找可绑定端口。"""
    for port in range(start_port, start_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"未找到可用端口：{start_port}-{start_port + max_tries - 1}")


if __name__ == "__main__":
    preferred_port = int(os.getenv("PORT", "7861"))
    port = _find_available_port(preferred_port)
    print(f"服务启动地址：http://127.0.0.1:{port}/")
    uvicorn.run(api_app, host="127.0.0.1", port=port)
