#!/usr/bin/env python3
"""Call the staging-only synthetic receptionist exercise.

The admin token is read from APEX_ADMIN_TOKEN or --token-file. It is sent as a
bearer token and is never printed. Example:

    APEX_ADMIN_TOKEN=... python3 scripts/staging_exercise.py --base-url https://preview.example
    python3 scripts/staging_exercise.py --base-url https://preview.example --token-file /run/secrets/admin-token
"""
import argparse
import os
import sys
import urllib.error
import urllib.request


def read_token(token_file: str) -> str:
    if token_file:
        with open(token_file, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    return os.environ.get("APEX_ADMIN_TOKEN", "").strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Exercise a staging ApexVoice deployment without a carrier.")
    parser.add_argument("--base-url", required=True, help="Preview origin, without a path")
    parser.add_argument("--token-file", default="", help="File containing the admin token")
    args = parser.parse_args()
    token = read_token(args.token_file)
    if not token:
        print("Set APEX_ADMIN_TOKEN or pass --token-file.", file=sys.stderr)
        return 2
    url = args.base_url.rstrip("/") + "/api/staging/exercise"
    request = urllib.request.Request(
        url,
        data=b"{}",
        method="POST",
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = response.status
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        print(f"Request failed: {exc.reason}", file=sys.stderr)
        return 1
    if token in body:
        body = body.replace(token, "[redacted]")
    print(status)
    print(body)
    return 0 if status == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
