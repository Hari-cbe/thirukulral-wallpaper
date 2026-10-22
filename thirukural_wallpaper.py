#!/usr/bin/env python3
"""
Daily Thirukkural Desktop Wallpaper Application
===============================================
Fetches a daily or random Thirukkural from https://kural.codewithram.dev/api/kural/{number}
(where number is 1..1330), renders a high-resolution desktop wallpaper with Tamil & English
meanings, sets it as the OS desktop background, and supports one-command boot startup registration
for Windows, macOS, and Linux.
"""

from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import json
import os
import platform
import random
import shutil
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Error: Pillow is required. Install it with: pip install Pillow", file=sys.stderr)
    sys.exit(1)


API_URL_TEMPLATE = "https://kural.codewithram.dev/api/kural/{number}"
MIN_KURAL = 1
MAX_KURAL = 1330

APP_DIR = Path.home() / ".thirukkural_wallpaper"
CACHE_FILE = APP_DIR / "kural_cache.json"
INPUT_VARIABLE = APP_DIR / "input_number.txt"
WALLPAPER_OUTPUT = APP_DIR / "current_thirukkural_wallpaper.png"

# Fallback Kural matching the exact API schema for offline first-boot resilience
FALLBACK_KURAL: Dict[str, Any] = {
    "number": 1245,
    "kural": [
        "செற்றார் எனக்கை விடல்உண்டோ நெஞ்சேயாம்",
        "உற்றால் உறாஅ தவர்.",
    ],
    "transliteration": [
        "Setraar Enakkai Vitalunto Nenjeyaam",
        "Utraal Uraaa Thavar",
    ],
    "meaning": {
        "en": "O my soul! can he who loves not though he is beloved, be forsaken saying he hates me (now)?",
        "en_modern": (
            "She asks whether she can give up loving a person simply because he does not "
            "return her love. Caring does not vanish on command, even when a relationship "
            "has become one-sided."
        ),
        "ta_mu_va": (
            "நெஞ்சே! யாம் விரும்பி நாடினாலும் எம்மை நாடாத அவர் நம்மை வெறுத்து விட்டார் "
            "என்று எண்ணிக் கைவிட முடியுமோ?"
        ),
        "ta_salamon": (
            "நெஞ்சே! நான் அவர்மீது அன்பு காட்டியும், என்மீது அன்பு காட்டாத அவரை, நம்மை "
            "வெறுத்தவர் என்று எண்ணிக் கைவிடும் உள்ள உறுதி எனக்கு உண்டோ?"
        ),
        "ta_kalaignar": (
            "நெஞ்சே! நாம் விரும்பினாலும் நம்மை விரும்பி வராத அவர், நம்மை வெறுத்து விட்டார் "
            "என நினைத்து அவர் மீது கொண்ட காதலைக் கைவிட்டு விட முடியுமா?"
        ),
    },
    "section": {"id": 3, "names": {"ta": "காமத்துப்பால்", "en": "Love"}},
    "chapter": {"id": 125, "names": {"ta": "நெஞ்சோடு கிளத்தல்", "en": "Soliloquy"}},
}


def pick_kural_number(mode: str = "random", explicit_number: Optional[int] = None ) -> int:
    """Selects a Kural number between 1 and 1330."""
    
    if explicit_number is not None:
        if not (MIN_KURAL <= explicit_number <= MAX_KURAL):
            raise ValueError(f"Kural number must be between {MIN_KURAL} and {MAX_KURAL}.")
        return explicit_number

    if mode == "daily":
        today_seed = int(dt.date.today().strftime("%Y%m%d"))
        minvariable = int((subprocess.run(["less",INPUT_VARIABLE],capture_output=True,text=True)).stdout.strip())
        if 0 <= minvariable < 1330: 
            os.system(f"echo {minvariable + 1} > {INPUT_VARIABLE}")
        else:
            os.system(f"echo {1} > {INPUT_VARIABLE}")
        return minvariable

    return random.randint(MIN_KURAL, MAX_KURAL)


