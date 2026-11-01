#!/usr/bin/env python3
"""Run the single-process iCloud HME server."""
import os
import uvicorn
from app.network import network_info, PORT

HOST = os.getenv("IHME_HOST", "127.0.0.1")


def main():
    print("iCloud Hide My Email Manager")
    print(f"Listening on {HOST}:{PORT}")
    for item in network_info()["candidates"]:
        print(f"  {item['label']}: {item['url']}")
    print("Only addresses on the listening interface are reachable.")
    print("Open the dashboard to set your password and configure the extension.")
    uvicorn.run("app.server:app", host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
