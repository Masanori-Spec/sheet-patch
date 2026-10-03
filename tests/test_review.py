"""Independent security/correctness regression review of Sheet Patch."""
from io import BytesIO
from pathlib import Path
import json
import os
import signal
import sys
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject,
                          FloatObject, NameObject, NumberObject, TextStringObject)
from sheet_patch import engine
from sheet_patch.demo import make_pdf
from sheet_patch.engine import InputError, analyze, inspect_pdf, plan_pairs
from sheet_patch.runner import Job, JobManager


def modified_pdf(mutator):
    writer = PdfWriter()
    writer.clone_document_from_reader(PdfReader(BytesIO(make_pdf(['front', 'back']))))
    mutator(writer)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def with_resource_layer(writer):
    group = DictionaryObject({NameObject('/Type'): NameObject('/OCG'),
                              NameObject('/Name'): TextStringObject('hidden resource layer')})
    group_ref = writer._add_object(group)
    for page in writer.pages:
        page['/Resources'][NameObject('/Properties')] = DictionaryObject({NameObject('/L0'): group_ref})
        content = DecodedStreamObject()
        content.set_data(b'/OC /L0 BDC\n' + page.get_contents().get_data() + b'\nEMC')
        page[NameObject('/Contents')] = writer._add_object(content)


def with_associated_file(writer):
    content = DecodedStreamObject()
    content.set_data(b'This unrequested attachment must not survive export.')
    content[NameObject('/Type')] = NameObject('/EmbeddedFile')
    filespec = DictionaryObject({NameObject('/Type'): NameObject('/Filespec'),
        NameObject('/F'): TextStringObject('extra.txt'),
        NameObject('/AFRelationship'): NameObject('/Data'),
        NameObject('/EF'): DictionaryObject({NameObject('/F'): writer._add_object(content)})})
    writer.pages[0][NameObject('/AF')] = ArrayObject([writer._add_object(filespec)])


class ReviewPdfTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def file(self, name, data):
        target = self.root / name
        target.write_bytes(data)
        return target

    def inputs(self, old, new):
        return self.file('old.pdf', old), self.file('new.pdf', new)

    def test_reject_optional_content_without_catalog_properties(self):
        with self.assertRaises(InputError):
            inspect_pdf(self.file('layer.pdf', modified_pdf(with_resource_layer)), 'layer.pdf', 72)

    def test_reject_associated_embedded_file_without_name_tree(self):
        with self.assertRaises(InputError):
            inspect_pdf(self.file('attachment.pdf', modified_pdf(with_associated_file)), 'attachment.pdf', 72)

    def test_reject_direct_optional_content_markers(self):
        for marker in (b'/OC <<>> BDC', b'/O#43 <<>> BDC', b'/OC BMC', b'/OC MP', b'/OC <<>> DP'):
            def add_marker(writer):
                content = DecodedStreamObject()
                content.set_data(marker + b'\n' + writer.pages[0].get_contents().get_data() + b'\nEMC')
                writer.pages[0][NameObject('/Contents')] = writer._add_object(content)
            with self.subTest(marker=marker), self.assertRaises(InputError):
                inspect_pdf(self.file('marked.pdf', modified_pdf(add_marker)), 'marked', 72)

    def test_reject_optional_content_in_form_xobject(self):
        def add_form(writer):
            form = DecodedStreamObject()
            form.set_data(b'/OC <<>> BDC 0 0 10 10 re f EMC')
            form.update({NameObject('/Type'): NameObject('/XObject'),
                         NameObject('/Subtype'): NameObject('/Form'),
                         NameObject('/BBox'): ArrayObject([NumberObject(n) for n in (0, 0, 20, 20)])})
            writer.pages[0]['/Resources'][NameObject('/XObject')] = DictionaryObject({NameObject('/LayerForm'): writer._add_object(form)})
        with self.assertRaises(InputError):
            inspect_pdf(self.file('form.pdf', modified_pdf(add_form)), 'form', 72)

    def test_reject_optional_content_in_tiling_pattern(self):
        def add_pattern(writer):
            pattern = DecodedStreamObject()
            pattern.set_data(b'/OC <<>> BDC 0 1 0 rg 0 0 10 10 re f EMC')
            pattern.update({NameObject('/Type'): NameObject('/Pattern'),
                NameObject('/PatternType'): NumberObject(1), NameObject('/PaintType'): NumberObject(1),
                NameObject('/TilingType'): NumberObject(1), NameObject('/XStep'): NumberObject(20),
                NameObject('/YStep'): NumberObject(20), NameObject('/Resources'): DictionaryObject(),
                NameObject('/BBox'): ArrayObject([NumberObject(n) for n in (0, 0, 20, 20)])})
            writer.pages[0]['/Resources'][NameObject('/Pattern')] = DictionaryObject({NameObject('/P1'): writer._add_object(pattern)})
        with self.assertRaises(InputError):
            inspect_pdf(self.file('pattern.pdf', modified_pdf(add_pattern)), 'pattern', 72)

    def test_reject_optional_content_in_type3_font_charproc(self):
        def add_font(writer):
            glyph = DecodedStreamObject()
            glyph.set_data(b'600 0 d0 /OC <<>> BDC 0 0 500 500 re f EMC')
            font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                NameObject('/Subtype'): NameObject('/Type3'),
                NameObject('/FontBBox'): ArrayObject([NumberObject(n) for n in (0, 0, 500, 500)]),
                NameObject('/FontMatrix'): ArrayObject([FloatObject(n) for n in (.001, 0, 0, .001, 0, 0)]),
                NameObject('/FirstChar'): NumberObject(65), NameObject('/LastChar'): NumberObject(65),
                NameObject('/Widths'): ArrayObject([NumberObject(600)]),
                NameObject('/Resources'): DictionaryObject(),
                NameObject('/Encoding'): DictionaryObject({NameObject('/Type'): NameObject('/Encoding'),
                    NameObject('/Differences'): ArrayObject([NumberObject(65), NameObject('/A')])}),
                NameObject('/CharProcs'): DictionaryObject({NameObject('/A'): writer._add_object(glyph)})})
            writer.pages[0]['/Resources']['/Font'][NameObject('/LayerFont')] = writer._add_object(font)
        with self.assertRaises(InputError):
            inspect_pdf(self.file('type3.pdf', modified_pdf(add_font)), 'type3', 72)

    def test_reject_document_scoped_print_state(self):
        for key, value in (('/OutputIntents', ArrayObject()), ('/ViewerPreferences', DictionaryObject())):
            with self.subTest(key=key), self.assertRaises(InputError):
                inspect_pdf(self.file('print-state.pdf', modified_pdf(
                    lambda writer: writer.root_object.__setitem__(NameObject(key), value))), 'print-state', 72)

    def test_unchanged_report_does_not_claim_export_rerender(self):
        old, new = self.inputs(make_pdf(['front', 'back']), make_pdf(['front', 'back']))
        result = analyze(old, new, self.root, dpi=72)
        report = (self.root / 'assembly.html').read_text()
        self.assertEqual(result['verification']['replacementSideCount'], 0)
        self.assertNotIn('Replacement sides were independently rerendered in this run', report)
        self.assertIn('no replacement-side rerender was performed', report)

    def test_reject_all_nonzero_boxes(self):
        for box in ('mediabox', 'cropbox', 'trimbox', 'bleedbox', 'artbox'):
            with self.subTest(box=box):
                blob = modified_pdf(lambda w: setattr(getattr(w.pages[0], box), 'lower_left', (1, 0)))
                with self.assertRaises(InputError):
                    inspect_pdf(self.file(box + '.pdf', blob), box, 72)

    def test_reject_invalid_geometry_bounds_and_units(self):
        mutators = [
            lambda w: setattr(w.pages[0].mediabox, 'upper_right', (35, 297)),
            lambda w: setattr(w.pages[0].mediabox, 'upper_right', (2001, 297)),
            lambda w: w.pages[0].__setitem__(NameObject('/UserUnit'), FloatObject(1.01)),
            lambda w: w.pages[0].__setitem__(NameObject('/Rotate'), NumberObject(360)),
        ]
        for number, mutate in enumerate(mutators):
            with self.subTest(number=number), self.assertRaises(InputError):
                inspect_pdf(self.file(f'geometry{number}.pdf', modified_pdf(mutate)), 'bad', 72)

    def test_reject_too_many_sides(self):
        with self.assertRaisesRegex(InputError, '80'):
            inspect_pdf(self.file('large.pdf', make_pdf(['blank'] * 82)), 'large', 72)

    def test_export_is_exact_ordered_new_pairs_by_independent_render(self):
        old, new = self.inputs(make_pdf(['A front', 'A back', 'B front', 'B back']),
                               make_pdf(['C front', 'C back', 'A front', 'A back', 'D front', 'D back']))
        result = analyze(old, new, self.root, dpi=72)
        self.assertEqual([row['action'] for row in result['assembly']], ['reprint', 'move', 'reprint'])
        self.assertEqual([row['patchSheet'] for row in result['assembly']], [1, None, 2])
        self.assertEqual(result['retire'], [2])
        self.assertEqual(len(PdfReader(self.root / 'replacement.pdf').pages), 4)
        for patch_page, new_page in enumerate((1, 2, 5, 6), start=1):
            ppm = []
            for tag, source, page in [('original', new, new_page),
                                      ('replacement', self.root / 'replacement.pdf', patch_page)]:
                stem = self.root / tag
                subprocess.run(['pdftoppm', '-f', str(page), '-l', str(page), '-singlefile',
                                '-r', '72', '-aa', 'yes', '-aaVector', 'yes', str(source), str(stem)],
                               check=True, capture_output=True, timeout=25)
                ppm.append(stem.with_suffix('.ppm').read_bytes())
            self.assertEqual(*ppm)
        with zipfile.ZipFile(self.root / 'packet.zip') as packet:
            self.assertEqual(packet.read('replacement.pdf'), (self.root / 'replacement.pdf').read_bytes())
            self.assertEqual(json.loads(packet.read('plan.json')), result)
            self.assertNotIn('old.pdf', packet.namelist())
            self.assertNotIn('new.pdf', packet.namelist())

    def test_export_pixel_corruption_prevents_verified_packet(self):
        old, new = self.inputs(make_pdf(['old front', 'old back']), make_pdf(['new front', 'new back']))
        write = PdfWriter.write
        def swap_content(writer, target):
            writer.pages[0][NameObject('/Contents')] = writer.pages[1].raw_get('/Contents')
            return write(writer, target)
        with patch('sheet_patch.engine.PdfWriter.write', swap_content):
            with self.assertRaisesRegex(InputError, 'Export verification failed'):
                analyze(old, new, self.root, dpi=72)
        self.assertFalse((self.root / 'packet.zip').exists())
        self.assertFalse((self.root / 'plan.json').exists())

    def test_malformed_and_active_pdf_never_call_renderer(self):
        valid = self.file('valid.pdf', make_pdf(['front', 'back']))
        active = modified_pdf(lambda w: w.root_object.__setitem__(NameObject('/OpenAction'), DictionaryObject()))
        for number, blob in enumerate((b'not a PDF', active, make_pdf(['odd']))):
            with self.subTest(number=number), patch('sheet_patch.engine.subprocess.run') as run:
                with self.assertRaises(InputError):
                    analyze(self.file(f'bad{number}.pdf', blob), valid, self.root, dpi=72)
                run.assert_not_called()

    def test_renderer_warning_prevents_packet(self):
        path = self.file('input.pdf', make_pdf(['front', 'back']))
        doc = inspect_pdf(path, 'input', 72)
        with patch('sheet_patch.engine.subprocess.run', return_value=subprocess.CompletedProcess([], 0, stderr=b'Warning')):
            with self.assertRaisesRegex(InputError, 'warning'):
                engine.render_sides(path, doc, 72, self.root, 'new', lambda _: None)
        self.assertFalse((self.root / 'packet.zip').exists())


