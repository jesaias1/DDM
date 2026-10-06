"""Generate Vercel CDN assets from the shared frontend."""
import shutil
from pathlib import Path

root = Path(__file__).resolve().parents[1]
shutil.copytree(root / "static", root / "public" / "static", dirs_exist_ok=True)
