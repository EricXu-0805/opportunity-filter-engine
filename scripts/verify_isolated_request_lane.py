"""Check a released backend's actual HTTP listener on loopback with synthetic queue work."""
import asyncio
import json
import socket
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import uvicorn
from pytest import MonkeyPatch

from backend.lib import blocking
from backend.main import app
from tests.test_request_lane_capacity import _cold_email_content


def post(url, body):
    request = Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        response = urlopen(request, timeout=12)
    except HTTPError as exc:
        response = exc
    with response:
        return response.status, response.headers, json.load(response)


async def main():
    gate = threading.Event()
    with socket.socket() as sock, MonkeyPatch.context() as patch:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.listen()
        server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="error"))
        serve = asyncio.create_task(server.serve(sockets=[sock]))
        work = []
        try:
            async with asyncio.timeout(15):
                while not server.started:
                    await asyncio.sleep(.01)
            body = _cold_email_content(patch)
            endpoint = f"http://127.0.0.1:{port}/api/cold-email"
            for _ in range(blocking.REQUEST_LANE_CAPACITY):
                work.append(asyncio.create_task(blocking.run_request_work(gate.wait, 15)))
            async with asyncio.timeout(10):
                while blocking._request_lane_load != blocking.REQUEST_LANE_CAPACITY:
                    await asyncio.sleep(.01)
            start = time.monotonic()
            code, headers, response = await asyncio.to_thread(post, endpoint, body)
            elapsed = time.monotonic() - start
            assert code == 503 and response == {"detail": {"code": "request_lane_full"}}, (code, response)
            assert headers["Retry-After"] == "5" and "no-store" in headers["Cache-Control"]
            assert blocking._request_lane_load == blocking.REQUEST_LANE_CAPACITY
            print("Occupied", blocking._request_lane_load, "HTTP", code, "Retry-After", headers["Retry-After"],
                  "elapsed ms", round(elapsed * 1000), flush=True)
            gate.set()
            await asyncio.gather(*work)
            assert blocking._request_lane_load == 0
            code, _, response = await asyncio.to_thread(post, endpoint, body)
            assert code == 200 and response["method"] == "template" and response["body"].strip()
            print("Released", blocking._request_lane_load, "same request HTTP", code, "local template recovered", flush=True)
        finally:
            gate.set()
            await asyncio.gather(*work, return_exceptions=True)
            server.should_exit = True
            await serve


if __name__ == "__main__":
    asyncio.run(main())