def load_cache() -> Dict[str, Any]:
    """Loads cached Kural responses from disk."""
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_to_cache(kural_data: Dict[str, Any]) -> None:
    """Saves a fetched Kural response to the local offline cache."""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    cache = load_cache()
    number_key = str(kural_data.get("number", ""))
    if number_key:
        cache[number_key] = kural_data
        CACHE_FILE.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def fetch_kural(
    number: int,
    retries: int = 3,
    backoff_seconds: float = 2.0,
    timeout: float = 8.0,
) -> Dict[str, Any]:
    """
    Fetches Kural JSON from https://kural.codewithram.dev/api/kural/{number}.
    Retries on boot when Wi-Fi/network may still be initializing, and falls back
    to cached Kurals or the built-in fallback if offline.
    """
    url = API_URL_TEMPLATE.format(number=number)
    headers = {
        "Accept": "application/json",
        "User-Agent": "ThirukkuralDesktopWallpaper/1.0",
    }

    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                save_to_cache(payload)
                return payload
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            if attempt < retries:
                time.sleep(backoff_seconds * attempt)
            else:
                print(
                    f"Warning: Network fetch failed ({exc}). Falling back to offline cache.",
                    file=sys.stderr,
                )

    cache = load_cache()
    if str(number) in cache:
        return cache[str(number)]
    if cache:
        return random.choice(list(cache.values()))
    return FALLBACK_KURAL


def find_font(preferred_names: List[str], size: int) -> ImageFont.FreeTypeFont:
    """Locates an installed Tamil/Unicode-capable font across Windows, macOS, and Linux."""
    search_paths = [
        # Linux Noto Tamil & Sans fonts
        "/usr/share/fonts/truetype/noto/AnekTamil-SemiBold.ttf ",
        "/usr/share/fonts/truetype/noto/NotoSansTamil-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansTamil-Bold.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansTamil-Regular.ttc",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]

    for name in preferred_names + search_paths:
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue

    return ImageFont.load_default()


