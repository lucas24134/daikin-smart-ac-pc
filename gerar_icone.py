"""Gera daikin.ico (ícone do .exe e dos atalhos) com o Pillow."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

TAM = 256
img = Image.new("RGBA", (TAM, TAM), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
# fundo arredondado azul
d.rounded_rectangle((8, 8, TAM - 8, TAM - 8), radius=56, fill=(23, 48, 71))
d.rounded_rectangle((8, 8, TAM - 8, TAM - 8), radius=56, outline=(58, 160, 255), width=6)
# aparelho estilizado
d.rounded_rectangle((44, 70, 212, 136), radius=14, fill=(230, 238, 245))
d.rounded_rectangle((58, 114, 198, 126), radius=4, fill=(29, 40, 51))
d.rounded_rectangle((150, 82, 196, 100), radius=5, fill=(15, 26, 36))
# vento
for i, x in enumerate(range(70, 200, 22)):
    dx = (x - 128) * 0.35
    d.line((x, 150, x + dx, 196), fill=(150, 205, 255), width=7)

try:
    fonte = ImageFont.truetype("seguisym.ttf", 30)
    d.text((158, 77), "❄", font=fonte, fill=(58, 160, 255))
except OSError:
    pass

destino = Path(__file__).with_name("daikin.ico")
img.save(destino, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(f"Ícone salvo em {destino}")
