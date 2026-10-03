"""Synthetic 3-to-4-sheet print-shop revision, no personal information."""
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor

def make_pdf(sides, size=(420,297)):
    output=BytesIO(); c=canvas.Canvas(output,pagesize=size,invariant=1)
    w,h=size
    for label in sides:
        c.setFillColor(HexColor('#fbf8ec')); c.rect(0,0,w,h,stroke=0,fill=1)
        if label != 'blank':
            c.setFillColor(HexColor('#1b5346')); c.rect(0,h-16,w,16,stroke=0,fill=1)
            c.setFont('Helvetica-Bold',12); c.drawString(28,h-48,'FIELD NOTES / PRINT PROOF')
            c.setFont('Helvetica-Bold',26); c.drawString(28,h-92,label)
            c.setFont('Helvetica',11); c.drawString(28,h-116,'Synthetic already-imposed sheet side')
            for i in range(5):
                c.setStrokeColor(HexColor('#bfcbc1'));c.line(28,h-146-i*16,w-28,h-146-i*16)
            if 'revised' in label:
                c.setFillColor(HexColor('#e6b64d'));c.rect(w-118,29,90,28,stroke=0,fill=1)
                c.setFillColor(HexColor('#1b5346')); c.setFont('Helvetica-Bold',11);c.drawString(w-108,39,'REVISION 02')
        c.showPage()
    c.save();return output.getvalue()

def demo_files():
    return make_pdf(['A front','A back','B front','B back','C front','C back']), make_pdf(['A front','A back','C front','C back','B front','B back revised','D front','D back'])