class ReviewMatchingTests(unittest.TestCase):
    def test_same_front_or_same_back_does_not_match(self):
        rows, retire = plan_pairs([('a', 'b'), ('c', 'd')], [('a', 'd'), ('c', 'b')])
        self.assertEqual([row['action'] for row in rows], ['reprint', 'reprint'])
        self.assertEqual(retire, [1, 2])

    def test_duplicates_cannot_multiply_physical_supply(self):
        rows, retire = plan_pairs([('a', 'b'), ('a', 'b')], [('a', 'b')] * 4)
        self.assertEqual([row['action'] for row in rows], ['keep', 'keep', 'reprint', 'reprint'])
        self.assertEqual([row['oldSheet'] for row in rows], [1, 2, None, None])
        self.assertEqual([row['patchSheet'] for row in rows], [None, None, 1, 2])
        self.assertEqual(retire, [])


class ReviewRunnerTests(unittest.TestCase):
    @staticmethod
    def wait(job, timeout=20):
        until = time.monotonic() + timeout
        while job.snapshot()['status'] == 'running' and time.monotonic() < until:
            time.sleep(.02)
        return job.snapshot()

    def test_immediate_cancel_repeated_start_and_private_cleanup(self):
        manager = JobManager()
        blob = make_pdf(['front', 'back'])
        locations = []
        try:
            for _ in range(5):
                job = manager.start(blob, blob, dpi=72)
                locations.append(job.work)
                self.assertEqual(job.work.stat().st_mode & 0o777, 0o700)
                self.assertEqual(job.cancel()['status'], 'cancelled')
                self.assertFalse(job.process.is_alive())
                self.assertNotIn('result', job.snapshot())
            job = manager.start(blob, blob, dpi=72)
            locations.append(job.work)
            self.assertEqual(self.wait(job)['status'], 'done')
            self.assertEqual(job.snapshot()['result']['summary']['keep'], 1)
            self.assertTrue(all(not location.exists() for location in locations[:-1]))
        finally:
            manager.close()
        self.assertTrue(all(not location.exists() for location in locations))

    @staticmethod
    def process_executing(pid):
        try:
            return Path(f'/proc/{pid}/stat').read_text().split()[2] not in ('Z', 'X')
        except FileNotFoundError:
            return False

    def descendant_job(self, trigger, renderer_error=False, timeout=20):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / 'descendant.pid'
            renderer = root / 'pdftoppm'
            renderer.write_text(f'#!{sys.executable}\n'
                'import os, subprocess, sys, time\n'
                'if "-v" in sys.argv:\n'
                '    print("pdftoppm version review-test", file=sys.stderr)\n'
                '    raise SystemExit(0)\n'
                'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n'
                'with open(os.environ["SHEET_REVIEW_CHILD_PID"], "w") as output: output.write(f"{child.pid} {os.getpgid(child.pid)}")\n'
                'if os.environ.get("SHEET_REVIEW_RENDER_ERROR") == "1": raise SystemExit(1)\n'
                'time.sleep(60)\n')
            renderer.chmod(0o700)
            with patch.dict(os.environ, {'PATH': str(root) + os.pathsep + os.environ['PATH'],
                                         'SHEET_REVIEW_CHILD_PID': str(marker),
                                         'SHEET_REVIEW_RENDER_ERROR': '1' if renderer_error else '0'}):
                blob = make_pdf(['front', 'back'])
                job = Job(blob, blob, dpi=72)
            child_pid = None
            try:
                deadline = time.monotonic() + 10
                while (not marker.exists() or not marker.stat().st_size) and time.monotonic() < deadline and job.snapshot()['status'] == 'running':
                    time.sleep(.02)
                self.assertTrue(marker.exists(), job.snapshot())
                child_pid, child_pgid = map(int, marker.read_text().split())
                self.assertEqual(child_pgid, job.process.pid)
                trigger(job)
                state = self.wait(job, timeout=timeout)
                self.assertIn(state['status'], ('cancelled', 'error'))
                self.assertFalse(job.process.is_alive())
                deadline = time.monotonic() + 3
                while self.process_executing(child_pid) and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertFalse(self.process_executing(child_pid), 'renderer descendant survived worker shutdown')
                return state
            finally:
                job.close()
                if child_pid and self.process_executing(child_pid):
                    os.kill(child_pid, signal.SIGKILL)

    @unittest.skipUnless(Path("/proc").exists(), "Process descendant observation uses Linux /proc")
    def test_cancel_kills_renderer_grandchild(self):
        self.descendant_job(lambda job: job.cancel())

    @unittest.skipUnless(Path("/proc").exists(), "Process descendant observation uses Linux /proc")
    def test_worker_crash_kills_renderer_grandchild(self):
        self.descendant_job(lambda job: os.kill(job.process.pid, signal.SIGKILL))

    @unittest.skipUnless(Path("/proc").exists(), "Process descendant observation uses Linux /proc")
    def test_handled_renderer_error_kills_grandchild(self):
        self.descendant_job(lambda job: None, renderer_error=True)

    @unittest.skipUnless(Path("/proc").exists(), "Process descendant observation uses Linux /proc")
    def test_renderer_timeout_kills_grandchild(self):
        state = self.descendant_job(lambda job: None, timeout=35)
        self.assertEqual(state['status'], 'error')
        self.assertIn('25-second renderer limit', state['error'])

    def test_bad_job_does_not_poison_next_run(self):
        manager = JobManager()
        blob = make_pdf(['front', 'back'])
        try:
            job = manager.start(b'broken', blob, dpi=72)
            old_id, old_work = job.id, job.work
            self.assertEqual(self.wait(job)['status'], 'error')
            self.assertIsNone(job.result)
            new_job = manager.start(blob, blob, dpi=72)
            self.assertIsNone(manager.get(old_id))
            self.assertFalse(old_work.exists())
            self.assertEqual(self.wait(new_job)['status'], 'done')
        finally:
            manager.close()


