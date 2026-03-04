#!/usr/bin/env python3
"""
OTA firmware upload for CuWatch (Mongoose multi-POST protocol).

The device's HTTP OTA handler expects the binary split into chunks,
each sent as a separate POST with ?offset=N&total=T query parameters.
A final POST with an empty body and offset==total triggers mg_ota_end(),
which commits the firmware and reboots the device.

Usage:
    python3 ota_upload.py <pico-ip> cuwatch.bin [--port 8080] [--chunk 4096]

Example:
    python3 ota_upload.py 192.168.4.45 build/cuwatch.bin

NOTE: upload cuwatch.bin (raw binary), NOT cuwatch.uf2.
"""

import argparse
import os
import sys
import urllib.error
import urllib.request


def upload(ip: str, port: int, firmware_path: str, chunk_size: int) -> None:
    total = os.path.getsize(firmware_path)
    base_url = f"http://{ip}:{port}/ota"

    print(f"Uploading {firmware_path} ({total:,} bytes) to {base_url}")
    print(f"Chunk size: {chunk_size} bytes  ({-(-total // chunk_size)} chunks)")

    with open(firmware_path, "rb") as f:
        offset = 0
        while True:
            data = f.read(chunk_size)
            if not data:
                break
            url = f"{base_url}?offset={offset}&total={total}"
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/octet-stream")
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    if resp.status != 200:
                        print(f"\nError at offset {offset}: HTTP {resp.status}")
                        sys.exit(1)
            except urllib.error.URLError as e:
                print(f"\nNetwork error at offset {offset}: {e}")
                sys.exit(1)
            offset += len(data)
            pct = offset * 100 // total
            bar = "#" * (pct // 5) + "." * (20 - pct // 5)
            print(f"\r[{bar}] {pct:3d}%  {offset:,}/{total:,} bytes", end="", flush=True)

    print()  # newline after progress bar

    # Final empty POST — triggers mg_ota_end() and device reboot
    url = f"{base_url}?offset={total}&total={total}"
    req = urllib.request.Request(url, data=b"", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode(errors="replace").strip()
            if resp.status == 200:
                print(f"OTA complete — device rebooting. Server said: {body}")
            else:
                print(f"Finalize failed: HTTP {resp.status}  {body}")
                sys.exit(1)
    except urllib.error.URLError as e:
        # Device may reboot before sending the response — treat as success
        print(f"OTA likely complete (device rebooted before response: {e})")


def main() -> None:
    parser = argparse.ArgumentParser(description="CuWatch OTA firmware uploader")
    parser.add_argument("ip", help="Pico-W IP address")
    parser.add_argument("firmware", help="Firmware binary (cuwatch.bin)")
    parser.add_argument("--port", type=int, default=8080, help="HTTP port (default 8080)")
    parser.add_argument(
        "--chunk",
        type=int,
        default=4096,
        help="Chunk size in bytes (default 4096; must fit in device MG_MAX_RECV_SIZE)",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.firmware):
        print(f"Error: {args.firmware!r} not found")
        sys.exit(1)

    upload(args.ip, args.port, args.firmware, args.chunk)


if __name__ == "__main__":
    main()
