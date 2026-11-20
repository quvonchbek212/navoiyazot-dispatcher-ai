"""Package the presentation as one offline HTML file, without external assets.

Run from any directory: python atil_ai_dispetcher/presentation/build.py
The authored sources are index.html, presentation.css and presentation.js.
"""
from pathlib import Path


def build() -> Path:
    folder = Path(__file__).resolve().parent
    html = (folder / "index.html").read_text(encoding="utf-8")
    css = (folder / "presentation.css").read_text(encoding="utf-8")
    script = (folder / "presentation.js").read_text(encoding="utf-8")
    html = html.replace('<link rel="stylesheet" href="presentation.css">', f"<style>\n{css}\n</style>")
    html = html.replace('<script defer src="presentation.js"></script>', "")
    html = html.replace("</body>", f"<script>\n{script}\n</script>\n</body>")
    output = folder / "ATIL_AI_TAQDIMOT.html"
    output.write_text(html, encoding="utf-8")
    return output


if __name__ == "__main__":
    print(build())
