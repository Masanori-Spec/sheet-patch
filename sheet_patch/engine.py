"""Bounded PDF acceptance, deterministic pair matching and evidence export.

Call analyze in a disposable worker (see runner.py), never on a web thread.
"""
from __future__ import annotations
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
import hashlib
import html
import json
import logging
import math
import os
import struct
import subprocess
import time
import zlib
import zipfile
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, StreamObject, ContentStream

MAX_BYTES = 16 * 1024 * 1024
MAX_SIDES = 80
MAX_TOTAL_PIXELS = 200_000_000
MAX_SIDE_PIXELS = 20_000_000
MAX_OBJECTS = 100_000
MAX_DEPTH = 100
DPI_OPTIONS = (72, 144, 216)
WARNINGS = [
    "Reuse is a raster-match candidate at the selected DPI, not identical PDF content or guaranteed print output.",
    "Spot colors, overprint, color management, printer drivers, font substitution and subpixel detail can differ. Inspect both sides; force reprint when uncertain.",
    "Only already-imposed, fixed-size, flattened PDFs are supported. Front/back ordering is supplied by you and is not inferred.",
    "Use only unbound sheets in good physical condition. Keep each front/back pair together; do not flip or rotate sheets based on this plan.",
    "No printer is controlled. Verify duplex settings and feed orientation independently with a safe proof before printing."
]
class InputError(ValueError):
    pass

