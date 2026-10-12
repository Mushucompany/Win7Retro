# -*- coding: utf-8 -*-
"""Генерация ассетов в стиле Windows 7 Aero (собственные, не из бинарников MS):
- стеклянная кнопка "Пуск" (круг с орбитой) для OpenShell / StartAllBack
- системные иконки рабочего стола в Aero-стиле: Компьютер, Корзина (полн/пуст), Сеть

Все файлы — авторская рисовка в духе Aero, легальны для установки.
Требуется: Pillow. Запуск:
    python gen_assets.py
"""
from PIL import Image, ImageDraw, ImageFilter, ImageOps
from pathlib import Path

OUT = Path(__file__).resolve().parent / "win7_assets"
OUT.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Стеклянная кнопка "Пуск" (орбита) — 144x144 (OpenShell масштабирует)
# ---------------------------------------------------------------------------
def glass_gradient(size, top, bottom):
    """Вертикальный градиент с полупрозрачным стеклом."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    w, h = size
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        d.line([(0, y), (w, y)], fill=(r, g, b, 255))
    return img


def make_start_orbit(size=256):
    side = size * 4
    # фоновая подложка кнопки — стеклянный шар с градиентом
    top = (30, 80, 140)   # тёмно-синий
    bottom = (180, 220, 255)
    ball = glass_gradient((side, side), top, bottom)
    mask = Image.new("L", (side, side), 0)
    md = ImageDraw.Draw(mask)
    md.ellipse([0, 0, side, side], fill=255)
    ball.putalpha(mask)
    # блик сверху-слева
    shine = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shine)
    sd.ellipse([0, 0, side, side], fill=(255, 255, 255, 0))
    # градиентный блик
    for i in range(side // 2):
        a = max(0, 90 - i * 2)
        sd.ellipse([i * 0.9, i * 0.6, side - i * 0.9, side - i * 0.6],
                   outline=(255, 255, 255, a))
    ball = Image.alpha_composite(ball, shine)
    # орбита — стилизованное кольцо вокруг шарика
    orbit = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    od = ImageDraw.Draw(orbit)
    od.ellipse([int(side*0.06), int(side*0.06), int(side*0.94), int(side*0.94)],
               outline=(255, 255, 255, 210), width=int(side*0.045))
    od.ellipse([int(side*0.12), int(side*0.12), int(side*0.88), int(side*0.88)],
               outline=(200, 225, 255, 120), width=int(side*0.03))
    ball = Image.alpha_composite(ball, orbit)
    # маленькая "планета" справа внизу внутри кольца
    planet = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    pd = ImageDraw.Draw(planet)
    pd.ellipse([int(side*0.42), int(side*0.52), int(side*0.66), int(side*0.76)],
               fill=(70, 130, 200, 255))
    ball = Image.alpha_composite(ball, planet)
    # мягкое размытие для сияния
    ball = ball.filter(ImageFilter.GaussianBlur(1))
    ball = ball.resize((size, size), Image.LANCZOS)
    return ball


def save_icon(img, name, sizes):
    """Сохраняет картинку как многоразмерный .ico."""
    img = img.convert("RGBA")
    img.save(OUT / name, format="ICO", sizes=[(s, s) for s in sizes])


# ---------------------------------------------------------------------------
# Иконки рабочего стола в Aero-стиле (плоские, с глянцем)
# ---------------------------------------------------------------------------
def rounded_rect(size, radius, fill):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([size*0.06, size*0.10, size*0.94, size*0.90],
                        radius=int(size*radius), fill=fill)
    return img


def aero_base(size=256):
    # сине-голубая глянцевая плитка
    base = rounded_rect(size, 0.10, (70, 140, 210))
    # верхний блик
    gloss = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(gloss)
    gd.rounded_rectangle([size*0.10, size*0.14, size*0.90, size*0.40],
                         radius=int(size*0.08), fill=(255, 255, 255, 90))
    base = Image.alpha_composite(base, gloss)
    return base


def icon_computer(size=256):
    img = aero_base(size)
    d = ImageDraw.Draw(img)
    s = size
    # монитор
    d.rectangle([s*0.22, s*0.25, s*0.88, s*0.68], fill=(235, 242, 250),
                outline=(35, 60, 100), width=max(2, int(s*0.02)))
    d.rectangle([s*0.28, s*0.31, s*0.82, s*0.61], fill=(140, 190, 235))
    # подставка и ножка
    d.polygon([(s*0.42, s*0.70), (s*0.58, s*0.70), (s*0.55, s*0.80),
               (s*0.45, s*0.80)], fill=(60, 90, 130))
    d.rectangle([s*0.36, s*0.80, s*0.64, s*0.88], fill=(60, 90, 130))
    return img


def icon_trash(size=256, full=True):
    img = aero_base(size)
    d = ImageDraw.Draw(img)
    s = size
    # корзина
    body_fill = (120, 160, 210) if full else (200, 215, 235)
    d.rounded_rectangle([s*0.30, s*0.40, s*0.70, s*0.78],
                        radius=int(s*0.05), fill=body_fill,
                        outline=(40, 70, 110), width=max(2, int(s*0.02)))
    # крышка
    d.rounded_rectangle([s*0.22, s*0.30, s*0.78, s*0.42],
                        radius=int(s*0.06), fill=(60, 100, 150),
                        outline=(30, 55, 90), width=max(2, int(s*0.02)))
    d.rounded_rectangle([s*0.18, s*0.22, s*0.82, s*0.32],
                        radius=int(s*0.05), fill=(90, 140, 200),
                        outline=(40, 70, 110), width=max(2, int(s*0.02)))
    # ручка
    d.arc([s*0.44, s*0.16, s*0.56, s*0.30], 180, 360, fill=(60, 100, 150),
          width=max(2, int(s*0.025)))
    # вертикальные полосы
    for x in (s*0.40, s*0.47, s*0.54, s*0.61):
        d.line([(x, s*0.46), (x, s*0.74)], fill=(40, 70, 110),
               width=max(1, int(s*0.02)))
    return img


def icon_network(size=256):
    img = aero_base(size)
    d = ImageDraw.Draw(img)
    s = size
    # монитор как в computers, но с сетью
    d.rectangle([s*0.20, s*0.22, s*0.90, s*0.66], fill=(235, 242, 250),
                outline=(35, 60, 100), width=max(2, int(s*0.02)))
    d.rectangle([s*0.26, s*0.28, s*0.84, s*0.58], fill=(150, 200, 240))
    d.polygon([(s*0.40, s*0.68), (s*0.60, s*0.68), (s*0.56, s*0.80),
               (s*0.44, s*0.80)], fill=(60, 90, 130))
    d.rectangle([s*0.32, s*0.80, s*0.68, s*0.88], fill=(60, 90, 130))
    # глобус-планета на экране
    d.ellipse([s*0.42, s*0.33, s*0.68, s*0.53], fill=(40, 90, 170))
    d.arc([s*0.40, s*0.20, s*0.70, s*0.56], 200, 340, fill=(255, 255, 255, 180),
          width=max(1, int(s*0.015)))
    return img


def build():
    start = make_start_orbit(256)
    start.save(OUT / "start-button.png")
    save_icon(start, "start_button.ico", [16, 24, 32, 48, 64, 128, 256])
    print("Создана кнопка «Пуск»:", OUT / "start_button.ico")

    items = {
        "computer.ico": icon_computer,
        "recycle_full.ico": lambda: icon_trash(full=True),
        "recycle_empty.ico": lambda: icon_trash(full=False),
        "network.ico": icon_network,
    }
    for fname, fn in items.items():
        ic = fn()
        save_icon(ic, fname, [16, 24, 32, 48, 64, 128, 256])
        print("Создана иконка:", OUT / fname)
    print("Готово! Папка:", OUT)


if __name__ == "__main__":
    build()