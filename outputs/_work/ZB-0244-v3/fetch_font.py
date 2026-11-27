"""Fetch a display-only Chinese font subset for the offline HTML."""
import re
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
content = '\n'.join((HERE / name).read_text() for name in [
    'build_html.py', 'prompt.txt', 'facts.json', 'qa_notes.md'])
content += '三次有效试答全部正确，最终按中等难度登记。有效样本中的错答数为零。'
characters = ''.join(sorted(set(re.findall(r'[\u3000-\u303f\u3400-\u9fff\uff00-\uffef]', content))))
params = urllib.parse.urlencode({'family': 'Noto Sans SC', 'text': characters})
user_agent = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
request = urllib.request.Request('https://fonts.googleapis.com/css2?' + params, headers={'User-Agent': user_agent})
css = urllib.request.urlopen(request, timeout=30).read().decode()
url = re.search(r'url\((https://fonts\.gstatic\.com/[^)]+)', css).group(1)
font = urllib.request.urlopen(url, timeout=30).read()
assert font[:4] == b'wOF2'
license_text = urllib.request.urlopen('https://raw.githubusercontent.com/google/fonts/main/ofl/notosanssc/OFL.txt', timeout=30).read()
assert b'SIL OPEN FONT LICENSE' in license_text
(HERE / 'cjk_subset.woff2').write_bytes(font)
(HERE / 'font_license.txt').write_bytes(license_text)
print(len(characters), len(font))
