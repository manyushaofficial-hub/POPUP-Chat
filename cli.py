"""本機測試：不用接 LINE，直接在終端機模擬工作人員提問。

python cli.py                      # 互動模式
python cli.py "客人問怎麼預約"       # 單次提問
"""
import asyncio
import os
import sys

from bot.service import StaffAssistant


async def main() -> None:
    os.environ.setdefault("ADMIN_USER_IDS", "local-admin")
    bot = StaffAssistant()
    if len(sys.argv) > 1:
        print(await bot.handle("local-admin", " ".join(sys.argv[1:])))
        return
    print("輸入工作人員的問題（Ctrl+C 離開，輸入「說明」查看指令）\n")
    while True:
        try:
            q = input("工作人員> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q:
            print("\n" + await bot.handle("local-admin", q) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
