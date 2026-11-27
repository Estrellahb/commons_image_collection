"""取得本页汉字所需的 Noto Sans SC 网页字体子集。"""
import re
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

work = Path(__file__).resolve().parent
page = work.parent.parent / "authoring_ZB-0235-v2/author_record.html"
html = page.read_text()
characters = "".join(sorted({c for c in html if ord(c) > 127}))
params = urlencode({"family": "Noto Sans SC:wght@400..700", "text": characters, "display": "swap"})
declaration = Request(
    f"https://fonts.googleapis.com/css2?{params}",
    headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"},
)
with urlopen(declaration, timeout=12) as response:
    css = response.read().decode()
url, = re.findall(r"url\((https://[^)]+)\)", css)
assert urlsplit(url).hostname == "fonts.gstatic.com"
with urlopen(url, timeout=12) as response:
    data = response.read()
assert data[:4] == b"wOF2"
license_url = "https://raw.githubusercontent.com/google/fonts/main/ofl/notosanssc/OFL.txt"
with urlopen(license_url, timeout=12) as response:
    license_text = response.read().decode()
assert "SIL OPEN FONT LICENSE" in license_text
(work / "record_font.woff2").write_bytes(data)
(work / "record_font_OFL.txt").write_text(license_text)
print(f"{len(characters)} 字符，{len(data)} 字节")
