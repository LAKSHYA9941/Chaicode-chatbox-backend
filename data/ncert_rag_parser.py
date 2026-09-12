# import os
# import sys
# import glob
# from pathlib import Path

# try:
#     import fitz  # PyMuPDF
# except ImportError:
#     print("❌ PyMuPDF not installed. Please run: pip install pymupdf")
#     sys.exit(1)

# def clean_text(text):
#     """
#     Cleans up common artifacts found in NCERT PDFs (running headers, excess newlines).
#     """
#     lines = text.split('\n')
#     cleaned_lines = []
    
#     for line in lines:
#         line_strip = line.strip()
        
#         # Skip common NCERT running headers/footers (e.g., page numbers, chapter titles)
#         if not line_strip:
#             cleaned_lines.append("")
#             continue
#         if "Rationalised" in line_strip or "Chapter" in line_strip:
#             continue
#         if line_strip.isdigit() and len(line_strip) <= 3:
#             continue
            
#         cleaned_lines.append(line_strip)
        
#     return "\n".join(cleaned_lines)

# def ncert_pdf_to_md(pdf_path, output_dir):
#     """
#     Converts a single NCERT PDF chapter to clean RAG-optimized Markdown.
#     """
#     pdf_path = Path(pdf_path)
#     output_dir = Path(output_dir)
#     output_dir.mkdir(parents=True, exist_ok=True)
    
#     md_filename = pdf_path.stem + ".md"
#     md_path = output_dir / md_filename
    
#     print(f"🔄 Processing: {pdf_path.name}...")
    
#     try:
#         doc = fitz.open(pdf_path)
#         md_blocks = []
        
#         # Metadata header for better RAG chunk context injection
#         md_blocks.append("---")
#         md_blocks.append(f"source_file: {pdf_path.name}")
#         md_blocks.append(f"total_pages: {len(doc)}")
#         md_blocks.append("---")
        
#         for page_num in range(len(doc)):
#             page = doc[page_num]
            
#             # Use 'blocks' format to group text layouts logically
#             blocks = page.get_text("blocks")
            
#             # Inject a semantic structural marker for RAG document chunk tracking
#             md_blocks.append(f"\n<!-- START_PAGE_{page_num + 1} -->\n")
            
#             for b in blocks:
#                 block_text = b[4].strip()
#                 if not block_text:
#                     continue
                
#                 # Filter running text header noise
#                 if "Rationalised" in block_text or block_text.isdigit():
#                     continue
                
#                 # Check for font size / bold traits if advanced flags are parsed, 
#                 # otherwise rely on logical paragraphs.
#                 # Simple heuristic: Short lines in ALL CAPS or starting with numbers are likely headings
#                 if len(block_text) < 100 and (block_text.isupper() or block_text[0].isdigit() and "." in block_text[:4]):
#                     md_blocks.append(f"\n### {block_text}\n")
#                 else:
#                     md_blocks.append(block_text)
                    
#             md_blocks.append(f"\n<!-- END_PAGE_{page_num + 1} -->\n")
            
#         # Save output
#         with open(md_path, "w", encoding="utf-8") as f:
#             f.write("\n".join(md_blocks))
            
#         print(f"✅ Saved to: {md_path}")
        
#     except Exception as e:
#         print(f"❌ Error processing {pdf_path.name}: {str(e)}")

# def batch_convert(input_folder, output_folder):
#     """
#     Scans a folder for all NCERT PDFs and processes them sequentially.
#     """
#     pdf_files = glob.glob(os.path.join(input_folder, "*.pdf"))
#     if not pdf_files:
#         print(f"⚠️ No PDF files found in '{input_folder}'. Update your path variables.")
#         return
        
#     print(f"📚 Found {len(pdf_files)} NCERT chapters to process.")
#     for pdf in pdf_files:
#         ncert_pdf_to_md(pdf, output_folder)

# if __name__ == "__main__":
#     # Configure your workspace directory structure here
#     INPUT_DIR = "./ncert_pdfs"
#     OUTPUT_DIR = "./ncert_markdowns"
    
#     # Create sample directory structure for the user
#     os.makedirs(INPUT_DIR, exist_ok=True)
    
#     print("⚙️ NCERT RAG Parser ready.")
#     print(f"1. Drop your NCERT chapter PDFs into the folder: {INPUT_DIR}")
#     print("2. Run this script to generate structural markdowns.")
    
#     # Uncomment below to execute local batch running when files are ready:
#     # batch_convert(INPUT_DIR, OUTPUT_DIR)