def render_wallpaper(
    data: Dict[str, Any],
    output_path: Path = WALLPAPER_OUTPUT,
    resolution: Tuple[int, int] = (1920, 1080),
    tamil_scholar: str = "ta_mu_va",
) -> Path:
    """Renders the Thirukkural data onto a 16:9 desktop wallpaper PNG."""
    width, height = resolution
    img = Image.new("RGB", (width, height), "#000000")
    draw = ImageDraw.Draw(img)

    # Subtle vertical gradient background (deep slate to midnight indigo)
    for y in range(height):
        ratio = y / max(height - 1, 1)
        r = int(15 + (23 - 15) * ratio)
        g = int(23 + (37 - 23) * ratio)
        b = int(42 + (68 - 42) * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Central card container
    margin_x = int(width * 0.08)
    margin_y = int(height * 0.10)
    card_box = [margin_x, margin_y, width - margin_x, height - margin_y]
    draw.rounded_rectangle(
        card_box,
        radius=28,
        fill=(22, 32, 56),
        outline=(212, 175, 55),
        width=2,
    )

    # Load fonts
    font_badge = find_font(["AnekTamil-Bold.ttf","NotoSansTamil-Bold.ttf", "NirmalaB.ttf", "segoeui.ttf"], int(height * 0.022))
    font_kural = find_font(["AnekTamil-Bold.ttf","NotoSansTamil-Bold.ttf", "NirmalaB.ttf"], int(height * 0.038))
    font_translit = find_font(["AnekTamil-Bold.ttf", "segoeui.ttf"], int(height * 0.021))
    font_label = find_font(["AnekTamil-Bold.ttf", "NirmalaB.ttf","DejaVuSans.ttf", "segoeui.ttf"], int(height * 0.020))
    font_body = find_font(["AnekTamil-Bold.ttf", "Nirmala.ttf","DejaVuSans.ttf", "segoeui.ttf"], int(height * 0.022))

    # Extract fields matching API structure
    number = data.get("number", "")
    kural_lines = data.get("kural", ["", ""])
    translit_lines = data.get("transliteration", ["", ""])
    meaning = data.get("meaning", {})
    section = data.get("section", {}).get("names", {})
    chapter = data.get("chapter", {}).get("names", {})
    chapter_id = data.get("chapter", {}).get("id", "")

    pad_x = margin_x + int(width * 0.05)
    cursor_y = margin_y + int(height * 0.05)

    # 1. Header Metadata (Section, Chapter, Kural Number)
    header_text = (
        f"திருக்குறள் #{number}   |   "
        f"{section.get('ta', '')} ({section.get('en', '')})   | "
        f"அதிகாரம் {chapter_id}: {chapter.get('ta', '')} ({chapter.get('en', '')})"
    )
    draw.text((pad_x, cursor_y), header_text, font=font_badge, fill=(245, 197, 66))
    cursor_y += int(height * 0.065)

    # Divider line
    draw.line(
        [(pad_x, cursor_y), (width - pad_x, cursor_y)],
        fill=(56, 74, 112),
        width=2,
    )
    cursor_y += int(height * 0.04)

    # 2. Two-line Tamil Kural Couplet
    for line in kural_lines:
        draw.text((pad_x, cursor_y), line, font=font_kural, fill=(255, 250, 240))
        cursor_y += int(height * 0.058)

    cursor_y += int(height * 0.01)

    # 3. Transliteration
    for t_line in translit_lines:
        draw.text((pad_x, cursor_y), t_line, font=font_translit, fill=(148, 163, 184))
        cursor_y += int(height * 0.032)

    cursor_y += int(height * 0.035)

    # 4. Tamil Commentary (Selectable or All 3 Scholars)
    scholar_labels = {
        "ta_mu_va": "மு. வரதராசனார் உரை (Mu. Varadarajan)",
        "ta_salamon": "சாலமன் பாப்பையா உரை (Solomon Pappayya)",
        "ta_kalaignar": "கலைஞர் மு. கருணாநிதி உரை (Kalaignar)",
    }
    selected_keys = (
        ["ta_mu_va", "ta_salamon", "ta_kalaignar"]
        if tamil_scholar == "all"
        else [tamil_scholar]
    )

    for key in selected_keys:
        ta_text = meaning.get(key, "")
        if not ta_text:
            continue
        draw.text(
            (pad_x, cursor_y),
            scholar_labels.get(key, "தமிழ் உரை"),
            font=font_label,
            fill=(245, 197, 66),
        )
        cursor_y += int(height * 0.032)
        for wrapped in textwrap.wrap(ta_text, width=72):
            draw.text((pad_x, cursor_y), wrapped, font=font_body, fill=(226, 232, 240))
            cursor_y += int(height * 0.032)
        cursor_y += int(height * 0.02)

    # 5. English Meaning (Modern & Classic)
    en_modern = meaning.get("en_modern") or meaning.get("en", "")
    if en_modern:
        draw.text(
            (pad_x, cursor_y),
            "English Meaning",
            font=font_label,
            fill=(96, 165, 250),
        )
        cursor_y += int(height * 0.032)
        for wrapped in textwrap.wrap(en_modern, width=90):
            draw.text((pad_x, cursor_y), wrapped, font=font_body, fill=(226, 232, 240))
            cursor_y += int(height * 0.032)

    en_classic = meaning.get("en", "")
    if en_classic and en_classic != en_modern and tamil_scholar != "all":
        cursor_y += int(height * 0.015)
        draw.text(
            (pad_x, cursor_y),
            "Classic Translation (G.U. Pope)",
            font=font_label,
            fill=(148, 163, 184),
        )
        cursor_y += int(height * 0.030)
        for wrapped in textwrap.wrap(en_classic, width=90):
            draw.text((pad_x, cursor_y), wrapped, font=font_translit, fill=(148, 163, 184))
            cursor_y += int(height * 0.028)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, format="PNG")
    return output_path


def set_os_wallpaper(image_path: Path) -> bool:
    """Sets the desktop wallpaper on Windows, macOS, or Linux."""
    resolved = str(image_path.resolve())
    system = platform.system()

    if system == "Windows":
        SPI_SETDESKWALLPAPER = 20
        SPIF_UPDATEINIFILE = 0x01
        SPIF_SENDWININICHANGE = 0x02
        result = ctypes.windll.user32.SystemParametersInfoW(
            SPI_SETDESKWALLPAPER,
            0,
            resolved,
            SPIF_UPDATEINIFILE | SPIF_SENDWININICHANGE,
        )
        return bool(result)

    if system == "Darwin":
        script = (
            f'tell application "System Events" to set picture of every desktop '
            f'to POSIX file "{resolved}"'
        )
        res = subprocess.run(["osascript", "-e", script], check=False)
        return res.returncode == 0

    if system == "Linux":
        uri = f"file://{resolved}"
        if shutil.which("gsettings"):
            subprocess.run(
                ["gsettings", "set", "org.gnome.desktop.background", "picture-uri", uri],
                check=False,
            )
            subprocess.run(
                ["gsettings", "set", "org.gnome.desktop.background", "picture-uri-dark", uri],
                check=False,
            )
            return True
        if shutil.which("feh"):
            subprocess.run(["feh", "--bg-scale", resolved], check=False)
            return True

    return False


