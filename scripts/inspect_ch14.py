from docx import Document
from pathlib import Path

out = Path("data/output/test_scheme_b/CH1.4_申请表_已填写.docx")
doc = Document(str(out))
lines = []
for ti, t in enumerate(doc.tables):
    lines.append(f"=== Table {ti} ===")
    for ri, row in enumerate(t.rows):
        for ci, c in enumerate(row.cells):
            if c.text.strip():
                lines.append(f"R{ri} C{ci}: {c.text[:300]}")
Path("data/output/ch14_inspect.txt").write_text("\n".join(lines), encoding="utf-8")
print("written", len(lines))
