# -*- coding: utf-8 -*-
"""Строит HTML-галерею всех .ico из папки win7_icons\icon,
конвертируя каждую в PNG-превью (крупнейший размер)."""
from PIL import Image
from pathlib import Path

SRC = Path("win7_icons") / "icon"
PREVIEW = Path("win7_icons") / "preview"
PREVIEW.mkdir(exist_ok=True)

items = []
for ico in sorted(SRC.glob("*.ico"), key=lambda p: int(p.stem) if p.stem.isdigit() else 0):
    try:
        im = Image.open(ico)
        # выбрать наибольший кадр
        largest = (0, 0, 0)
        best = None
        for size in im.ico.sizes():
            if size[0] > largest[0]:
                largest = size
        im = im.convert("RGBA")
        im.thumbnail((96, 96), Image.LANCZOS)
        png = PREVIEW / (ico.stem + ".png")
        im.save(png)
        items.append((ico.name, png.name, largest))
    except Exception as e:
        print("skip", ico.name, e)

html = ["<!doctype html><html><head><meta charset='utf-8'>",
        "<title>Иконки Windows 7 — галерея</title>",
        "<style>body{font-family:Segoe UI;background:#1b1b1b;color:#eee;margin:20px;}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:10px;}"
        ".cell{background:#2a2a2a;border-radius:8px;padding:10px;text-align:center;"
        "border:1px solid #3a3a3a;cursor:pointer;}"
        ".cell:hover{border-color:#4a9eff;}"
        ".cell img{width:64px;height:64px;object-fit:contain;}"
        ".cell .n{font-size:11px;opacity:.7;margin-top:6px;}"
        ".cell.sel{border-color:#4a9eff;background:#1f3a5f;}</style></head><body>",
        "<h2>Иконки Windows 7 (Aero) — клик для копирования имени</h2>",
        "<p>Нажми на иконку — скопируется путь к .ico. Нужны для вкладки «Иконки» в Win7Retro.</p>",
        "<div class='grid'>"]

for name, png, size in items:
    full = str((SRC / name).resolve())
    idx = name.replace(".ico", "")
    html.append(f"<div class='cell' onclick='copy(this)' data-v='{full}' title='{name} ({size[0]}px)'>"
                f"<img src='preview/{png}' alt='{name}'><div class='n'>#{idx}</div></div>")

html.append("</div><script>"
            "function copy(el){var t=document.createElement('textarea');"
            "t.value=el.dataset.v;document.body.appendChild(t);t.select();"
            "document.execCommand('copy');document.body.removeChild(t);"
            "el.classList.add('sel');var s=el.querySelector('.n');"
            "s.textContent='скопировано!';setTimeout(function(){s.textContent=el.title.split(' (')[0];},1500);}"
            "</script></body></html>")

Path("win7_icons_gallery.html").write_text("\n".join(html), encoding="utf-8")
print("Gallery:", "win7_icons_gallery.html", "| icons:", len(items))