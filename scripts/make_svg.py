#!/usr/bin/env python3
"""週間予報の SVG（ライト/ダーク）を生成する。JS・外部フォント不使用、CSS アニメーションのみ。

使い方: python scripts/make_svg.py [--out DIR] [--sample tests/sample.json]
出力:   DIR/weather-light.svg, DIR/weather-dark.svg
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(__file__))
import omiya_weather as ow  # noqa: E402

THEMES = {
    "light": dict(bg="#ffffff", border="#d0d7de", fg="#1f2328", sub="#656d76",
                  hi="#cf222e", lo="#0969da", pop="#0550ae", today="#ddf4ff"),
    "dark": dict(bg="#0d1117", border="#30363d", fg="#e6edf3", sub="#8d96a0",
                 hi="#ff7b72", lo="#79c0ff", pop="#79c0ff", today="#12263f"),
}
W, H, PAD = 700, 250, 16
COL = (W - PAD * 2) / 7


def render(w: ow.Weather, theme: str) -> str:
    c = THEMES[theme]
    d0 = w.days[0]
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'role="img" aria-label="{escape(ow.LOCATION_NAME)}の週間天気予報">',
        "<style>"
        "text{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Hiragino Sans','Noto Sans JP','Yu Gothic',sans-serif}"
        ".ic{font-size:30px;animation:fl 3s ease-in-out infinite}"
        "@keyframes fl{0%,100%{transform:translateY(0)}50%{transform:translateY(-3px)}}"
        "@media (prefers-reduced-motion:reduce){.ic{animation:none}}"
        "</style>",
        f'<rect x=".5" y=".5" width="{W-1}" height="{H-1}" rx="10" fill="{c["bg"]}" stroke="{c["border"]}"/>',
        f'<text x="{PAD}" y="30" font-size="16" font-weight="700" fill="{c["fg"]}">'
        f'{escape(ow.LOCATION_NAME)} 週間予報</text>',
        f'<text x="{W-PAD}" y="30" font-size="12" text-anchor="end" fill="{c["sub"]}">'
        f'今 {ow.emoji(w.code)} {ow.rnd(w.temp)}°C（体感 {ow.rnd(w.feels)}°C）'
        f' 💨{ow.wind_dir_name(w.wind_deg)}{ow.rnd(w.wind_ms)}m/s'
        f'{"" if d0.uv is None else f" UV {d0.uv:.0f}"}'
        f'{"" if not d0.sunrise else f" 🌅{d0.sunrise} 🌇{d0.sunset}"}</text>',
    ]
    for i, d in enumerate(w.days):
        x = PAD + COL * i
        cx = x + COL / 2
        if i == 0:
            out.append(f'<rect x="{x+3:.1f}" y="46" width="{COL-6:.1f}" height="170" rx="8" fill="{c["today"]}"/>')
        out += [
            f'<text x="{cx:.1f}" y="70" font-size="13" font-weight="700" text-anchor="middle" fill="{c["fg"]}">'
            f'{d.weekday}</text>',
            f'<text x="{cx:.1f}" y="86" font-size="11" text-anchor="middle" fill="{c["sub"]}">'
            f'{d.date.month}/{d.date.day}</text>',
            f'<text class="ic" x="{cx:.1f}" y="130" text-anchor="middle" style="animation-delay:{i*0.2:.1f}s">'
            f'{ow.emoji(d.code)}</text>',
            f'<text x="{cx:.1f}" y="150" font-size="11" text-anchor="middle" fill="{c["sub"]}">{escape(ow.text(d.code))}</text>',
            f'<text x="{cx:.1f}" y="178" font-size="16" font-weight="700" text-anchor="middle" fill="{c["hi"]}">'
            f'{ow.rnd(d.tmax)}°</text>',
            f'<text x="{cx:.1f}" y="198" font-size="14" text-anchor="middle" fill="{c["lo"]}">{ow.rnd(d.tmin)}°</text>',
            f'<text x="{cx:.1f}" y="212" font-size="11" text-anchor="middle" fill="{c["pop"]}">'
            f'☔{"–" if d.pop is None else d.pop}%</text>',
        ]
    out.append(
        f'<text x="{W-PAD}" y="{H-12}" font-size="10" text-anchor="end" fill="{c["sub"]}">'
        f'Open-Meteo · 更新 {w.today.month}/{w.today.day}</text></svg>'
    )
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist")
    ap.add_argument("--sample", help="API の代わりに読み込む JSON（テスト用）")
    a = ap.parse_args()
    w = ow.parse(json.load(open(a.sample))) if a.sample else ow.fetch()
    os.makedirs(a.out, exist_ok=True)
    for t in THEMES:
        p = os.path.join(a.out, f"weather-{t}.svg")
        open(p, "w", encoding="utf-8").write(render(w, t))
        print("wrote", p)


if __name__ == "__main__":
    main()
