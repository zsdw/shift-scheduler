"""텔레그램 읽기 전용 조회 (2026-10-22 사용자 요청).

사용:  .venv\\Scripts\\python -I scripts\\tg_readonly.py --chat HDS --limit 10
       .venv\\Scripts\\python -I scripts\\tg_readonly.py --chat HDS --since 2026-10-21T18:00 --until 2026-10-22T08:00

- 읽기만 한다: 메시지 보내기·읽음 표시·삭제·방 나가기 코드는 없다.
- 로그인 증표(안티그래비티에서 만든 C:\\Users\\LJH\\.gemini\\config\\telegram_user.session)는 임시 사본으로 열고
  끝나면 사본을 지운다(안티그래비티와 동시에 열어도 원본 파일이 잠기지 않게). 증표·api_hash 값은 출력하지 않는다.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from telethon import TelegramClient

CONFIG = Path(r"C:\Users\LJH\.gemini\config")


async def read(chat: str, limit: int, since: datetime | None, until: datetime | None) -> int:
    auth = json.loads((CONFIG / "telegram_auth.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        session = Path(tmp) / "readonly"
        shutil.copy2(CONFIG / "telegram_user.session", str(session) + ".session")
        client = TelegramClient(str(session), int(auth["api_id"]), auth["api_hash"])
        await client.connect()
        try:
            if not await client.is_user_authorized():
                print("로그인 증표가 만료됐습니다. 안티그래비티에서 다시 연결해야 합니다.")
                return 2
            target = None
            async for dialog in client.iter_dialogs(limit=200):
                if chat in (dialog.name or ""):
                    target = dialog
                    break
            if target is None:
                print(f"'{chat}'이(가) 들어간 대화방을 찾지 못했습니다.")
                return 3
            print(f"대화방: {target.name}")
            kwargs = {"limit": limit}
            if until is not None:
                kwargs["offset_date"] = until.astimezone()
            messages = await client.get_messages(target.entity, **kwargs)
            for message in reversed(messages):
                when = message.date.astimezone()
                if since is not None and when < since.astimezone():
                    continue
                sender = await message.get_sender()
                who = " ".join(x for x in (getattr(sender, "first_name", None), getattr(sender, "last_name", None)) if x) \
                    or getattr(sender, "title", "") or ""
                text = message.message or "[사진·파일]"
                print(f"- {when:%m/%d %H:%M} {who}: {text}")
            return 0
        finally:
            await client.disconnect()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="텔레그램 읽기 전용 조회")
    parser.add_argument("--chat", default="HDS", help="대화방 이름에 들어간 글자 (기본: HDS)")
    parser.add_argument("--limit", type=int, default=10, help="가져올 최근 메시지 수 (기본 10, 최대 500)")
    parser.add_argument("--since", type=datetime.fromisoformat, help="이 시각 이후만 (예: 2026-10-21T18:00)")
    parser.add_argument("--until", type=datetime.fromisoformat, help="이 시각 이전까지 (예: 2026-10-22T08:00)")
    args = parser.parse_args()
    return asyncio.run(read(args.chat, max(1, min(args.limit, 500)), args.since, args.until))


if __name__ == "__main__":
    raise SystemExit(main())
