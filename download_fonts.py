import os
import urllib.request
import zipfile
import io

FONTS_DIR = os.path.join(os.path.dirname(__file__), "assets", "fonts")
os.makedirs(FONTS_DIR, exist_ok=True)

# Google Fonts zip download URLs
FONTS = {
    "LibreCaslonText": "https://fonts.google.com/download?family=Libre%20Caslon%20Text",
    "HankenGrotesk": "https://fonts.google.com/download?family=Hanken%20Grotesk",
    "JetBrainsMono": "https://fonts.google.com/download?family=JetBrains%20Mono"
}

def download_fonts():
    for name, url in FONTS.items():
        print(f"Downloading {name}...")
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                with zipfile.ZipFile(io.BytesIO(response.read())) as z:
                    for info in z.infolist():
                        if info.filename.endswith('.ttf') or info.filename.endswith('.otf'):
                            # Flatten directory structure
                            info.filename = os.path.basename(info.filename)
                            if info.filename:
                                target_path = os.path.join(FONTS_DIR, info.filename)
                                if not os.path.exists(target_path):
                                    with open(target_path, "wb") as f:
                                        f.write(z.read(info))
                                    print(f"  Extracted {info.filename}")
        except Exception as e:
            print(f"Failed to download {name}: {e}")

if __name__ == "__main__":
    download_fonts()
    print("Fonts downloaded successfully.")