def install_boot_startup(mode: str = "random", scholar: str = "ta_mu_va") -> str:
    """Registers the application to run automatically when the PC boots/logs in."""
    script_path = Path(__file__).resolve()
    python_exe = sys.executable
    system = platform.system()

    if system == "Windows":
        startup_dir = (
            Path(os.environ.get("APPDATA", ""))
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Startup"
        )
        startup_dir.mkdir(parents=True, exist_ok=True)
        vbs_path = startup_dir / "ThirukkuralWallpaper.vbs"
        pythonw_exe = Path(python_exe).with_name("pythonw.exe")
        exe_to_use = str(pythonw_exe if pythonw_exe.exists() else python_exe)
        cmd = f'"{exe_to_use}" "{script_path}" --mode {mode} --scholar {scholar}'
        vbs_content = (
            'Set WshShell = CreateObject("WScript.Shell")\n'
            f'WshShell.Run "{cmd.replace(chr(34), chr(34)*2)}", 0, False\n'
        )
        vbs_path.write_text(vbs_content, encoding="utf-8")
        return f"Installed Windows Startup launcher at: {vbs_path}"


    # Linux (XDG Autostart)
    autostart_dir = Path.home() / ".config" / "autostart"
    autostart_dir.mkdir(parents=True, exist_ok=True)
    desktop_path = autostart_dir / "thirukkural-wallpaper.desktop"
    desktop_content = f"""[Desktop Entry]
Type=Application
Name=Daily Thirukkural Wallpaper
Comment=Displays a daily or random Thirukkural on the desktop wallpaper at boot
Exec={python_exe} {script_path} --mode {mode} --scholar {scholar}
Terminal=false
X-GNOME-Autostart-enabled=true
"""
    desktop_path.write_text(desktop_content, encoding="utf-8")
    return f"Installed Linux XDG Autostart entry at: {desktop_path}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch a Thirukkural (1-1330) and set it as your desktop wallpaper."
    )
    parser.add_argument(
        "--mode",
        choices=["random", "daily"],
        default="random",
        help="'random' picks a random Kural (1-1330) every boot; 'daily' seeds by date.",
    )
    parser.add_argument(
        "--number",
        type=int,
        default=None,
        help="Explicit Kural number (1-1330) to display.",
    )
    parser.add_argument(
        "--scholar",
        choices=["ta_mu_va", "ta_salamon", "ta_kalaignar", "all"],
        default="ta_mu_va",
        help="Tamil commentary scholar to display on the wallpaper.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=WALLPAPER_OUTPUT,
        help="Output PNG path for the generated wallpaper.",
    )
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="Only render the PNG image without changing the OS desktop wallpaper.",
    )
    parser.add_argument(
        "--install-startup",
        action="store_true",
        help="Register this script to run automatically when your PC boots.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.install_startup:
        msg = install_boot_startup(mode=args.mode, scholar=args.scholar)
        print(msg)
    kural_number = pick_kural_number(mode=args.mode, explicit_number=args.number)
    kural_data = fetch_kural(kural_number)
    img_path = render_wallpaper(
        kural_data,
        output_path=args.output,
        tamil_scholar=args.scholar,
    )
    print(f"Rendered Kural #{kural_data.get('number')} wallpaper to: {img_path} ")

    if not args.render_only:
        applied = set_os_wallpaper(img_path)
        if applied:
            print("Desktop wallpaper updated.")
        else:
            print("Wallpaper image generated (OS wallpaper setter not applicable in this environment).")


if __name__ == "__main__":
    main()