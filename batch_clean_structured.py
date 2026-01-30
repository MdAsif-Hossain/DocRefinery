import fitz  # PyMuPDF
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib import colors
import os
import glob
import re

# --- Configuration ---
INPUT_FOLDER = "raw_pdfs"
OUTPUT_FOLDER = "clean_pdfs"

class RAGSanitizer:
    def __init__(self, input_path, output_path):
        self.input_path = input_path
        self.output_path = output_path
        self.doc = fitz.open(input_path)
        self.story = []
        self.styles = getSampleStyleSheet()
        
        # --- Styles ---
        self.style_body = ParagraphStyle(
            'Body', parent=self.styles['BodyText'],
            fontSize=11, leading=15, alignment=TA_JUSTIFY, spaceAfter=10
        )
        self.style_h1 = ParagraphStyle(
            'Header1', parent=self.styles['Heading1'],
            fontSize=14, leading=18, spaceAfter=12, textColor=colors.black,
            fontName='Helvetica-Bold'
        )
        self.style_h2 = ParagraphStyle(
            'Header2', parent=self.styles['Heading2'],
            fontSize=12, leading=16, spaceAfter=10, textColor=colors.black,
            fontName='Helvetica-Bold'
        )
        self.style_list = ParagraphStyle(
            'ListItem', parent=self.styles['BodyText'],
            fontSize=11, leading=15, leftIndent=20, spaceAfter=8,
            fontName='Helvetica' 
        )

    def is_junk_page(self, text):
        """Skip TOC, Index, and License pages."""
        text_lower = text.lower()
        if text.count(".....") > 3: return True
        if "contents" in text_lower[:200] and "chapter" in text_lower: return True
        if "list of tables" in text_lower or "list of figures" in text_lower: return True
        
        junk_triggers = ["creative commons", "isbn 978", "suggested citation", "mailing address:", "all rights reserved"]
        if sum(1 for t in junk_triggers if t in text_lower) >= 2: return True 
        return False

    def clean_text_rag_optimized(self, text):
        """Removes watermarks, headers, and specific junk."""
        text = re.sub(r'\\', '', text)
        text = re.sub(r'---\s*PAGE\s*\d+\s*---', '', text)
        text = text.replace('©', '').replace('\xa0', ' ').replace('\\', '').replace('AKW', '')
        
        lines = text.split('\n')
        cleaned_lines = []
        hit_footer = False

        for line in lines:
            stripped = line.strip()
            if len(stripped) < 3: continue
            
            # Junk Filters
            if "We want to hear from you" in stripped: hit_footer = True
            if hit_footer: continue 
            if "FAO" in stripped and "Yangon" in stripped: continue
            if "Page" in stripped and "of" in stripped: continue
            if "Tuesday, December" in stripped: continue
            if "CD1098EN" in stripped: continue
            if re.match(r'^(Source|Figure|http).*', stripped, re.IGNORECASE): continue

            # --- STRUCTURE MARKERS ---
            # 1. Detect Tables: Look for 2+ spaces between words (Column Gaps)
            # We explicitly mark lines that look like table rows with <TABLE_ROW>
            if len(re.split(r'\s{3,}', stripped)) > 1: 
                cleaned_lines.append("<TABLE_ROW>" + stripped)
            # 2. Detect Lists/Headers
            elif re.match(r'^\d+(\.\d+)*\.?', stripped):
                cleaned_lines.append("<FORCE_BREAK>" + stripped)
            else:
                cleaned_lines.append(stripped)
            
        return "\n".join(cleaned_lines)

    def process_table_block(self, table_lines):
        """Converts a list of text lines into a ReportLab Table."""
        data = []
        for line in table_lines:
            # Split by 3+ spaces to find columns
            cols = re.split(r'\s{3,}', line.strip())
            data.append(cols)
        
        if not data: return None

        # Create the Table with generic styling
        t = Table(data, hAlign='LEFT')
        t.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey), # Header Row Grey
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('PADDING', (0,0), (-1,-1), 6),
        ]))
        return t

    def sanitize(self):
        for page_num in range(len(self.doc)):
            page = self.doc.load_page(page_num)
            raw_text = page.get_text("text") 
            
            if self.is_junk_page(raw_text):
                print(f"   [Skipping Junk Page {page_num+1}]")
                continue

            clean_text = self.clean_text_rag_optimized(raw_text)
            
            # Process Paragraphs & Tables
            clean_text = clean_text.replace('\n', ' ') 
            clean_text = clean_text.replace('<FORCE_BREAK>', '\n<FORCE_BREAK>')
            # Group Table Rows together
            clean_text = re.sub(r'(<TABLE_ROW>.*?)(?=\s*<FORCE_BREAK>|\s*[A-Z])', r'\n<TABLE_BLOCK>\1', clean_text)
            
            blocks = clean_text.split('\n')

            table_buffer = []

            for block in blocks:
                block = block.strip()
                if not block: continue
                
                # --- TABLE HANDLING ---
                if "<TABLE_ROW>" in block or "<TABLE_BLOCK>" in block:
                    # Clean tags
                    row_content = block.replace('<TABLE_BLOCK>', '').replace('<TABLE_ROW>', '').replace('<FORCE_BREAK>', '')
                    table_buffer.append(row_content)
                    
                    # If this is the last block or next is not table, flush buffer
                    # (Simple heuristic: assumes contiguous table rows)
                    if len(table_buffer) > 1: 
                        # Try to flush
                        pass 
                    continue
                else:
                    # Flush any existing table buffer first
                    if table_buffer:
                        t = self.process_table_block(table_buffer)
                        if t: self.story.append(t)
                        self.story.append(Spacer(1, 10))
                        table_buffer = []

                # --- TEXT HANDLING ---
                text_content = block.replace('<FORCE_BREAK>', '').strip()
                if not text_content: continue

                # Header Logic
                if re.match(r'^\d+\.\s+[A-Z\s]+$', text_content) and len(text_content) < 80:
                    style = self.style_h1
                elif re.match(r'^\d+\.\d+\.?\s+', text_content) and len(text_content) < 80:
                    style = self.style_h2
                elif re.match(r'^\d+(\.\d+)*\.?', text_content):
                    style = self.style_list
                else:
                    style = self.style_body

                try:
                    p = Paragraph(text_content, style)
                    self.story.append(p)
                except:
                    pass
            
            # Flush table at end of page if any
            if table_buffer:
                t = self.process_table_block(table_buffer)
                if t: self.story.append(t)

        if self.story:
            doc = SimpleDocTemplate(
                self.output_path, pagesize=letter,
                rightMargin=50, leftMargin=50, topMargin=50, bottomMargin=50
            )
            doc.build(self.story)

# --- Batch Runner ---
def run_batch():
    if not os.path.exists(OUTPUT_FOLDER): os.makedirs(OUTPUT_FOLDER)
    files = glob.glob(os.path.join(INPUT_FOLDER, "*.pdf"))
    
    print(f"🚀 Cleaning {len(files)} PDFs (Smart Table Mode)...")
    
    for f in files:
        name = os.path.basename(f)
        out_name = os.path.join(OUTPUT_FOLDER, "Clean_" + name)
        try:
            print(f"   - {name}...", end=" ")
            s = RAGSanitizer(f, out_name)
            s.sanitize()
            print("✅ Done")
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    run_batch()