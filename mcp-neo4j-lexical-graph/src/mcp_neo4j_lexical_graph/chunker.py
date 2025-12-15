"""PDF processing and chunking module.

Uses PyMuPDF for fast PDF text extraction and tiktoken for token-based chunking.
"""

import hashlib
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
import tiktoken
import structlog

from .models import Chunk, ChunkingResult

logger = structlog.get_logger()

# Default tokenizer for OpenAI models
DEFAULT_ENCODING = "cl100k_base"


class PDFChunker:
    """Process PDFs into text chunks with token-based splitting.
    
    Features:
    - Fast PDF text extraction via PyMuPDF
    - Token-based chunking with configurable size and overlap
    - Preserves character positions for provenance
    
    Example:
        >>> chunker = PDFChunker(chunk_size=500, chunk_overlap=50)
        >>> result = chunker.process_pdf("/path/to/doc.pdf", "doc_001")
        >>> print(f"Created {len(result.chunks)} chunks")
    """
    
    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        encoding_name: str = DEFAULT_ENCODING
    ):
        """Initialize the PDF chunker.
        
        Args:
            chunk_size: Target size of each chunk in tokens
            chunk_overlap: Number of overlapping tokens between chunks
            encoding_name: Tiktoken encoding name (default: cl100k_base for OpenAI)
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.encoding = tiktoken.get_encoding(encoding_name)
        
        logger.info(
            "PDFChunker initialized",
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            encoding=encoding_name
        )
    
    def extract_text_from_pdf(self, pdf_path: str) -> tuple[str, int]:
        """Extract all text from a PDF file.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            Tuple of (extracted_text, page_count)
            
        Raises:
            FileNotFoundError: If PDF file doesn't exist
            ValueError: If PDF cannot be processed
        """
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        
        try:
            doc = fitz.open(pdf_path)
            pages_text = []
            
            for page_num, page in enumerate(doc):
                text = page.get_text("text")
                pages_text.append(text)
                logger.debug(f"Extracted page {page_num + 1}", chars=len(text))
            
            full_text = "\n\n".join(pages_text)
            page_count = len(doc)
            doc.close()
            
            logger.info(
                "PDF text extracted",
                path=pdf_path,
                pages=page_count,
                total_chars=len(full_text)
            )
            
            return full_text, page_count
            
        except Exception as e:
            logger.error("Failed to extract PDF text", path=pdf_path, error=str(e))
            raise ValueError(f"Failed to process PDF: {e}") from e
    
    def chunk_text(
        self,
        text: str,
        document_id: str
    ) -> list[Chunk]:
        """Split text into overlapping chunks based on token count.
        
        Args:
            text: Full text to chunk
            document_id: Document identifier for chunk IDs
            
        Returns:
            List of Chunk objects
        """
        # Encode full text to tokens
        tokens = self.encoding.encode(text)
        total_tokens = len(tokens)
        
        logger.info(
            "Starting chunking",
            document_id=document_id,
            total_tokens=total_tokens,
            chunk_size=self.chunk_size,
            overlap=self.chunk_overlap
        )
        
        chunks = []
        chunk_index = 0
        token_start = 0
        
        while token_start < total_tokens:
            # Calculate token end position
            token_end = min(token_start + self.chunk_size, total_tokens)
            
            # Get tokens for this chunk
            chunk_tokens = tokens[token_start:token_end]
            
            # Decode back to text
            chunk_text = self.encoding.decode(chunk_tokens)
            
            # Calculate character positions (approximate)
            # We need to find where this text appears in the original
            char_start = self._find_text_position(text, chunk_text, chunk_index)
            char_end = char_start + len(chunk_text)
            
            # Generate chunk ID
            chunk_id = f"{document_id}_chunk_{chunk_index:04d}"
            
            chunk = Chunk(
                id=chunk_id,
                text=chunk_text,
                index=chunk_index,
                start_char=char_start,
                end_char=char_end,
                token_count=len(chunk_tokens),
                embedding=None
            )
            chunks.append(chunk)
            
            logger.debug(
                f"Created chunk {chunk_index}",
                tokens=len(chunk_tokens),
                chars=len(chunk_text)
            )
            
            # Calculate next start position
            # Step forward by (chunk_size - overlap) tokens
            step = self.chunk_size - self.chunk_overlap
            next_start = token_start + step
            
            # If we've reached the end or would make no progress, stop
            if next_start >= total_tokens or next_start <= token_start:
                break
            
            token_start = next_start
            chunk_index += 1
        
        logger.info(
            "Chunking completed",
            document_id=document_id,
            total_chunks=len(chunks),
            total_tokens=total_tokens
        )
        
        return chunks
    
    def _find_text_position(self, full_text: str, chunk_text: str, chunk_index: int) -> int:
        """Find approximate character position of chunk in full text.
        
        For overlapping chunks, we estimate based on chunk index.
        This is approximate since token boundaries don't align perfectly with characters.
        """
        # Estimate position based on average chars per token
        if chunk_index == 0:
            return 0
        
        # Find the chunk text in the full text, starting from estimated position
        avg_chars_per_token = len(full_text) / max(1, len(self.encoding.encode(full_text)))
        estimated_start = int(chunk_index * (self.chunk_size - self.chunk_overlap) * avg_chars_per_token)
        
        # Search in a window around estimated position
        search_start = max(0, estimated_start - 1000)
        search_end = min(len(full_text), estimated_start + len(chunk_text) + 1000)
        
        # Try to find exact match
        pos = full_text.find(chunk_text[:100], search_start, search_end)  # Match first 100 chars
        
        if pos >= 0:
            return pos
        
        # Fallback to estimated position
        return min(estimated_start, len(full_text) - len(chunk_text))
    
    def process_pdf(
        self,
        pdf_path: str,
        document_id: str
    ) -> ChunkingResult:
        """Process a PDF file into chunks.
        
        Main entry point for PDF processing.
        
        Args:
            pdf_path: Path to the PDF file
            document_id: Unique identifier for the document
            
        Returns:
            ChunkingResult with all chunks and metadata
        """
        logger.info("Processing PDF", path=pdf_path, document_id=document_id)
        
        # Extract text
        full_text, page_count = self.extract_text_from_pdf(pdf_path)
        
        # Create chunks
        chunks = self.chunk_text(full_text, document_id)
        
        # Calculate totals
        total_tokens = sum(c.token_count for c in chunks)
        
        result = ChunkingResult(
            document_id=document_id,
            source_path=pdf_path,
            total_pages=page_count,
            total_characters=len(full_text),
            total_tokens=total_tokens,
            chunks=chunks
        )
        
        logger.info(
            "PDF processing completed",
            document_id=document_id,
            pages=page_count,
            chunks=len(chunks),
            tokens=total_tokens
        )
        
        return result


# Convenience function for single-file processing
def process_pdf_to_chunks(
    pdf_path: str,
    document_id: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50
) -> ChunkingResult:
    """Process a PDF file into chunks.
    
    Convenience function that creates a PDFChunker and processes the file.
    
    Args:
        pdf_path: Path to the PDF file
        document_id: Unique identifier for the document
        chunk_size: Target chunk size in tokens (default: 500)
        chunk_overlap: Overlap between chunks in tokens (default: 50)
        
    Returns:
        ChunkingResult with all chunks and metadata
    """
    chunker = PDFChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    return chunker.process_pdf(pdf_path, document_id)

