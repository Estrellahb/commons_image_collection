#!/usr/bin/env python3
"""Claim and update status for #247 (ZB-SPEC-120266311-v1) via local img_server HTTP API."""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE_URL = "http://127.0.0.1:18080"
QUEUE_ID = 247
CLAIMER = "ZeroBench-Author-ZB-SPEC-120266311-v1"


def load_token() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("IMG_SERVER_TOKEN="):
            return s.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("IMG_SERVER_TOKEN not found in .env")


def api_call(method: str, path: str, payload: dict, token: str):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return e.code, body


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "claim"
    token = load_token()
    if mode == "claim":
        st1, res1 = api_call("POST", "/api/claims", {"id": QUEUE_ID, "claimer": CLAIMER}, token)
        print("POST /api/claims:", st1, json.dumps(res1, ensure_ascii=False))
        if st1 >= 400:
            sys.exit(1)
        st2, res2 = api_call(
            "PATCH",
            "/api/tags",
            {
                "id": QUEUE_ID,
                "authored_status": "draft",
                "authored_ref": "ZB-SPEC-120266311-v1 | outputs/authoring_ZB-SPEC-120266311-v1",
            },
            token,
        )
        print("PATCH /api/tags (draft):", st2, json.dumps(res2, ensure_ascii=False))
        if st2 >= 400:
            sys.exit(1)
    elif mode == "authored":
        payload_path = Path(sys.argv[2])
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        st, res = api_call("PATCH", "/api/tags", payload, token)
        print("PATCH /api/tags (authored):", st, json.dumps(res, ensure_ascii=False))
        if st >= 400:
            sys.exit(1)


if __name__ == "__main__":
    main()
