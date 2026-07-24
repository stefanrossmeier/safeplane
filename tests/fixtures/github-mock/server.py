from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


STATE_PATH = Path(os.environ.get("SAFEPLANE_GITHUB_MOCK_STATE", "/data/state.json"))
STATE_PATH.parent.mkdir(parents=True, exist_ok=True)


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"next_number": 1, "pulls": [], "requests": []}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(STATE_PATH)


class Handler(BaseHTTPRequestHandler):
    server_version = "SafeplaneGitHubMock/1"

    def log_message(self, *_args) -> None:
        return

    def send_json(self, status: int, body) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def record(self, state: dict, *, payload=None) -> None:
        state["requests"].append(
            {
                "method": self.command,
                "path": self.path,
                "authorization_present": bool(self.headers.get("Authorization")),
                "payload": payload,
            }
        )

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path == "/health":
            self.send_json(200, {"status": "ok"})
            return
        state = load_state()
        if parsed.path.endswith("/pulls") and parsed.path.startswith("/repos/"):
            query = parse_qs(parsed.query)
            head = (query.get("head") or [""])[0]
            base = (query.get("base") or [""])[0]
            branch = head.split(":", 1)[-1]
            matches = [
                item
                for item in state["pulls"]
                if item.get("state") == "open"
                and item.get("head") == branch
                and item.get("base") == base
            ]
            self.record(state)
            save_state(state)
            self.send_json(200, matches)
            return
        if parsed.path == "/state":
            self.send_json(200, state)
            return
        self.record(state)
        save_state(state)
        self.send_json(404, {"message": "not found"})

    def do_POST(self) -> None:
        parsed = urlsplit(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        state = load_state()
        self.record(state, payload=payload)
        if parsed.path.endswith("/pulls") and parsed.path.startswith("/repos/"):
            repository = parsed.path.removeprefix("/repos/").removesuffix("/pulls").strip("/")
            number = int(state["next_number"])
            state["next_number"] = number + 1
            item = {
                "number": number,
                "html_url": f"https://github.example/{repository}/pull/{number}",
                "draft": bool(payload.get("draft")),
                "state": "open",
                "title": payload.get("title"),
                "body": payload.get("body"),
                "head": payload.get("head"),
                "base": payload.get("base"),
            }
            state["pulls"].append(item)
            save_state(state)
            self.send_json(201, item)
            return
        save_state(state)
        self.send_json(404, {"message": "not found"})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