class StrictPdfLog(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.WARNING:
            raise InputError("PDF parser reported a structural warning; flatten or repair the document first.")

def digest(data):
    return hashlib.sha256(data).hexdigest()

def safe_name(name):
    # Display-only names: never used as filesystem paths or URLs.
    return ''.join(c for c in str(name).replace('\\', '/').split('/')[-1] if c.isprintable())[:160] or 'document.pdf'

def plan_pairs(old, new, force=()):
    """Maximal equal ordered-pair reuse, reserving same-position matches first.

    Force is a set of zero-based NEW sheet indices. Old sheets remain available
    to satisfy other new positions when a position is forced to reprint.
    """
    force = set(force)
    if any(type(i) is not int or i < 0 or i >= len(new) for i in force):
        raise InputError('Force-reprint sheet number is outside the new document.')
    matched = {i: i for i in range(min(len(old), len(new))) if i not in force and old[i] == new[i]}
    used = set(matched.values())
    supply = defaultdict(deque)
    for i, pair in enumerate(old):
        if i not in used:
            supply[pair].append(i)
    for i, pair in enumerate(new):
        if i not in force and i not in matched and supply[pair]:
            matched[i] = supply[pair].popleft()
    assembly, patch = [], 0
    for i, pair in enumerate(new):
        old_i = matched.get(i)
        if old_i is None:
            patch += 1
        assembly.append(dict(newSheet=i + 1,
            action='reprint' if old_i is None else ('keep' if old_i == i else 'move'),
            oldSheet=None if old_i is None else old_i + 1,
            patchSheet=patch if old_i is None else None,
            forced=i in force, frontHash=pair[0], backHash=pair[1]))
    return assembly, [i + 1 for i in range(len(old)) if i not in matched.values()]


def verify_assembly(old, new, assembly, retire, force):
    """Fail closed if an internal plan ever violates the physical-sheet contract."""
    used = set()
    patch_number = 0
    if len(assembly) != len(new):
        raise InputError('Internal assembly verification failed; no packet was produced.')
    valid = True
    for i, row in enumerate(assembly):
        valid = valid and row['newSheet'] == i+1 and row['forced'] == (i in force)
        source = row['oldSheet']
        if source is None:
            patch_number += 1
            valid = valid and row['action'] == 'reprint' and row['patchSheet'] == patch_number
        else:
            valid = valid and type(source) is int and 1 <= source <= len(old) and source not in used and i not in force
            if not valid:
                raise InputError('Internal assembly verification failed; no packet was produced.')
            valid = valid and old[source-1] == new[i] and row['patchSheet'] is None
            valid = valid and row['action'] == ('keep' if source == i+1 else 'move')
            used.add(source)
        valid = valid and (row['frontHash'], row['backHash']) == new[i]
    valid = valid and retire == [i for i in range(1,len(old)+1) if i not in used]
    if not valid:
        raise InputError('Internal assembly verification failed; no packet was produced.')

# Reject active/interactive features rather than dropping them when exporting.
FORBIDDEN = {'/AcroForm','/Annots','/OCProperties','/OC','/OpenAction','/AA',
    '/JavaScript','/JS','/XFA','/EmbeddedFiles','/RichMediaContent','/Launch','/Perms','/AF','/EF','/OutputIntents','/ViewerPreferences','/CharProcs'}

def inspect_graph(reader):
    seen = set()
    count = 0
    def walk(obj, depth):
        nonlocal count
        if depth > MAX_DEPTH:
            raise InputError('PDF object nesting exceeds the supported limit.')
        if isinstance(obj, IndirectObject):
            key = (obj.idnum, obj.generation)
            if key in seen:
                return
            seen.add(key)
            count += 1
            if count > MAX_OBJECTS:
                raise InputError('PDF object count exceeds the supported limit.')
            obj = obj.get_object()
        if isinstance(obj, DictionaryObject):
            bad = FORBIDDEN.intersection(obj.keys())
            if bad:
                raise InputError('Unsupported interactive, layered or active PDF feature: ' + ', '.join(sorted(bad)))
            if obj.get('/Type') in ('/Sig','/OCG','/OCMD','/Filespec','/EmbeddedFile') or obj.get('/S') in ('/JavaScript','/Launch','/GoToR','/SubmitForm','/ImportData'):
                raise InputError('Active actions, external content and signed documents are unsupported.')
            if obj.get('/Subtype') == '/Type3':
                raise InputError('Type 3 fonts are unsupported; flatten the document first.')
            if isinstance(obj, StreamObject):
                if '/F' in obj:
                    raise InputError('External PDF stream data is unsupported.')
                if obj.get('/Subtype') == '/Form' or obj.get('/PatternType') == 1:
                    inspect_content(obj, reader)
            for key, value in obj.items():
                if key != '/Parent':
                    walk(value, depth + 1)
        elif isinstance(obj, ArrayObject):
            for value in obj:
                walk(value, depth + 1)
    walk(reader.trailer, 0)

def inspect_content(stream, reader):
    if stream is None:
        return
    content = stream if isinstance(stream, ContentStream) else ContentStream(stream, reader)
    if len(content.get_data()) > 32 * 1024 * 1024:
        raise InputError('A decoded content stream exceeds the 32 MiB limit.')
    operations = content.operations
    if len(operations) > 1_000_000:
        raise InputError('A content stream exceeds the operator limit.')
    for operands, operator in operations:
        if operator in (b'BDC', b'BMC', b'DP', b'MP') and operands and operands[0] == '/OC':
            raise InputError('Optional-content marked sections are unsupported.')

@dataclass
class Document:
    reader: PdfReader
    info: dict
    geometry: list

def inspect_pdf(path, name, dpi):
    size = path.stat().st_size
    if not size or size > MAX_BYTES:
        raise InputError('Each PDF must be nonempty and at most 16 MiB.')
    data = path.read_bytes()
    if not data.startswith(b'%PDF-') or not data.rstrip().endswith(b'%%EOF'):
        raise InputError('Malformed PDF header or end marker.')
    try:
        reader = PdfReader(path, strict=True)
        if reader.is_encrypted:
            raise InputError('Encrypted PDFs are unsupported, even with an empty password.')
        n = len(reader.pages)
        if not n or n > MAX_SIDES or n % 2:
            raise InputError('Each PDF must contain an even number of sides, from 2 through 80.')
        inspect_graph(reader)
        geometry = []
        for page in reader.pages:
            inspect_content(page.get_contents(), reader)
            boxes = [[float(v) for v in getattr(page, box)] for box in ('mediabox','cropbox','trimbox','bleedbox','artbox')]
            if any(not math.isfinite(v) for box in boxes for v in box):
                raise InputError('Non-finite page geometry is unsupported.')
            media = boxes[0]
            if media[:2] != [0.0, 0.0] or any(box != media for box in boxes):
                raise InputError('All page boxes must be equal and start at (0, 0).')
            if not (36 <= media[2] <= 2000 and 36 <= media[3] <= 2000):
                raise InputError('Page width and height must be between 36 and 2000 points.')
            if float(page.get('/UserUnit', 1)) != 1 or float(page.get('/Rotate', 0)) != 0:
                raise InputError('Rotated pages and non-default UserUnit are unsupported; flatten them first.')
            px = math.ceil(media[2] * dpi / 72) * math.ceil(media[3] * dpi / 72)
            if px > MAX_SIDE_PIXELS:
                raise InputError('A side exceeds the 20-million-pixel rendering limit.')
            geometry.append(media)
        if any(g != geometry[0] for g in geometry):
            raise InputError('Mixed page sizes are unsupported; use one fixed sheet size per document.')
        return Document(reader, dict(name=safe_name(name), sha256=digest(data), bytes=size,
            sideCount=n, sheetCount=n//2, geometryPoints=geometry[0]), geometry)
    except InputError:
        raise
    except Exception as exc:
        raise InputError('Malformed or unsupported PDF structure.') from exc

def parse_ppm(data):
    # Poppler P6 only. Parse header without stripping pixels that equal whitespace.
    pos = 0
    tokens = []
    while len(tokens) < 4:
        while pos < len(data) and data[pos] in b' \t\r\n': pos += 1
        if pos < len(data) and data[pos] == 35:
            pos = data.index(b'\n',pos) + 1
            continue
        start = pos
        while pos < len(data) and data[pos] not in b' \t\r\n': pos += 1
        tokens.append(data[start:pos])
    if tokens[0] != b'P6' or tokens[3] != b'255' or pos >= len(data):
        raise InputError('Unexpected renderer output.')
    if data[pos:pos+2] == b'\r\n': pos += 2
    else: pos += 1
    w, h = int(tokens[1]), int(tokens[2])
    if w <= 0 or h <= 0 or w*h > MAX_SIDE_PIXELS or len(data)-pos != w*h*3:
        raise InputError('Invalid renderer dimensions or pixel count.')
    return w, h, data[pos:]

def thumbnail_png(w, h, rgb, max_width=450):
    ratio = min(1, max_width / max(w,h))
    tw, th = max(1,int(w*ratio)), max(1,int(h*ratio))
    raw = bytearray()
    for y in range(th):
        raw.append(0)
        sy = min(h-1,int(y/ratio))
        for x in range(tw):
            sx = min(w-1,int(x/ratio)); start = (sy*w+sx)*3
            raw.extend(rgb[start:start+3])
    def chunk(tag, payload):
        return struct.pack('>I',len(payload))+tag+payload+struct.pack('>I',zlib.crc32(tag+payload)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',tw,th,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')

def render_sides(path, doc, dpi, work, prefix, progress):
    hashes = []
    for i, geometry in enumerate(doc.geometry):
        progress(f'Rendering {prefix} side {i+1} of {len(doc.geometry)}')
        stem = work / 'render'
        try:
            process = subprocess.run(['pdftoppm','-f',str(i+1),'-l',str(i+1),'-singlefile',
                '-r',str(dpi),'-aa','yes','-aaVector','yes',str(path),str(stem)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=25, check=False)
        except subprocess.TimeoutExpired as exc:
            raise InputError('A PDF side exceeded the 25-second renderer limit.') from exc
        if process.returncode or process.stderr.strip():
            # Diagnostics stay local. Bound and normalize untrusted renderer text;
            # never ignore warnings or dump an input document into a log.
            diagnostic = ' '.join(process.stderr.decode('utf-8', errors='replace').split())
            diagnostic = ''.join(c for c in diagnostic if c.isprintable())[:800]
            detail = f' Exit code {process.returncode}.'
            if diagnostic:
                detail += ' Renderer diagnostic: ' + diagnostic
            raise InputError('The renderer reported an error or warning; repair or flatten the PDF first.' + detail)
        ppm = stem.with_suffix('.ppm')
        if not ppm.exists() or ppm.stat().st_size > MAX_SIDE_PIXELS*3+1024:
            raise InputError('Renderer output exceeds the supported limit.')
        w,h,rgb = parse_ppm(ppm.read_bytes()); ppm.unlink()
        expected = (math.ceil(geometry[2]*dpi/72), math.ceil(geometry[3]*dpi/72))
        if (w,h) != expected:
            raise InputError('Renderer dimensions disagree with accepted geometry.')
        header = json.dumps({'dpi':dpi,'geometry':geometry,'width':w,'height':h,'mode':'RGB'},sort_keys=True,separators=(',',':')).encode()
        hashes.append(digest(header+b'\0'+rgb))
        previews = work / 'preview' / prefix
        previews.mkdir(parents=True,exist_ok=True)
        (previews / f'{i+1}.png').write_bytes(thumbnail_png(w,h,rgb))
    return hashes

def report_html(result):
    esc = html.escape
    rows = ''.join(f'<tr><td>{r["newSheet"]}</td><td>{r["action"]}{" (forced)" if r["forced"] else ""}</td><td>{r["oldSheet"] or "—"}</td><td>{r["patchSheet"] or "—"}</td></tr>' for r in result['assembly'])
    warnings = ''.join(f'<li>{esc(w)}</li>' for w in result['warnings'])
    export_note = ('Replacement sides were independently rerendered in this run and matched their new-source fingerprints. This validates raster extraction only, not physical print identity.' if result['summary']['reprint'] else 'No replacement PDF was needed, so no replacement-side rerender was performed.')
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><title>Sheet Patch assembly evidence</title><style>body{{font:16px system-ui;max-width:900px;margin:40px auto;padding:20px;color:#17382e;background:#faf9f2}}h1{{font-size:42px}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;padding:12px;border-bottom:1px solid #b8c7be}}code{{overflow-wrap:anywhere}}.warning{{padding:18px;background:#fff1d3}}@media print{{body{{margin:0}}}}</style><h1>Sheet Patch</h1><p>Ordered duplex revision · evidence packet · {result['dpi']} DPI</p><p>Old: {esc(result['old']['name'])}<br>New: {esc(result['new']['name'])}</p><div class="warning"><strong>Review before reuse or printing</strong><ul>{warnings}</ul></div><h2>Assembly in new sheet order</h2><p>Label every old physical sheet with its original number before moving any sheet. Each row is one intact front/back pair. Keep/move rows take an old sheet; reprint rows take a replacement sheet. Gather the new stack in row order. Retire unused old sheets only after checking the complete stack.</p><table><thead><tr><th>New sheet</th><th>Action</th><th>Old source</th><th>Replacement sheet</th></tr></thead><tbody>{rows}</tbody></table><p>Retire old sheets: {', '.join(map(str,result['retire'])) or 'none'}.</p><p>{result['summary']['reprint']} replacement sheets / {result['summary']['reprint']*2} PDF sides. {'No replacement PDF is included because all new sheets have reuse candidates.' if not result['summary']['reprint'] else 'replacement.pdf contains complete front/back pairs in ascending new-sheet order; it is not a complete new document.'}</p><h2>Provenance</h2><p>Old SHA-256: <code>{result['old']['sha256']}</code><br>New SHA-256: <code>{result['new']['sha256']}</code></p><p>Renderer: {esc(result['renderer'])}. {export_note}</p><p>The JSON file includes every ordered-side fingerprint and mapping. Previews remain in the local workbench; originals are not included in the packet.</p></html>'''

def analyze(old_path, new_path, work, old_name='old.pdf', new_name='new.pdf', dpi=144, force=(), progress=lambda _:None):
    if type(dpi) is not int or dpi not in DPI_OPTIONS:
        raise InputError('DPI must be 72, 144 or 216.')
    if not isinstance(force,(list,tuple,set)) or any(type(i) is not int for i in force):
        raise InputError('Force-reprint values must be integer sheet numbers.')
    start = time.monotonic()
    handler = StrictPdfLog(); logger = logging.getLogger('pypdf'); logger.addHandler(handler)
    try:
        progress('Validating flattened PDFs and resource budget')
        old, new = inspect_pdf(old_path,old_name,dpi), inspect_pdf(new_path,new_name,dpi)
        total_pixels = sum(math.ceil(g[2]*dpi/72)*math.ceil(g[3]*dpi/72) for d in (old,new) for g in d.geometry)
        if total_pixels > MAX_TOTAL_PIXELS:
            raise InputError('Both PDFs exceed the 200-million-pixel input budget at this DPI. Use a lower DPI or smaller documents.')
        if any(i < 1 or i > new.info['sheetCount'] for i in force):
            raise InputError('Force-reprint sheet number is outside the new document.')
        version = subprocess.run(['pdftoppm','-v'],capture_output=True,timeout=5,check=True)
        renderer = (version.stderr or version.stdout).decode(errors='replace').splitlines()[0]
        oh = render_sides(old_path,old,dpi,work,'old',progress)
        nh = render_sides(new_path,new,dpi,work,'new',progress)
        op, np = list(zip(oh[::2],oh[1::2])), list(zip(nh[::2],nh[1::2]))
        forced_indices = {i-1 for i in force}
        assembly, retire = plan_pairs(op,np,forced_indices)
        verify_assembly(op,np,assembly,retire,forced_indices)
        replacements = [r['newSheet'] for r in assembly if r['action']=='reprint']
        if replacements:
            progress('Writing and independently rerendering complete replacement pairs')
            writer = PdfWriter()
            for sheet in replacements:
                writer.add_page(new.reader.pages[2*(sheet-1)])
                writer.add_page(new.reader.pages[2*(sheet-1)+1])
            patch = work/'replacement.pdf'
            writer.write(patch)
            # Export may exceed input bytes due to object copies; same safety cap.
            exported = inspect_pdf(patch,'replacement.pdf',dpi)
            ph = render_sides(patch,exported,dpi,work,'patch',progress)
            expected = [nh[j] for i in replacements for j in (2*(i-1),2*(i-1)+1)]
            if ph != expected:
                raise InputError('Export verification failed: replacement sides differ from their source.')
        summary = {action:sum(r['action']==action for r in assembly) for action in ('keep','move','reprint')}
        summary.update(retire=len(retire),reused=summary['keep']+summary['move'])
        result = dict(schemaVersion=1,tool='sheet-patch',version='0.1.0',dpi=dpi,
            matchKind='ordered-pair raster candidate',renderer=renderer,
            renderOptions=['RGB','-aa yes','-aaVector yes','full page; equal media/crop/trim/bleed/art boxes'],
            old=old.info,new=new.info,summary=summary,assembly=assembly,retire=retire,
            oldSideHashes=oh,newSideHashes=nh,warnings=WARNINGS,
            verification=dict(replacementRerenderPerformed=bool(replacements),replacementRerenderMatched=True,replacementSideCount=len(replacements)*2,
                uniqueOldConsumption=True,newSheetCoverage=len(assembly),inputPixels=total_pixels,
                elapsedSeconds=round(time.monotonic()-start,3)))
        (work/'plan.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        (work/'assembly.html').write_text(report_html(result),encoding='utf-8')
        with zipfile.ZipFile(work/'packet.zip','w',zipfile.ZIP_DEFLATED) as packet:
            for name in ['plan.json','assembly.html']+(['replacement.pdf'] if replacements else []):
                packet.write(work/name,name)
        progress('Verified packet ready')
        return result
    finally:
        logger.removeHandler(handler)
