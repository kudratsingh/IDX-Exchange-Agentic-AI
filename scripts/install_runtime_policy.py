"""Install the IDX response policy in the configured agent workspace with backups."""

from __future__ import annotations

import argparse
import os
import tempfile
import uuid
from pathlib import Path

from openclaw_merge_config import load_json5

BEGIN = "<!-- IDX RESPONSE POLICY BEGIN -->"
END = "<!-- IDX RESPONSE POLICY END -->"


def install_policy(source: Path, workspace: Path) -> bool:
    """Preserve workspace notes, replace only our block, and back up prior bytes."""
    if workspace.is_symlink():
        raise ValueError("workspace must not be a symlink")
    target = workspace / "AGENTS.md"
    if target.is_symlink():
        raise ValueError("workspace instructions must not be a symlink")
    policy = source.read_text(encoding="utf-8").strip()
    if not policy or BEGIN in policy or END in policy:
        raise ValueError("invalid response policy")
    original = target.read_bytes() if target.exists() else b""
    text = original.decode("utf-8")
    if text.count(BEGIN) != text.count(END) or text.count(BEGIN) > 1:
        raise ValueError("ambiguous managed policy markers")
    block = BEGIN + "\n" + policy + "\n" + END
    if BEGIN in text:
        start, end = text.index(BEGIN), text.index(END)
        if end < start:
            raise ValueError("reversed managed policy markers")
        updated = text[:start] + block + text[end + len(END) :]
    else:
        updated = text + ("\n\n" if text else "") + block + "\n"
    encoded = updated.encode("utf-8")
    if encoded == original:
        return False
    workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
    if target.exists():
        backups = workspace / ".idx-policy-backups"
        if backups.is_symlink():
            raise ValueError("backup directory must not be a symlink")
        backups.mkdir(mode=0o700, exist_ok=True)
        backup = backups / ("AGENTS-" + uuid.uuid4().hex + ".md")
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(original)
        if backup.read_bytes() != original:
            raise ValueError("backup verification failed")
    if (
        target.is_symlink()
        or (target.read_bytes() if target.exists() else b"") != original
    ):
        raise ValueError("workspace instructions changed during installation")
    fd, temporary = tempfile.mkstemp(prefix=".idx-policy-", dir=workspace)
    with os.fdopen(fd, "wb") as stream:
        stream.write(encoded)
    os.replace(temporary, target)
    return True


def configured_workspace(config: Path) -> Path:
    """Resolve the same idx workspace selected by the installed configuration."""
    agents = load_json5(config).get("agents", {})
    value = agents.get("entries", {}).get("idx", {}).get("workspace")
    value = value or agents.get("defaults", {}).get("workspace")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("idx workspace is not configured")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("idx workspace must be absolute")
    return path


def main() -> None:
    """Install the public policy; never read workspace memory or print its content."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1] / "config" / "IDX_RUNTIME.md"
    changed = install_policy(source, configured_workspace(args.config))
    print(
        "IDX response policy installed."
        if changed
        else "IDX response policy unchanged."
    )


if __name__ == "__main__":
    main()
