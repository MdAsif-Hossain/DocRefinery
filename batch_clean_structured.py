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
            fontSize=12, leading=16, spaceAfter=4, textColor=colors.darkblue,
            fontName='Helvetica-Bold'
        )

    def clean_text_rag_optimized(self, text):
        """
        The Master Cleaner: Removes artifacts, symbols, watermarks, and contact info.
        """
        # 1. Remove tags
        text = re.sub(r'\\', '', text)
        
        # 2. Remove Page Markers "--- PAGE 1 ---"
        text = re.sub(r'---\s*PAGE\s*\d+\s*---', '', text)
        
        # 3. Fix Encoding/Symbols
        text = text.replace('©', '')     # Remove copyright symbol entirely
        text = text.replace('\xa0', ' ') # Fix non-breaking spaces
        text = text.replace('\\', '')    # Remove backslashes safely
        
        lines = text.split('\n')
        cleaned_lines = []
        
        # Flag to detect if we hit the "Contact Us" section
        hit_footer_section = False

        for line in lines:
            stripped = line.strip()
            
            # --- AGGRESSIVE NOISE FILTERS ---
            
            # A. Remove empty or tiny lines
            if len(stripped) < 3: continue
            
            # B. Remove Repeating Watermarks "AKW"
            if re.match(r'^(\(?c\)?\s*AKW\s*)+$', stripped, re.IGNORECASE):
                continue
            
            # C. Remove "FAO, Yangon" footers
            if "FAO" in stripped and "Yangon" in stripped: continue
            
            # D. Remove File codes / Copyright lines
            if stripped in ["CD1098EN/1/06.24", "AKW", "FAO, 2024"]: continue
            
            # E. Remove Date/Page lines
            if "Page" in stripped and "of" in stripped: continue
            if "Tuesday, December" in stripped: continue

            # --- F. NEW: REMOVE CONTACT / FEEDBACK SECTION ---
            # If we see the start of the feedback section, we trigger a flag or skip
            
            # Detect the start phrase
            if "We want to hear from you" in stripped:
                hit_footer_section = True
                continue # Skip this line
            
            # Detect specific names/numbers in that block
            if "Daw Nu Nu Lwin" in stripped or "U Aung Thein" in stripped: continue
            if "09 893" in stripped or "09 894" in stripped: continue
            if "@fao.org" in stripped: continue
            if "Pictures on cover by" in stripped: continue
            
            # Detect the broken "Time : 8:30" lines
            if "Time" in stripped and "8:30" in stripped: continue
            if "Monday" in stripped and "Friday" in stripped: continue

            # If it's just a stray number from the phone list (e.g., "091", "090")
            if stripped.isdigit() and len(stripped) < 5: continue
            
            # If it's a stray name part like "U", "Aung", "Ko" appearing on its own line
            if stripped in ["U", "Aung", "Ko", "Win"]: continue

            cleaned_lines.append(stripped)
            
        return "\n".join(cleaned_lines)

    def detect_and_format_table(self, text_block):
        """
        Heuristic to detect tables (like the Salinity table) and format them as Grids.
        """
        lines = text_block.split('\n')
        
        # Specific Check for the FAO "Salinity" table pattern
        if "No problem" in text_block and "Severe problems" in text_block:
            data = []
            for line in lines:
                # Split by 2+ spaces (visual column separation)
                cols = re.split(r'\s{2,}', line.strip())
                if len(cols) > 1:
                    data.append(cols)
            
            if len(data) > 2:
                # It's a table! Create a ReportLab Table Object
                t = Table(data, colWidths=[150, 100, 100, 100])
                t.setStyle(TableStyle([
                    ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
                    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'), # Bold Header
                    ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
                    ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                    ('FONTSIZE', (0,0), (-1,-1), 9),
                ]))
                return t
        
        return None

    def sanitize(self):
        for page_num in range(len(self.doc)):
            page = self.doc.load_page(page_num)
            raw_text = page.get_text("text") 
            
            # 1. Clean the text
            clean_text = self.clean_text_rag_optimized(raw_text)
            
            # 2. Split into semantic blocks (Paragraphs) by double newline
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
                if len(para_text) < 100 and not para_text.endswith('.'):
                    style = self.style_header
                else:
                    style = self.style_body
                
                # 5. Create Paragraph
                try:
                    p = Paragraph(para_text, style)
                    self.story.append(p)
                except:
                    # Fallback for weird characters
                    p = Paragraph(para_text, self.style_body)
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