"""Run the ordinary API with an extra actionable listing for loopback browser tests."""

from pathlib import Path
from tempfile import TemporaryDirectory

from backend import data_loader

# Link the corpus the app would have used, including a developer's local
# assembled work file when present. The test fixture lives only in this process.
_directory = TemporaryDirectory(prefix="ofe-playwright-")
shards = Path(_directory.name) / "shards"
shards.mkdir()
assembled = data_loader.DATA_DIR / "opportunities.json"
sources = [assembled] if assembled.exists() else sorted((data_loader.DATA_DIR / "shards").glob("*.json"))
if not sources:
    raise RuntimeError("Playwright requires the project corpus")
for source in sources:
    (shards / source.name).symlink_to(source)
(shards / "playwright-actionable.json").symlink_to(Path(__file__).parent / "fixtures" / "actionable-listing.json")
data_loader.DATA_DIR = Path(_directory.name)

from backend.main import app  # noqa: E402, F401
