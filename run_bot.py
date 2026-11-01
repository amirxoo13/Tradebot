"""نقطهٔ شروع ربات. فایل .env کنار همین فایل خودش خوانده می‌شود."""
import asyncio
import os
import sys
from pathlib import Path

env = Path(__file__).resolve().parent / ".env"
if env.exists():
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from bot.runner import amain

if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))
