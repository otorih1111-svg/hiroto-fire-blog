"""
ブログ本文を、スマホで読みやすいように短い段落へ整形する。

方針:
- frontmatterは保持
- 通常本文だけを対象に、1段落を原則1〜2文へ分割
- 見出し、箇条書き、引用、表、コメント、コードブロックは維持
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent
CONTENT_DIR = SCRIPT_DIR.parent / "src" / "content" / "blog"

SPECIAL_PREFIXES = ("#", "-", ">", "|", "<!--")


def split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        return "", text
    end = text.find("\n---\n", 4)
    if end == -1:
        return "", text
    end += len("\n---\n")
    return text[:end], text[end:]


def split_sentences(text: str) -> list[str]:
    parts = re.findall(r".+?(?:[。！？!?](?:[)）\"]*)|$)", text, flags=re.DOTALL)
    return [part.strip() for part in parts if part.strip()]


def should_keep_block(block: str) -> bool:
    stripped = block.lstrip()
    if not stripped:
        return True
    if stripped == "---":
        return True
    if stripped.startswith(SPECIAL_PREFIXES):
        return True
    if "\n" in block and any(line.lstrip().startswith(SPECIAL_PREFIXES) for line in block.splitlines()):
        return True
    if "```" in block:
        return True
    return False


def reflow_block(block: str) -> str:
    stripped = block.strip()
    if should_keep_block(stripped):
        return stripped

    one_line = re.sub(r"\s*\n\s*", " ", stripped)
    sentences = split_sentences(one_line)
    if len(sentences) <= 2:
        return "\n".join(sentences) if len(sentences) == 2 else one_line

    groups: list[str] = []
    current: list[str] = []
    for sentence in sentences:
        current.append(sentence)
        if len(current) == 2:
            groups.append(" ".join(current).strip())
            current = []
    if current:
        groups.append(" ".join(current).strip())
    return "\n\n".join(groups)


def reflow_body(body: str) -> str:
    parts = re.split(r"(```[\s\S]*?```)", body)
    rebuilt: list[str] = []
    for part in parts:
        if not part:
            continue
        if part.startswith("```"):
            rebuilt.append(part)
            continue
        blocks = part.split("\n\n")
        rebuilt_blocks = [reflow_block(block) for block in blocks]
        rebuilt.append("\n\n".join(rebuilt_blocks))
    return "".join(rebuilt)


def main() -> int:
    parser = argparse.ArgumentParser(description="ブログ本文を短い段落へ整形")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("files", nargs="*", help="対象ファイル名")
    args = parser.parse_args()

    files = [CONTENT_DIR / name for name in args.files] if args.files else sorted(CONTENT_DIR.glob("*.md"))

    print(f"対象記事: {len(files)}本")
    for i, path in enumerate(files, 1):
        text = path.read_text(encoding="utf-8")
        frontmatter, body = split_frontmatter(text)
        if not frontmatter:
            print(f"[{i}/{len(files)}] {path.name} SKIP frontmatter")
            continue
        updated = frontmatter + reflow_body(body)
        if not args.dry_run:
            path.write_text(updated, encoding="utf-8")
        print(f"[{i}/{len(files)}] {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
