import fitz  # PyMuPDF
import sys
import os

def pdf_to_markdown(pdf_path, md_path):
    print(f"Reading PDF from: {pdf_path}")
    doc = fitz.open(pdf_path)
    markdown_lines = []
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        markdown_lines.append(f"## Page {page_num + 1}\n")
        
        # Extract text blocks with structural layout hints
        text = page.get_text("text")
        markdown_lines.append(text)
        markdown_lines.append("\n---\n") # Page separator
        
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(markdown_lines))
        
    print(f"Successfully converted and saved to: {md_path}")

if __name__ == "__main__":
    # Example usage
    # pdf_to_markdown('sample.pdf', 'output.md')
    pass
