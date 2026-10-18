"""평일 주간 현장 양식 이미지를 엑셀 없이 원본과 똑같이 그린다 (2026-10-08 사용자 요청).

바탕은 엑셀이 원본 편성표 양식을 그린 빈 그림(templates/day_form_blank.png), 칸 위치·글꼴은 같은 때 엑셀에서
뽑은 값(templates/day_form_geometry.json, tools/export_day_form_geometry.ps1). 그 위에 원본 엑셀의
조건부 서식 규칙대로 칸을 칠하고 맑은 고딕으로 글자를 쓴다. 테두리는 빈 양식 픽셀을 그대로 되살린다.
"""
from __future__ import annotations

import json
import re
from io import BytesIO
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent / "templates"
BLANK = TEMPLATES / "day_form_blank.png"
GEOMETRY = TEMPLATES / "day_form_geometry.json"
FONT = {False: Path("C:/Windows/Fonts/malgun.ttf"), True: Path("C:/Windows/Fonts/malgunbd.ttf")}
PX = 96 / 72                                     # 엑셀 100% 화면: 1pt = 4/3px
# 원본 편성표 조건부 서식 (E8:BL22): 이 순서로 글자가 들어 있으면 그 색 (테마 색은 원본 테마로 계산한 값)
RULES = (("13", "CC00FF"), ("12", "006699"), ("2", "00B0F0"), ("3", "92D050"), ("11", "CC9900"), ("10", "FFFFCC"),
         ("9", "FF0000"), ("8", "FFFF00"), ("7", "7B7B7B"), ("6", "8EA9DB"), ("5", "DDEBF7"), ("4", "EDEDED"),
         ("1", "70AD47"))
COLOR_COLUMNS = range(5, 65)                     # E~BL (포스트·4C·CP·1C·셔틀·순찰), 대기·휴게는 흰 칸
GREEN_MARK = ("대기",)                           # 원본(10/7·10/8)에서 엑셀 초록 삼각형이 보이는 열: 대기 숫자 칸


def rule_color(text: str) -> str | None:
    """원본 엑셀 조건부 서식과 같은 판정: 글자에 13→12→2→3→11→10→9→8→7→6→5→4→1 순서로 포함되면 그 색."""
    text = str(text or "")
    return next((color for key, color in RULES if key in text), None)


def available() -> bool:
    return BLANK.exists() and GEOMETRY.exists() and FONT[False].exists()


def draw(values: dict[str, str], column_labels: dict[int, str] | None = None,
         blank_path: Path = BLANK, geometry_path: Path = GEOMETRY, colored: bool = True) -> bytes:
    """values: {엑셀 칸 주소: 글자} (day_excel_image.build_spec 와 같은 값).
    휴일 주간 양식(weekend_form)은 같은 방식에 다른 바탕·칸 위치, 번호 색 없음(원본 휴일 시트에 색 규칙 없음)."""
    from PIL import Image, ImageDraw, ImageFont
    from openpyxl.utils import column_index_from_string
    geo = json.loads(geometry_path.read_text(encoding="utf-8-sig"))
    blank = Image.open(blank_path).convert("RGB")
    image = blank.copy()
    pen = ImageDraw.Draw(image)
    labels = column_labels or {}
    for address, text in values.items():
        box = geo["cells"].get(address)
        if not box or not str(text):
            continue
        x0, y0 = round(box["left"] * PX), round(box["top"] * PX)
        x1, y1 = round((box["left"] + box["width"]) * PX), round((box["top"] + box["height"]) * PX)
        column = column_index_from_string(re.match(r"[A-Z]+", address)[0])
        row = int(re.search(r"\d+", address)[0])
        color = rule_color(text) if colored and column in COLOR_COLUMNS and row >= 8 else None
        if color:
            pen.rectangle((x0, y0, x1 - 1, y1 - 1), fill="#" + color)
        size = round(box["size"] * PX)
        font = ImageFont.truetype(str(FONT[bool(box["bold"])]), size)
        text = str(text)
        width = pen.textlength(text, font=font)
        while width > (x1 - x0) - 4 and size > 8:                # 칸보다 길면 엑셀 '셀에 맞춤'처럼 줄임
            size -= 1
            font = ImageFont.truetype(str(FONT[bool(box["bold"])]), size)
            width = pen.textlength(text, font=font)
        ascent, descent = font.getmetrics()
        # 엑셀 화면 글자 자리와 픽셀 대조로 맞춘 보정 (오른쪽 0.5px, 위로 1.5px)
        tx = (x0 + x1) / 2 - width / 2 + 0.5
        ty = (y0 + y1) / 2 - (ascent + descent) / 2 - 1.5
        pen.text((round(tx), round(ty)), text, font=font, fill="black")
        if colored and labels.get(column) in GREEN_MARK and re.fullmatch(r"[\d.]+", text):   # 엑셀 오류 표시(초록 삼각형)
            for i in range(5):                                   # 원본 픽셀 그대로: 5·4·3·2·1px, 008000
                pen.line(((x0 + 1, y0 + 1 + i), (x0 + 5 - i, y0 + 1 + i)), fill="#008000")
    # 테두리는 엑셀이 그린 빈 양식 픽셀 그대로 (칠한 색이 선을 덮지 않게)
    import numpy as np
    base, drawn = np.asarray(blank), np.array(image)
    lines = (base < 90).all(axis=2)
    drawn[lines] = base[lines]
    out = BytesIO()
    Image.fromarray(drawn).save(out, format="PNG")
    return out.getvalue()
