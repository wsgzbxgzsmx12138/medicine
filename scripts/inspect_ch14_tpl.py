from docx import Document
from pathlib import Path
import glob

tpl = Path(glob.glob("data/upload/**/CH1.4*申请表*.docx", recursive=True)[-1])
doc = Document(str(tpl))
lines = [f"TEMPLATE {tpl.name}"]
for ti, t in enumerate(doc.tables):
    lines.append(f"=== Table {ti} ===")
    for ri, row in enumerate(t.rows):
        for ci, c in enumerate(row.cells):
            if c.text.strip():
                lines.append(f"R{ri} C{ci}: {repr(c.text[:200])}")
Path("data/output/ch14_tpl.txt").write_text("\n".join(lines), encoding="utf-8")
print("ok")
