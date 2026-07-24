from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_safeplane_home() -> Path:
    return Path(os.environ.get("SAFEPLANE_HOME", str(Path.home() / ".safeplane"))).expanduser()


def mcp_log_path(safeplane_home: Optional[Path] = None) -> Path:
    root = safeplane_home or default_safeplane_home()
    return root / "logs" / "mcp" / "tool-access.jsonl"


def new_mcp_log_id() -> str:
    return f"log_mcp_{uuid.uuid4()}"


def write_mcp_log(row: Dict[str, Any], *, safeplane_home: Optional[Path] = None) -> Path:
    path = mcp_log_path(safeplane_home)
    path.parent.mkdir(parents=True, exist_ok=True)

    enriched = {
        "log_id": row.get("log_id") or new_mcp_log_id(),
        "ts": row.get("ts") or utc_now(),
        **row,
    }

    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(enriched, ensure_ascii=False) + "\n")

    return path
