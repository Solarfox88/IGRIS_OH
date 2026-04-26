"""Intent parser — detects user actions even when LLM doesn't use tags.

Fallback layer for small local LLMs (Mistral, CodeLlama, etc.) that may
describe commands instead of wrapping them in [CMD]/[WRITE_FILE] tags.

Two-phase detection:
1. Parse user message for direct file creation / command execution intents
2. Parse LLM response for commands it described but didn't tag
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger("igris.intent")


# --- Phase 1: Parse user message for direct intents ---

# "crea/create [un] file <name> [sul desktop / in <path>] [con scritto/with content] <content>"
FILE_CREATE_PATTERNS = [
    # Italian: "crea un file test.txt sul desktop con scritto ciao"
    re.compile(
        r"crea(?:mi|re)?\s+(?:un\s+)?file\s+(?:(?:di\s+)?(?:testo\s+)?)?(\S+\.?\w*)"
        r"(?:\s+(?:sul\s+desktop|in|su|nella?\s+cartella|dentro)\s+(.+?))?"
        r"(?:\s+con\s+(?:scritto|contenuto|dentro|testo)\s+[\"']?(.+?)[\"']?\s*$)?",
        re.IGNORECASE,
    ),
    # Italian: "crea qui il file ... <path>"
    re.compile(
        r"crea(?:mi|re)?\s+(?:qui\s+)?(?:il\s+)?file\s+(?:che\s+ti\s+ho\s+chiesto\s+)?(\S+\.?\w*)"
        r"(?:\s+(?:in|su|qui)?\s*(.+?))?\s*$",
        re.IGNORECASE,
    ),
    # English: "create a file test.txt on desktop with content hello"
    re.compile(
        r"create\s+(?:a\s+)?file\s+(\S+\.?\w*)"
        r"(?:\s+(?:on\s+desktop|in|at|inside)\s+(.+?))?"
        r"(?:\s+with\s+(?:content|text)\s+[\"']?(.+?)[\"']?\s*$)?",
        re.IGNORECASE,
    ),
]

# "scrivi/write <content> in/nel file <path>"
WRITE_TO_FILE_PATTERNS = [
    re.compile(
        r"scrivi\s+[\"']?(.+?)[\"']?\s+(?:in|nel|dentro\s+(?:il|al)?\s*)?(?:file\s+)?(\S+)",
        re.IGNORECASE,
    ),
]

# Detect paths in the message
PATH_PATTERN = re.compile(
    r'([A-Z]:\\(?:[^\\/:*?"<>|\s]+\\)*[^\\/:*?"<>|\s]+)'  # Windows: C:\Users\...
    r'|'
    r'((?:/[\w.-]+)+/?)',  # Unix: /home/user/...
)


def parse_user_intent(user_message: str) -> list[dict]:
    """Parse the user message for direct file/command creation intents.

    Returns a list of action dicts:
    - {"type": "write_file", "path": "...", "content": "..."}
    - {"type": "command", "command": "..."}
    """
    actions = []
    msg = user_message.strip()

    # Try file creation patterns
    for pattern in FILE_CREATE_PATTERNS:
        match = pattern.search(msg)
        if match:
            groups = match.groups()
            filename = groups[0] if groups[0] else ""
            directory = groups[1].strip().rstrip("/\\") if len(groups) > 1 and groups[1] else ""
            content = groups[2].strip().strip("'\"") if len(groups) > 2 and groups[2] else ""

            if filename:
                # Try to find explicit path in the message
                path_match = PATH_PATTERN.search(msg)
                if path_match:
                    base_path = (path_match.group(1) or path_match.group(2)).rstrip("/\\")
                    if not base_path.endswith(filename):
                        file_path = base_path.rstrip("/\\") + "\\" + filename if "\\" in base_path else base_path + "/" + filename
                    else:
                        file_path = base_path
                elif directory:
                    sep = "\\" if "\\" in directory else "/"
                    file_path = directory.rstrip("/\\") + sep + filename
                else:
                    file_path = filename

                actions.append({
                    "type": "write_file",
                    "path": file_path,
                    "content": content,
                })
                break

    # Try write-to-file patterns
    if not actions:
        for pattern in WRITE_TO_FILE_PATTERNS:
            match = pattern.search(msg)
            if match:
                content = match.group(1).strip().strip("'\"")
                file_ref = match.group(2).strip()
                actions.append({
                    "type": "write_file",
                    "path": file_ref,
                    "content": content,
                })
                break

    return actions


# --- Phase 2: Parse LLM response for described-but-not-tagged commands ---

# Common command patterns that LLMs describe
DESCRIBED_CMD_PATTERNS = [
    # "touch /path/to/file", "echo content > file", "mkdir dir"
    re.compile(r'(?:^|\n)\s*(?:\d+\.\s*)?`?(touch\s+.+?)`?\s*$', re.MULTILINE),
    re.compile(r'(?:^|\n)\s*(?:\d+\.\s*)?`?(echo\s+.+?)`?\s*$', re.MULTILINE),
    re.compile(r'(?:^|\n)\s*(?:\d+\.\s*)?`?(mkdir\s+.+?)`?\s*$', re.MULTILINE),
    re.compile(r'(?:^|\n)\s*(?:\d+\.\s*)?`?(cat\s+.+?)`?\s*$', re.MULTILINE),
    re.compile(r'(?:^|\n)\s*(?:\d+\.\s*)?`?(pip\s+install\s+.+?)`?\s*$', re.MULTILINE),
    re.compile(r'(?:^|\n)\s*(?:\d+\.\s*)?`?(cd\s+.+?)`?\s*$', re.MULTILINE),
    re.compile(r'(?:^|\n)\s*(?:\d+\.\s*)?`?(ls\s*.*?)`?\s*$', re.MULTILINE),
    re.compile(r'(?:^|\n)\s*(?:\d+\.\s*)?`?(dir\s*.*?)`?\s*$', re.MULTILINE),
    re.compile(r'(?:^|\n)\s*(?:\d+\.\s*)?`?(python\s+.+?)`?\s*$', re.MULTILINE),
    re.compile(r'(?:^|\n)\s*(?:\d+\.\s*)?`?(npm\s+.+?)`?\s*$', re.MULTILINE),
    re.compile(r'(?:^|\n)\s*(?:\d+\.\s*)?`?(git\s+.+?)`?\s*$', re.MULTILINE),
    re.compile(r'(?:^|\n)\s*(?:\d+\.\s*)?`?(node\s+.+?)`?\s*$', re.MULTILINE),
]

# Code blocks with commands
CODE_BLOCK_CMD = re.compile(r'```(?:bash|shell|cmd|powershell|sh)?\s*\n(.+?)\n```', re.DOTALL)


def parse_llm_described_commands(llm_response: str) -> list[str]:
    """Extract commands that the LLM described but didn't tag with [CMD].

    Only returns commands if the response does NOT already contain [CMD] tags.
    """
    from igris.core.chat_engine import CMD_PATTERN, WRITE_FILE_PATTERN

    # If the LLM already used tags, don't double-parse
    if CMD_PATTERN.search(llm_response) or WRITE_FILE_PATTERN.search(llm_response):
        return []

    commands = []

    # Extract from code blocks first
    for match in CODE_BLOCK_CMD.finditer(llm_response):
        block = match.group(1).strip()
        for line in block.split("\n"):
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("//"):
                commands.append(line)

    # If no code blocks, try inline described commands
    if not commands:
        for pattern in DESCRIBED_CMD_PATTERNS:
            for match in pattern.finditer(llm_response):
                cmd = match.group(1).strip().strip("`")
                if cmd and len(cmd) > 2:
                    commands.append(cmd)

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for cmd in commands:
        if cmd not in seen:
            seen.add(cmd)
            unique.append(cmd)

    if unique:
        logger.info(f"Fallback parser found {len(unique)} described commands in LLM response")

    return unique
