# Standard résumé export fonts

The export renderer reads these local static fonts. It never downloads fonts or opens user URLs.

- `NotoSansCJKsc-Regular.ttf`: Noto Sans CJK SC, weight 400, full TrueType CJK build (44,810 mapped code points). The smaller regional subset misses some names, including 𠮷.
- `NotoEmoji-Regular.ttf`: Noto Emoji, weight 400, monochrome individual emoji (1,489 mapped code points).
- `manifest.json`: pinned upstream URLs, input/output SHA-256, family names, copyright, size and build version.
- Both fonts use SIL OFL 1.1; the complete license texts are included. Original copyright and licensing metadata remain in the font name tables. No reserved `Source` name is used for the derived font family.

PDF embeds the glyphs needed by that file. DOCX embeds a subset of each font the file needs: the characters it uses, Latin and punctuation, and, when it has East Asian text, the GB2312 symbols and 3,755 level-1 hanzi, so common later edits keep the same face. Word for Mac 16.113.3 cuts an embedded font down to the document's characters whenever it saves, so that extra coverage lasts until the first save in Word. A Word file with one Chinese line is about 0.8 MB; the complete CJK font made it 11.6 MB. Its settings ask Word to save only font subsets (`saveSubsetFonts`): with that off, Word for Mac saved such a file at 6.2 MB, adding whole Times New Roman, Calibri, Cambria, Courier and Symbol; with it on, at 49 KB. LibreOffice 26.2 saved it at 1.6 MB either way, embedding the CJK subset twice (see below). Characters typed later outside the subset use an installed font (Word for Mac chose Microsoft YaHei). The fontTable declares each embedded font's panose, charset (86, GB2312, for the CJK font), family, pitch and code-page signature; without them Word for Mac set the Chinese text in SimSun. The regular weight is intentional; hierarchy uses font size and spacing, without synthetic bold or an additional large font payload.

LibreOffice 26.2.4.2 on macOS re-saved the 838,132 B export of the walk draft with one Chinese skill at 1,622,467 B (`soffice --convert-to docx`). It wrote the 1,263,168 B CJK subset twice, as `embedRegular` and `embedBold`, and kept `embedTrueTypeFonts` but dropped `saveSubsetFonts`, so a later Word save falls back to Word's default (not measured). The two copies come from LibreOffice, not from this file. Its DOCX export asks for each embedded family's regular, bold, italic and bold-italic face (`DocxAttributeOutput::EmbedFont`). `EmbeddedFontsManager::fontFileUrl` names the file of a face that matches the request after the requested attributes; when none matches, as for bold here, it writes every face of the family under that face's own attributes. On macOS every face reports an unknown family type (`DevFontFromCTFontDescriptor`), while the request carries the document's `swiss`, so the one regular face is written a second time and declared bold. Italic and bold italic then find that second file and are skipped, which is why only two copies appear. A fontTable family of `auto`, or none, did not help: LibreOffice then requested `roman` and still wrote both copies. LibreOffice on Windows or Linux was not checked. Source read at tag `libreoffice-26.2.4.2`: `sw/source/filter/ww8/docxattributeoutput.cxx`, `vcl/source/gdi/embeddedfontsmanager.cxx`, `vcl/quartz/SystemFontList.cxx`.

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

Verify the output SHA-256 against the manifest. Keep the assets complete: the renderer subsets per export. Both outputs must contain `glyf`, no `fvar`, and `OS/2.fsType == 0`.

The CJK license comes from the repository root `LICENSE` at the same pinned commit; Emoji uses `ofl/notoemoji/OFL.txt`. Runtime checks reject unavailable or incompatible font assets. Text with missing glyphs or unsupported compound emoji/variation sequences fails with a safe error; it is never silently removed. This is a bounded character contract, not a claim of universal script support.

## Verification boundary

Tests inspect actual PDF text, links, pages, and embedded fonts; DOCX tests inspect editable text, embedded subset coverage, fontTable declarations and relationships. Visual checks use the bundled LibreOffice renderer. Microsoft Word desktop behavior requires separate acceptance on Word; a successful LibreOffice render does not establish that result. Word for Mac 16.113.3 was checked on 2026-09-30: one page for the one-page sample, the embedded CJK font for Chinese text, and editable text.
