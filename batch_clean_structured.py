import fitz  # PyMuPDF
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER, TA_LEFT
import os
import glob
import re

# --- Configuration ---
INPUT_FOLDER = "raw_pdfs"
OUTPUT_FOLDER = "clean_pdfs"

class PDFSanitizerPro:
    def __init__(self, input_path, output_path):
        self.input_path = input_path
        self.output_path = output_path
        self.doc = fitz.open(input_path)
        self.story = [] # Holds all the 'Flowables' (Text blocks)
        
        # --- Define Professional Styles ---
        styles = getSampleStyleSheet()
        
        # 1. Main Header (Bold, Centered, Big)
        self.style_header = ParagraphStyle(
            'Header1',
            parent=styles['Heading1'],
            fontSize=14,
            leading=18, # Line height
            alignment=TA_CENTER,
            spaceAfter=12,
            fontName='Helvetica-Bold'
        )
        
        # 2. Sub Header (Bold, Left Aligned)
        self.style_subheader = ParagraphStyle(
            'Header2',
            parent=styles['Heading2'],
            fontSize=11,
            leading=14,
            alignment=TA_LEFT,
            spaceAfter=6,
            fontName='Helvetica-Bold'
        )
        
        # 3. List Item (Hanging Indent)
        self.style_list = ParagraphStyle(
            'ListItem',
            parent=styles['BodyText'],
            fontSize=10,
            leading=12,
            leftIndent=20,
            firstLineIndent=0, # Keeps the bullet/number at the edge
            alignment=TA_JUSTIFY,
            spaceAfter=3
        )

        # 4. Standard Body (Justified, Clean)
        self.style_body = ParagraphStyle(
            'Body',
            parent=styles['BodyText'],
            fontSize=10,
            leading=13, # Comfortable reading height
            alignment=TA_JUSTIFY,
            spaceAfter=6
        )

    def is_junk_page(self, text, page_num):
        if page_num == 0: return True
        junk = ["table of contents", "index", "acknowledgement", "preface"]
        if text.count("....") > 5: return True
        return any(k in text.lower()[:300] for k in junk)

    def extract_smart_layout(self, page):
        """
        Extracts blocks and sorts them intelligently (Columns -> Reading Order).
        """
        blocks = page.get_text("blocks")
        # Filter noise: Images (type 1) and empty strings
        text_blocks = [b for b in blocks if b[6] == 0 and len(b[4].strip()) > 1]
        
        if not text_blocks: return []

        page_width = page.rect.width
        mid_point = page_width / 2
        
        # Detect Columns
        has_right_col = any(b[0] > (mid_point + 20) for b in text_blocks)
        
        if has_right_col:
            left = [b for b in text_blocks if b[0] < mid_point]
            right = [b for b in text_blocks if b[0] >= mid_point]
            left.sort(key=lambda x: x[1])
            right.sort(key=lambda x: x[1])
            sorted_blocks = left + right
        else:
            text_blocks.sort(key=lambda x: x[1])
            sorted_blocks = text_blocks

        # Return LIST of strings (Paragraphs), not one giant string
        return [b[4].strip() for b in sorted_blocks]

    def clean_text_block(self, text):
        """Removes Footer/Header noise inside the text block."""
        lines = text.split('\n')
        clean_lines = []
        for line in lines:
            # aggressive footer filter
            if re.search(r'Page \d+ of \d+', line): continue
            if "Tuesday, December" in line: continue
            if len(line.strip()) < 3: continue 
            
            # Merge hyphenated words (e.g., "bacter- ia" -> "bacteria")
            if line.endswith("-"):
                line = line[:-1]
                
            clean_lines.append(line)
            
        return " ".join(clean_lines) # Merge lines back into a single flowing paragraph

    def analyze_style(self, text):
        """Decides which Style Object to use."""
        # Main Header: Starts with number, short, CAPS or Title Case
        if (re.match(r'^\d+\.\s+', text) and len(text) < 80) or text.isupper():
            return self.style_header
        
        # Sub Header: 2.1, 2.1.3
        if re.match(r'^\d+\.\d+', text) and len(text) < 100:
            return self.style_subheader
            
        # List Item: (a), (i), 1.
        if re.match(r'^(\(?\w+\)?|\d+\.)\s+', text):
            return self.style_list
            
        return self.style_body

    def sanitize(self):
        for page_num in range(len(self.doc)):
            page = self.doc.load_page(page_num)
            raw_text = page.get_text("text") 
            
            if self.is_junk_page(raw_text, page_num): continue
            
            # Get Blocks (List of Paragraphs)
            blocks = self.extract_smart_layout(page)
            
            for block in blocks:
                # 1. Clean content
                clean_content = self.clean_text_block(block)
                if not clean_content: continue
                
                # 2. Pick Style
                style_to_use = self.analyze_style(clean_content)
                
                # 3. Create Paragraph Flowable
                para = Paragraph(clean_content, style_to_use)
                self.story.append(para)

        # Build PDF
        if self.story:
            doc = SimpleDocTemplate(
                self.output_path,
                pagesize=letter,
                rightMargin=50, leftMargin=50,
                topMargin=50, bottomMargin=50
            )
            doc.build(self.story)

# --- Batch Runner ---
def run_batch():
    if not os.path.exists(OUTPUT_FOLDER): os.makedirs(OUTPUT_FOLDER)
    files = glob.glob(os.path.join(INPUT_FOLDER, "*.pdf"))
    
    print(f"🚀 Processing {len(files)} PDFs using Pro Typesetting...")
    
    for f in files:
        name = os.path.basename(f)
        out_name = os.path.join(OUTPUT_FOLDER, "Pro_" + name)
        try:
            print(f"   - {name}...", end=" ")
            s = PDFSanitizerPro(f, out_name)
            s.sanitize()
            print("✅ Done")
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    run_batch()