# Standard résumé export fonts

The export renderer reads these local static fonts. It never downloads fonts or opens user URLs.

- `NotoSansCJKsc-Regular.ttf`: Noto Sans CJK SC, weight 400, full TrueType CJK build (44,810 mapped code points). The smaller regional subset misses some names, including 𠮷.
- `NotoEmoji-Regular.ttf`: Noto Emoji, weight 400, monochrome individual emoji (1,489 mapped code points).
- `manifest.json`: pinned upstream URLs, input/output SHA-256, family names, copyright, size and build version.
- Both fonts use SIL OFL 1.1; the complete license texts are included. Original copyright and licensing metadata remain in the font name tables. No reserved `Source` name is used for the derived font family.

PDF embeds the glyphs needed by that file. DOCX embeds the **complete** static fonts, so editing can add other supported characters. The regular weight is intentional; hierarchy uses font size and spacing, without synthetic bold or an additional large font payload.

## Rebuild

Install the pinned `fonttools==4.66.0` from the project requirements. Download the two `source_url` values from `manifest.json` to a temporary directory and verify `source_sha256`. For each input, run:

```python
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
font = TTFont(source_path, recalcTimestamp=False)
static = instantiateVariableFont(font, {"wght": 400}, inplace=False, updateFontNames=True)
static.recalcTimestamp = False
static.save(output_path)
```

Verify the output SHA-256 against the manifest. Do not subset the DOCX font assets. Both outputs must contain `glyf`, no `fvar`, and `OS/2.fsType == 0`.

The CJK license comes from the repository root `LICENSE` at the same pinned commit; Emoji uses `ofl/notoemoji/OFL.txt`. Runtime checks reject unavailable or incompatible font assets. Text with missing glyphs or unsupported compound emoji/variation sequences fails with a safe error; it is never silently removed. This is a bounded character contract, not a claim of universal script support.

## Verification boundary

Tests inspect actual PDF text, links, pages, and embedded fonts; DOCX tests inspect editable text, full embedded font bytes and relationships. Visual checks use the bundled LibreOffice renderer. Microsoft Word desktop behavior requires separate acceptance on Word; a successful LibreOffice render does not establish that result.
