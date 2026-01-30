import fitz  # PyMuPDF
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit
from reportlab.lib import colors
from datetime import datetime
import os
import glob
import re

# --- Configuration ---
INPUT_FOLDER = "raw_pdfs"
OUTPUT_FOLDER = "clean_pdfs"

class PDFSanitizer:
    def __init__(self, input_path, output_path):
        self.input_path = input_path
        self.output_path = output_path
        self.doc = fitz.open(input_path)
        self.clean_paragraphs = [] # Stores text blocks to write

    def is_junk_page(self, text, page_num):
        """Detects Covers, Indexes, or blank pages."""
        text_lower = text.lower()
        if page_num == 0: return True # Always skip Cover
        
        junk_keywords = ["table of contents", "index", "acknowledgement", "preface"]
        # Check for dots pattern (common in TOC)
        if text.count("....") > 5: return True
        
        # Check for keywords in header
        header = text_lower[:300]
        for k in junk_keywords:
            if k in header: return True
            
        return False

    def extract_smart_layout(self, page):
        """
        Detects 1-column vs 2-column layout dynamically.
        Returns text sorted in reading order.
        """
        blocks = page.get_text("blocks")
        # Filter: exclude images (type 1) and tiny text
        text_blocks = [b for b in blocks if b[6] == 0 and len(b[4].strip()) > 1]
        
        if not text_blocks: return ""

        page_width = page.rect.width
        mid_point = page_width / 2
        
        # Check if 2-Column: Do we have text starting on the Right Half?
        has_right_col = any(b[0] > (mid_point + 20) for b in text_blocks)
        
        if has_right_col:
            # Sort: Left Col (Top-Down) -> Right Col (Top-Down)
            left_col = [b for b in text_blocks if b[0] < mid_point]
            right_col = [b for b in text_blocks if b[0] >= mid_point]
            
            left_col.sort(key=lambda x: x[1])
            right_col.sort(key=lambda x: x[1])
            
            sorted_blocks = left_col + right_col
        else:
            # Sort: Strict Top-Down
            text_blocks.sort(key=lambda x: x[1])
            sorted_blocks = text_blocks

        # Return joined text
        return "\n".join([b[4].strip() for b in sorted_blocks])

    def clean_noise(self, text):
        """
        Removes old page numbers and headers from the raw text stream.
        """
        lines = text.split('\n')
        cleaned_lines = []
        for line in lines:
            # Remove "Page X of Y" or "December 24, 2024" type lines
            if re.search(r'Page \d+ of \d+', line) or re.search(r'Tuesday, December', line):
                continue
            if len(line) < 4: # Remove tiny artifacts
                continue
            cleaned_lines.append(line)
        return cleaned_lines

    def analyze_structure(self, line):
        """
        Decides the Formatting (Bold, Indent) based on Regex patterns.
        Matches the style of your 'Gold Standard' documents.
        """
        # 1. MAIN HEADER (e.g., "1. TITLE", "5. MISCONDUCT")
        # Pattern: Start with number + dot + CAPS or specific Keywords
        if re.match(r'^\d+\.\s+[A-Z\s]+$', line) or line in ["PREAMBLE", "STATUTE"]:
            return "HEADER_1"
        
        # 2. SUB HEADER (e.g., "2.1 Definition", "4.2.1")
        if re.match(r'^\d+\.\d+(\.\d+)?\s+', line):
            return "HEADER_2"
            
        # 3. LIST ITEM (e.g., "(a)", "(i)", "a.")
        if re.match(r'^(\([a-z0-9]+\)|[a-z]\.)\s+', line):
            return "LIST_ITEM"
            
        return "NORMAL"

    def create_clean_pdf(self):
        """Writes the structured PDF using ReportLab."""
        c = canvas.Canvas(self.output_path, pagesize=letter)
        width, height = letter
        margin_left = 50
        margin_right = 50
        max_width = width - (margin_left + margin_right)
        
        y = height - 50 # Start position
        page_num = 1
        
        def draw_footer():
            c.setFont("Helvetica", 9)
            c.setFillColor(colors.grey)
            date_str = datetime.now().strftime("%A, %B %d, %Y")
            c.drawString(margin_left, 30, date_str)
            c.drawRightString(width - margin_right, 30, f"Page {page_num} of ?")
            c.setFillColor(colors.black) # Reset

        for line in self.clean_paragraphs:
            # Check for Page Break
            if y < 60: 
                draw_footer()
                c.showPage()
                y = height - 50
                page_num += 1

            # Get Style
            style = self.analyze_structure(line)
            
            # Apply Style Settings
            if style == "HEADER_1":
                c.setFont("Helvetica-Bold", 14)
                indent = 0
                y -= 10 # Extra space before header
            elif style == "HEADER_2":
                c.setFont("Helvetica-Bold", 11)
                indent = 15
                y -= 5
            elif style == "LIST_ITEM":
                c.setFont("Helvetica", 11)
                indent = 35
            else: # Normal
                c.setFont("Helvetica", 11)
                indent = 0

            # Wrap Text (Handling long lines)
            wrapped_lines = simpleSplit(line, c._fontname, c._fontsize, max_width - indent)
            
            for w_line in wrapped_lines:
                if y < 60: # Check break inside a paragraph
                    draw_footer()
                    c.showPage()
                    y = height - 50
                    page_num += 1
                    # Restore font after page break
                    if style == "HEADER_1": c.setFont("Helvetica-Bold", 14)
                    elif style == "HEADER_2": c.setFont("Helvetica-Bold", 11)
                    else: c.setFont("Helvetica", 11)

                c.drawString(margin_left + indent, y, w_line)
                y -= 14 # Line spacing
            
            y -= 4 # Paragraph spacing

        draw_footer()
        c.save()

    def sanitize(self):
        # 1. Read & Process All Pages
        for page_num in range(len(self.doc)):
            page = self.doc.load_page(page_num)
            raw_text = page.get_text("text") # Quick check
            
            if self.is_junk_page(raw_text, page_num):
                continue
                
            # Smart Extract (Fixes Columns)
            ordered_text = self.extract_smart_layout(page)
            
            # Clean Noise & Store
            clean_lines = self.clean_noise(ordered_text)
            self.clean_paragraphs.extend(clean_lines)
            
        # 2. Generate PDF
        if self.clean_paragraphs:
            self.create_clean_pdf()

# --- Batch Runner ---
def run_batch():
    if not os.path.exists(OUTPUT_FOLDER): os.makedirs(OUTPUT_FOLDER)
    files = glob.glob(os.path.join(INPUT_FOLDER, "*.pdf"))
    
    print(f"🚀 Found {len(files)} PDFs. Processing...")
    
    for f in files:
        name = os.path.basename(f)
        out_name = os.path.join(OUTPUT_FOLDER, "Cleaned_" + name)
        print(f"   - Processing: {name} ...", end=" ")
        try:
            s = PDFSanitizer(f, out_name)
            s.sanitize()
            print("✅ Done")
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    run_batch()