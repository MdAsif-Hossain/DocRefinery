import fitz  # PyMuPDF
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
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
        
        # --- Custom Styles ---
        self.style_body = ParagraphStyle(
            'Body', parent=self.styles['BodyText'],
            fontSize=10, leading=14, alignment=TA_JUSTIFY, spaceAfter=8
        )
        self.style_header = ParagraphStyle(
            'Header', parent=self.styles['Heading2'],
            fontSize=12, leading=16, spaceAfter=4, textColor=colors.darkblue
        )

    def clean_text_rag_optimized(self, text):
        """
        The Master Cleaner: Removes artifacts, symbols, and specific noise patterns.
        """
        # 1. Remove tags
        text = text.replace('\\', '')
        
        # 2. Remove Page Markers "--- PAGE 1 ---"
        text = re.sub(r'---\s*PAGE\s*\d+\s*---', '', text)
        
        # 3. Fix Encoding/Symbols
        text = text.replace('©', '(c)')  # Fix copyright symbol
        text = text.replace('\xa0', ' ') # Fix non-breaking spaces
        
        # 4. Remove Watermarks/Initials (lines that are just "AKW" or "CD1098EN")
        lines = text.split('\n')
        cleaned_lines = []
        for line in lines:
            stripped = line.strip()
            # Skip empty or tiny meaningless lines
            if len(stripped) < 3: continue
            if stripped in ["AKW", "AKW AKW", "CD1098EN/1/06.24"]: continue 
            
            # Skip Footer/Header noise
            if "Page" in stripped and "of" in stripped: continue
            if "Tuesday, December" in stripped: continue
            
            cleaned_lines.append(stripped)
            
        return "\n".join(cleaned_lines)

    def detect_and_format_table(self, text_block):
        """
        Heuristic to detect if a text block is actually a table.
        If yes, formats it as a ReportLab Table (which RAG engines read better).
        """
        lines = text_block.split('\n')
        
        # Heuristic: If multiple lines have similar spacing or structure (like "Value... Value... Value")
        # For this specific PDF, we look for the "Salinity" table pattern
        if "No problem" in text_block and "Severe problems" in text_block:
            # We found the specific Salinity table! Let's hard-code the fix for this known structure
            # Or use a generic splitter. Let's try a generic splitter based on spacing.
            data = []
            for line in lines:
                # Split by 2+ spaces (assuming visual separation)
                cols = re.split(r'\s{2,}', line.strip())
                if len(cols) > 1:
                    data.append(cols)
            
            if len(data) > 2:
                # It's a table!
                t = Table(data, colWidths=[150, 100, 100, 100]) # Approx widths
                t.setStyle(TableStyle([
                    ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
                    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'), # Header bold
                    ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
                ]))
                return t
        
        return None

    def sanitize(self):
        for page_num in range(len(self.doc)):
            page = self.doc.load_page(page_num)
            raw_text = page.get_text("text") # Extract raw text
            
            # 1. Clean the text
            clean_text = self.clean_text_rag_optimized(raw_text)
            
            # 2. Split into semantic blocks (Paragraphs)
            # We split by double newline to separate headers from body
            paragraphs = clean_text.split('\n\n')
            
            for para_text in paragraphs:
                para_text = para_text.strip()
                if not para_text: continue
                
                # 3. Check for Table
                table_obj = self.detect_and_format_table(para_text)
                if table_obj:
                    self.story.append(table_obj)
                    self.story.append(Spacer(1, 12))
                    continue
                
                # 4. Determine Style (Header vs Body)
                # If short and no period at end, likely a Header
                if len(para_text) < 100 and not para_text.endswith('.'):
                    style = self.style_header
                else:
                    style = self.style_body
                
                # 5. Create Paragraph
                p = Paragraph(para_text, style)
                self.story.append(p)

        # Build PDF
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
    
    print(f"🚀 RAG-Cleaning {len(files)} PDFs...")
    
    for f in files:
        name = os.path.basename(f)
        out_name = os.path.join(OUTPUT_FOLDER, "RAG_" + name)
        try:
            print(f"   - {name}...", end=" ")
            s = RAGSanitizer(f, out_name)
            s.sanitize()
            print("✅ Done")
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    run_batch()