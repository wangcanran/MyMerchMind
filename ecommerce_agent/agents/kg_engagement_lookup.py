"""从 LightRAG ``query_data`` 结果收集 ``file_path``，并回溯 JSON 提取互动量摘要。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Set


def collect_file_paths_from_query_data(raw: Any) -> List[str]:
    found: Set[str] = set()

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            fp = x.get("file_path")
            if isinstance(fp, str) and fp.strip():
                found.add(fp.strip())
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for i in x:
                walk(i)

    walk(raw)
    return sorted(found)


def format_engagement_for_prompt(
    project_root: Path,
    rel_paths: List[str],
    *,
    max_files: int = 8,
    max_chars: int = 4000,
) -> str:
    lines: List[str] = []
    total = 0
    for rel in rel_paths[:max_files]:
        p = Path(rel)
        if not p.is_absolute():
            p = project_root / rel
        if not p.is_file():
            continue
        try:
            raw_text = p.read_text(encoding="utf-8")
            data = json.loads(raw_text)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue

        if isinstance(data, list):
            posts = data
        elif isinstance(data, dict):
            posts = data.get("posts") or data.get("data") or []
        else:
            continue
        if isinstance(posts, dict):
            posts = [posts]
        if not isinstance(posts, list):
            continue

        for post in posts[:24]:
            if not isinstance(post, dict):
                continue
            pid = post.get("post_id") or post.get("id", "")
            lk, cl = post.get("liked_count"), post.get("collected_count")
            if lk is None and cl is None:
                continue
            seg = f"- 帖 {pid}: 赞 {lk} / 藏 {cl}\n"
            if total + len(seg) > max_chars:
                return "".join(lines)
            lines.append(seg)
            total += len(seg)
    return "".join(lines)
