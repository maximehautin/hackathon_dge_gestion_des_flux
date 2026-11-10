"""Assemble l'application Marguerite v2 en un seul fichier HTML sans clé."""
import os, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
flux_api_url = os.environ.get("FLUX_API_URL", "")

def daisy(size, col):
    petals = "".join(f'<ellipse cx="50" cy="27" rx="9" ry="15" transform="rotate({a} 50 50)" style="fill:none;stroke:{col};stroke-width:5"/>' for a in range(0, 360, 40))
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 100 100" aria-hidden="true">'
            f'<circle cx="50" cy="50" r="46" style="fill:none;stroke:{col};stroke-width:5"/>{petals}'
            f'<circle cx="50" cy="50" r="10" style="fill:{col}"/></svg>')

body = (SRC / "body.html").read_text(encoding="utf-8")
body = body.replace("__LOGO_SMALL__", daisy(30, "currentColor")).replace("__LOGO_BIG__", daisy(96, "#fff"))
js = (SRC / "app.js").read_text(encoding="utf-8")
js = (js.replace("__CATALOGUE__", (SRC / "catalogue.json").read_text(encoding="utf-8"))
        .replace("__FLUX_API_URL__", flux_api_url))
css = (SRC / "style.css").read_text(encoding="utf-8") + "\n.leaflet-container{font:inherit}.leaflet-div-icon{background:none;border:0}\n"
html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="referrer" content="strict-origin-when-cross-origin">
<title>Marguerite – votre séjour à vélo en étoile en Isère</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
/* Leaflet 1.9.4 (BSD-2-Clause) */
{(SRC / "leaflet.css").read_text(encoding="utf-8")}
</style>
<style>
{css}
</style>
</head>
<body>
{body}
<script>
/* Leaflet 1.9.4 – © Volodymyr Agafonkin, BSD-2-Clause */
{(SRC / "leaflet.js").read_text(encoding="utf-8")}
</script>
<script>
{js}
</script>
</body>
</html>"""
out = ROOT / "app" / "index.html"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(html, encoding="utf-8")
print(f"Application générée : {out} ({len(html)//1024} Ko)")
