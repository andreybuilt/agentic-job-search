"""
Shared config loader for every tool in this toolkit.

Config values (your name and contact details, data paths, gate list files, render
settings) are never hardcoded in a tool. They are read from one YAML file through this
module.

Resolution order for the config file (first match wins):
  1. `--config <path>`, when the tool passes one in
  2. the `JOBSTACK_CONFIG` environment variable
  3. `./config.yaml` in the current working directory
  4. `config.yaml` at the repository root

There is no fallback to `config.example.yaml`. That file holds a fictional persona, and a
tool that silently ran on it would put someone else's name on your documents. If no config
is found, the tool stops and tells you to run `cp config.example.yaml config.yaml`.

Parser: a small stdlib-only YAML subset, so the toolkit needs no third-party packages.
Supported:
  * `key: value` lines, nested by indentation (spaces only)
  * scalars: strings (quoted or bare), integers, floats, true/false, null/~
  * flow lists of scalars: `[]`, `["a", "b"]`, `[1, 2]`
  * `#` comments (full-line, or after an unquoted value / closing quote)
Anything else (block lists with `- item`, `|` or `>` block scalars, anchors, flow maps,
tabs, a line with no `key:`) is rejected with the line number, never guessed at.

Usage inside a tool:

    from tools.common.config import load_config, get, require
    cfg = load_config(args.config)
    name = require(cfg, "candidate.name")
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_VAR = "JOBSTACK_CONFIG"
CONFIG_DIR_KEY = "__config_dir__"  # set by load_config(); relative paths resolve against it
MISSING_HINT = "Run `cp config.example.yaml config.yaml` in the repo root, then edit config.yaml."


class ConfigError(ValueError):
    """Raised for config syntax this parser does not support."""


def candidate_paths(explicit: Optional[str] = None) -> List[Path]:
    """Every path load_config() would consider, in order. Exposed for tests and doctor.py."""
    out: List[Path] = []
    if explicit:
        out.append(Path(explicit).expanduser())
    env = os.environ.get(ENV_VAR)
    if env:
        out.append(Path(env).expanduser())
    out.append(Path.cwd() / "config.yaml")
    out.append(REPO_ROOT / "config.yaml")
    return out


def resolve_config_path(explicit: Optional[str] = None) -> Path:
    """Return the config path to use, or exit with a clear message.

    An explicit --config or $JOBSTACK_CONFIG that points at a missing file is an error. It
    does not fall through to the next candidate, because the user asked for that file."""
    if explicit:
        p = Path(explicit).expanduser()
        if not p.is_file():
            sys.exit(f"[config] --config points at '{p}', which does not exist.")
        return p
    env = os.environ.get(ENV_VAR)
    if env:
        p = Path(env).expanduser()
        if not p.is_file():
            sys.exit(f"[config] ${ENV_VAR} points at '{p}', which does not exist.")
        return p
    for p in (Path.cwd() / "config.yaml", REPO_ROOT / "config.yaml"):
        if p.is_file():
            return p
    sys.exit(
        "[config] No config.yaml found (looked in the current directory and the repo root, "
        f"and neither --config nor ${ENV_VAR} was set). {MISSING_HINT}"
    )


def _strip_comment(value: str) -> str:
    """Drop a trailing `# comment` that is outside any quotes."""
    quote = None
    for i, ch in enumerate(value):
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "#" and (i == 0 or value[i - 1] in " \t" or value[:i].rstrip().endswith(("'", '"', "]"))):
            return value[:i].rstrip()
    return value.rstrip()


def _parse_scalar(raw: str, lineno: int) -> Any:
    raw = raw.strip()
    if raw == "" or raw.lower() == "null" or raw == "~":
        return None
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    if raw[0] in ("'", '"'):
        q = raw[0]
        if len(raw) < 2 or raw[-1] != q or q in raw[1:-1]:
            raise ConfigError(f"line {lineno}: unterminated or malformed quoted string: {raw}")
        return raw[1:-1]
    if raw[0] in "&*!|>{%@`" or (raw[0] == "-" and not raw[1:2].isdigit()):
        raise ConfigError(f"line {lineno}: unsupported YAML syntax in value: {raw}")
    try:
        if any(c in raw for c in ".eE") and not raw.isalpha():
            return float(raw)
        return int(raw)
    except ValueError:
        return raw


def _split_flow(inner: str, lineno: int) -> List[str]:
    items, cur, quote = [], "", None
    for ch in inner:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            cur += ch
        elif ch in "[]{}":
            raise ConfigError(f"line {lineno}: nested lists or maps are not supported")
        elif ch == ",":
            items.append(cur)
            cur = ""
        else:
            cur += ch
    if quote:
        raise ConfigError(f"line {lineno}: unterminated quote inside a list")
    items.append(cur)
    if items and items[-1].strip() == "" and len(items) > 1:
        items.pop()  # allow a trailing comma
    for it in items:
        if it.strip() == "":
            raise ConfigError(f"line {lineno}: empty item in a list")
    return items


def _parse_value(raw: str, lineno: int) -> Any:
    raw = raw.strip()
    if raw.startswith("["):
        if not raw.endswith("]"):
            raise ConfigError(f"line {lineno}: a flow list must open and close on the same line: {raw}")
        inner = raw[1:-1].strip()
        if inner == "":
            return []
        return [_parse_scalar(x, lineno) for x in _split_flow(inner, lineno)]
    return _parse_scalar(raw, lineno)


def parse_yaml_lite(text: str) -> Dict[str, Any]:
    """Parse the YAML subset described in the module docstring. Raises ConfigError on
    anything outside it."""
    root: Dict[str, Any] = {}
    # (indent of the block's keys or None if not yet seen, the dict, indent of its parent key)
    stack: List[list] = [[0, root, -1]]
    pending_block = False  # the previous key opened a nested block

    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "\t" in line[: len(line) - len(line.lstrip())]:
            raise ConfigError(f"line {lineno}: tab indentation is not supported; use spaces")
        indent = len(line) - len(line.lstrip(" "))
        content = line.strip()
        if content.startswith("- ") or content == "-":
            raise ConfigError(
                f"line {lineno}: block lists ('- item') are not supported; use a flow list like [\"a\", \"b\"]"
            )
        if content.startswith(("---", "...")):
            raise ConfigError(f"line {lineno}: YAML document markers are not supported")
        key, sep, value = content.partition(":")
        if not sep or not key.strip() or (value and not value.startswith(" ")):
            raise ConfigError(f"line {lineno}: expected 'key: value', got: {content}")
        key = key.strip()
        if key[0] in "'\"[{&*!|>?":
            raise ConfigError(f"line {lineno}: unsupported key syntax: {key}")

        if pending_block:
            parent_indent = stack[-1][2]
            if indent <= parent_indent:
                # the block was empty: leave it as {}
                stack.pop()
            else:
                stack[-1][0] = indent
            pending_block = False

        while len(stack) > 1 and indent < stack[-1][0]:
            stack.pop()
        if indent != stack[-1][0]:
            raise ConfigError(f"line {lineno}: inconsistent indentation")
        parent = stack[-1][1]
        if key in parent:
            raise ConfigError(f"line {lineno}: duplicate key '{key}'")

        value = _strip_comment(value.strip())
        if value == "":
            child: Dict[str, Any] = {}
            parent[key] = child
            stack.append([None, child, indent])
            pending_block = True
        else:
            parent[key] = _parse_value(value, lineno)
    return root


# Backwards-compatible private name.
_parse_yaml_lite = parse_yaml_lite


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    """Load the config chosen by resolve_config_path(). Exits with a message (never
    returns an empty or default config) if the file is missing or does not parse."""
    cfg_path = resolve_config_path(path)
    try:
        cfg = parse_yaml_lite(cfg_path.read_text(encoding="utf-8"))
        cfg[CONFIG_DIR_KEY] = str(cfg_path.resolve().parent)
        return cfg
    except ConfigError as exc:
        sys.exit(f"[config] {cfg_path}: {exc}")
    except OSError as exc:
        sys.exit(f"[config] cannot read {cfg_path}: {exc}")


def get(cfg: Dict[str, Any], dotted_key: str, default: Any = None) -> Any:
    """Read a dotted key like 'candidate.name' out of a loaded config dict."""
    node: Any = cfg
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def require(cfg: Dict[str, Any], dotted_key: str) -> Any:
    """Like get(), but exits if the value is missing or empty. Use it for anything a tool
    cannot safely run without."""
    value = get(cfg, dotted_key, default=None)
    if value is None or value == "" or value == []:
        sys.exit(
            f"[config] Required config key '{dotted_key}' is missing or empty. "
            f"Set it in your config.yaml (config.example.yaml lists every key)."
        )
    return value


def resolve_path(cfg: Dict[str, Any], dotted_key: str, base: Optional[str] = None) -> Optional[str]:
    """Read a path-valued key. A relative path is taken relative to `base` when given,
    otherwise relative to the directory of the config file it came from (the repo root
    for the usual config.yaml), so a tool behaves the same from any working directory."""
    value = get(cfg, dotted_key, None)
    if value in (None, ""):
        return None
    p = Path(str(value)).expanduser()
    if not p.is_absolute():
        root = base or cfg.get(CONFIG_DIR_KEY) or str(REPO_ROOT)
        p = Path(root) / p
    return os.path.normpath(str(p))


def add_config_arg(parser) -> None:
    """Add the standard --config flag to an argparse.ArgumentParser."""
    parser.add_argument(
        "--config",
        default=None,
        help="Path to your config YAML (default: $JOBSTACK_CONFIG, then ./config.yaml, then <repo>/config.yaml)",
    )


if __name__ == "__main__":
    # A library, not a command: print the module help and exit 0.
    print(__doc__)