class ReviewRendererDiagnosticTests(unittest.TestCase):
    def test_known_fontcache_notices_preserve_unicode_paths_order_and_deduplicate(self):
        lines = ['Unable to revert mtime: /usr/share/fonts',
                 'Unable to revert mtime: /tmp/日本語 Fonts']
        notices = []
        engine.check_renderer_diagnostics(0, ('\n'.join(lines + lines) + '\n').encode(), notices)
        self.assertEqual(notices, lines)

    def test_malformed_utf8_is_not_normalized_into_known_notice(self):
        for diagnostic in (b'Unable to revert mtime: /fonts/\xff\n',
                           b'Unable to revert mtime: /fonts/\xc0\xaf\n'):
            with self.subTest(diagnostic=diagnostic), self.assertRaises(InputError):
                engine.check_renderer_diagnostics(0, diagnostic, [])

    def test_control_framing_is_not_stripped_into_known_notice(self):
        notice = b'Unable to revert mtime: /usr/share/fonts'
        for diagnostic in (b'\t' + notice + b'\n', b'\v' + notice + b'\n',
                           notice + b'\v\n', notice + b'\f\n',
                           notice + b'\x1c\n'):
            with self.subTest(diagnostic=diagnostic), self.assertRaises(InputError):
                engine.check_renderer_diagnostics(0, diagnostic, [])

    def test_mixed_warning_never_commits_partial_environment_notices(self):
        known = b'Unable to revert mtime: /usr/share/fonts\n'
        for unknown in (b'Syntax Warning: font substitution\n', b'Syntax Error: damaged font\n',
                        b'Fontconfig error: Cannot load default config file\n',
                        b'Unable to revert mtime: relative/path\n'):
            for data in (known + unknown, unknown + known):
                notices = ['existing notice']
                with self.subTest(data=data), self.assertRaises(InputError):
                    engine.check_renderer_diagnostics(0, data, notices)
                self.assertEqual(notices, ['existing notice'])

    def test_unknown_and_nonzero_remain_fatal_with_bounded_diagnostic(self):
        known = b'Unable to revert mtime: /usr/share/fonts\n'
        for returncode, diagnostic in ((1, known), (-9, known), (0, b'x' * 10000),
                                       (0, b'Unable to revert mtime: /' + b'x' * 513)):
            notices = []
            with self.subTest(returncode=returncode), self.assertRaises(InputError) as caught:
                engine.check_renderer_diagnostics(returncode, diagnostic, notices)
            self.assertEqual(notices, [])
            self.assertLess(len(str(caught.exception)), 1000)


if __name__ == '__main__':
    unittest.main()
