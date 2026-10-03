from collections import Counter
from io import BytesIO
from pathlib import Path
import itertools
import json
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from pypdf import PdfReader,PdfWriter
from pypdf.generic import NameObject,DictionaryObject,ArrayObject,NumberObject,FloatObject
from sheet_patch.engine import plan_pairs,verify_assembly,check_renderer_diagnostics,analyze,inspect_pdf,InputError,parse_ppm,report_html,MAX_BYTES
from sheet_patch.demo import make_pdf,demo_files

class MatchingTests(unittest.TestCase):
    def test_exhaustive_multiset_optimum(self):
        seqs=[t for n in range(5) for t in itertools.product('ABC',repeat=n)]
        checked=0
        for old in seqs:
            for new in seqs:
                op=[(v,'back') for v in old];np=[(v,'back') for v in new]
                rows,retire=plan_pairs(op,np)
                used=[r['oldSheet'] for r in rows if r['oldSheet']]
                optimum=sum(min(Counter(old)[v],Counter(new)[v]) for v in 'ABC')
                self.assertEqual(len(used),optimum)
                self.assertEqual(len(used),len(set(used)))
                self.assertEqual(set(used)|set(retire),set(range(1,len(old)+1)))
                self.assertFalse(set(used)&set(retire))
                for i,r in enumerate(rows):
                    self.assertEqual(r['newSheet'],i+1)
                    if r['oldSheet']:self.assertEqual(op[r['oldSheet']-1],np[i])
                    if i<len(old) and old[i]==new[i]:self.assertEqual(r['action'],'keep')
                checked+=1
        self.assertEqual(checked,14641)
    def test_force_releases_old_supply(self):
        rows,retire=plan_pairs([('a','b')],[('a','b'),('a','b')],{0})
        self.assertEqual([r['action'] for r in rows],['reprint','move'])
        self.assertEqual(rows[1]['oldSheet'],1);self.assertEqual(retire,[])
    def test_forced_multiset_optimum(self):
        seqs=[t for n in range(4) for t in itertools.product('AB',repeat=n)]
        for old,new in itertools.product(seqs,repeat=2):
            for mask in range(1<<len(new)):
                force={i for i in range(len(new)) if mask&(1<<i)}
                rows,_=plan_pairs([(v,v) for v in old],[(v,v) for v in new],force)
                available=Counter(old);demand=Counter(v for i,v in enumerate(new) if i not in force)
                self.assertEqual(sum(r['oldSheet'] is not None for r in rows),sum(min(available[v],demand[v]) for v in 'AB'))
                self.assertTrue(all(rows[i]['action']=='reprint' for i in force))
    def test_runtime_verifier_rejects_duplicate_consumption(self):
        old=[('a','b')];new=[('a','b'),('a','b')]
        rows,retire=plan_pairs(old,new)
        verify_assembly(old,new,rows,retire,set())
        rows[1].update(oldSheet=1,action='move',patchSheet=None)
        with self.assertRaises(InputError):verify_assembly(old,new,rows,retire,set())

    def test_front_back_order_is_indivisible(self):
        rows,_=plan_pairs([('a','b'),('c','d')],[('b','a'),('a','d')])
        self.assertEqual([r['action'] for r in rows],['reprint','reprint'])
    def test_invalid_force(self):
        for force in ({-1},{1},{True}):
            with self.assertRaises(InputError):plan_pairs([], [('a','b')],force)

class PdfTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def path(self,name,blob):
        p=self.root/name;p.write_bytes(blob);return p
    def run_plan(self,old,new,**kwargs):
        work=self.root/'work';work.mkdir()
        return analyze(self.path('old.pdf',old),self.path('new.pdf',new),work,dpi=72,**kwargs)
    def test_demo_verified_complete_pairs(self):
        r=self.run_plan(*demo_files())
        self.assertEqual(r['summary'],dict(keep=1,move=1,reprint=2,retire=1,reused=2))
        self.assertEqual(r['retire'],[2])
        replacement=PdfReader(self.root/'work'/'replacement.pdf')
        self.assertEqual(len(replacement.pages),4)
        self.assertIn('B front',replacement.pages[0].extract_text())
        self.assertIn('B back revised',replacement.pages[1].extract_text())
        self.assertIn('D front',replacement.pages[2].extract_text())
        self.assertTrue(r['verification']['replacementRerenderMatched'])
        with zipfile.ZipFile(self.root/'work'/'packet.zip') as z:
            self.assertEqual(set(z.namelist()),{'plan.json','assembly.html','replacement.pdf'})
            self.assertEqual(json.loads(z.read('plan.json')),r)
    def test_unchanged_no_empty_pdf(self):
        blob=make_pdf(['a','b']);r=self.run_plan(blob,blob)
        self.assertEqual(r['summary']['keep'],1)
        self.assertFalse((self.root/'work'/'replacement.pdf').exists())
    def test_blank_duplicates_delete(self):
        r=self.run_plan(make_pdf(['blank']*6),make_pdf(['blank']*4))
        self.assertEqual(r['summary']['keep'],2);self.assertEqual(r['retire'],[3])
    def test_changed_back(self):
        r=self.run_plan(make_pdf(['front','back']),make_pdf(['front','back revised']))
        self.assertEqual(r['summary']['reprint'],1);self.assertEqual(r['retire'],[1])
    def test_swapped_sides(self):
        r=self.run_plan(make_pdf(['a','b']),make_pdf(['b','a']))
        self.assertEqual(r['summary']['reprint'],1)
    def test_geometry_is_part_of_equality(self):
        r=self.run_plan(make_pdf(['blank','blank'],(200,200)),make_pdf(['blank','blank'],(201,200)))
        self.assertEqual(r['summary']['reprint'],1)
    def test_force(self):
        blob=make_pdf(['a','b']);r=self.run_plan(blob,blob,force=[1])
        self.assertTrue(r['assembly'][0]['forced']);self.assertEqual(r['retire'],[1])
    def test_odd_empty_malformed_and_oversize(self):
        for i,blob in enumerate((b'',b'%PDF-1.4\nhi\n%%EOF',make_pdf(['a']),b'x'*(MAX_BYTES+1))):
            with self.subTest(i=i),self.assertRaises(InputError):inspect_pdf(self.path(f'bad{i}.pdf',blob),'bad',72)
    def modified(self,fn):
        r=PdfReader(BytesIO(make_pdf(['a','b'])));w=PdfWriter();[w.add_page(page) for page in r.pages];fn(w)
        stream=BytesIO();w.write(stream);return stream.getvalue()
    def test_rejected_features(self):
        mutators={
          'encrypted':lambda w:w.encrypt('password'),
          'forms':lambda w:w.root_object.__setitem__(NameObject('/AcroForm'),DictionaryObject()),
          'annotations':lambda w:w.pages[0].__setitem__(NameObject('/Annots'),ArrayObject()),
          'layers':lambda w:w.root_object.__setitem__(NameObject('/OCProperties'),DictionaryObject()),
          'action':lambda w:w.root_object.__setitem__(NameObject('/OpenAction'),DictionaryObject()),
          'rotation':lambda w:w.pages[0].__setitem__(NameObject('/Rotate'),NumberObject(90)),
          'unit':lambda w:w.pages[0].__setitem__(NameObject('/UserUnit'),NumberObject(2)),
          'crop':lambda w:setattr(w.pages[0].cropbox,'lower_left',(1,1)),
          'mixed':lambda w:setattr(w.pages[0].mediabox,'upper_right',(300,297)),
          'nan':lambda w:w.pages[0].mediabox.__setitem__(2,FloatObject('nan')),
        }
        for name,fn in mutators.items():
            with self.subTest(name=name),self.assertRaises((InputError,ValueError)):
                inspect_pdf(self.path(name+'.pdf',self.modified(fn)),name,72)
    def test_pixel_budget_rejected_before_render(self):
        blob=make_pdf(['blank']*80,(1000,1000))
        with patch('sheet_patch.engine.render_sides') as render:
            with self.assertRaisesRegex(InputError,'pixel input budget'):
                analyze(self.path('old.pdf',blob),self.path('new.pdf',blob),self.root,dpi=144)
            render.assert_not_called()
    def test_dpi_and_force_validation(self):
        a,b=demo_files()
        for dpi,force in ((73,[]),(True,[]),(72,[True]),(72,[99])):
            with self.subTest(dpi=dpi,force=force),self.assertRaises(InputError):
                analyze(self.path('old.pdf',a),self.path('new.pdf',b),self.root,dpi=dpi,force=force)
    def test_renderer_diagnostics_are_visible_bounded_and_fail_closed(self):
        blob=make_pdf(['a','b']);doc=inspect_pdf(self.path('old.pdf',blob),'old',72)
        from sheet_patch.engine import render_sides
        from types import SimpleNamespace
        with patch('sheet_patch.engine.subprocess.run',return_value=SimpleNamespace(returncode=0,stderr=b'Fontconfig error: example cache failure\n'+b'x'*5000)):
            with self.assertRaises(InputError) as caught:
                render_sides(self.root/'old.pdf',doc,72,self.root,'old',lambda _:None)
        self.assertIn('Fontconfig error: example cache failure',str(caught.exception))
        self.assertIn('Exit code 0',str(caught.exception))
        self.assertLess(len(str(caught.exception)),1000)
        self.assertFalse((self.root/'packet.zip').exists())

    def test_fontconfig_metadata_notice_classification_is_narrow(self):
        notice=b'Unable to revert mtime: /usr/share/fonts\n'
        collected=[]
        check_renderer_diagnostics(0,notice+notice,collected)
        self.assertEqual(collected,['Unable to revert mtime: /usr/share/fonts'])
        for code,stderr in ((1,notice),(0,notice+b'Syntax Warning: missing font\n'),(0,b'Unable to revert mtime: relative/path\n'),(0,b'Fontconfig error: cache failure\n'),(0,b'Unable to revert mtime: /fonts\x00oops')):
            with self.subTest(code=code,stderr=stderr),self.assertRaises(InputError):
                check_renderer_diagnostics(code,stderr,[])
        with self.assertRaises(InputError):check_renderer_diagnostics(0,notice)

    def test_fontconfig_notice_is_recorded_without_changing_raster_verification(self):
        import subprocess
        original=subprocess.run
        notice=b'Unable to revert mtime: /usr/share/fonts\n'
        def with_notice(*args,**kwargs):
            result=original(*args,**kwargs)
            if '-f' in args[0] and result.returncode==0:
                result.stderr=result.stderr+notice
            return result
        with patch('sheet_patch.engine.subprocess.run',side_effect=with_notice):
            result=self.run_plan(*demo_files())
        self.assertEqual(result['environmentNotices'],['Unable to revert mtime: /usr/share/fonts'])
        self.assertIn('Font-cache maintenance notice: Unable to revert mtime: /usr/share/fonts',result['warnings'])
        self.assertTrue(result['verification']['replacementRerenderMatched'])
        self.assertIn('Font-cache maintenance notice', (self.root/'work'/'assembly.html').read_text())
        self.assertEqual(result['summary']['reprint'],2)

    def test_html_escape(self):
        r=self.run_plan(*demo_files(),old_name='<img src=x onerror=alert(1)>.pdf')
        report=report_html(r)
        self.assertNotIn('<img src=x',report);self.assertIn('&lt;img',report)
    def test_ppm_first_pixel_whitespace(self):
        self.assertEqual(parse_ppm(b'P6\n1 1\n255\n \n\r'),(1,1,b' \n\r'))
