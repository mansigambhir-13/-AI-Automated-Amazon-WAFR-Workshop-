"""
PDF Processor - Extract text and images from PDF files.

Integrates with WAFR assessment pipeline to process PDF documentation
and extract content for analysis.
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

DEFAULT_AWS_REGION = "us-east-1"
DEFAULT_DPI_OCR = 300
DEFAULT_DPI_IMAGES = 200

# Thresholds for text quality assessment
MIN_TEXT_LENGTH_THRESHOLD = 100
MIN_ALPHANUMERIC_RATIO = 0.1

# -----------------------------------------------------------------------------
# Library Availability Checks
# -----------------------------------------------------------------------------

logger = logging.getLogger(__name__)

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False
    logger.warning("pdfplumber not available - PDF text extraction will be limited")

try:
    from PIL import Image
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    logger.warning("Pillow not available - PDF image extraction will be limited")

try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False
    logger.warning("pdf2image not available - PDF to image conversion will be limited")

try:
    import PyPDF2
    PYPDF2_AVAILABLE = True
except ImportError:
    PYPDF2_AVAILABLE = False
    logger.warning("PyPDF2 not available - PDF metadata extraction will be limited")

try:
    import pytesseract
    PYTESSERACT_AVAILABLE = True
except ImportError:
    PYTESSERACT_AVAILABLE = False
    logger.warning("pytesseract not available - OCR fallback will be limited")

try:
    import boto3
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False
    logger.warning("boto3 not available - Amazon Textract OCR will not be available")


# -----------------------------------------------------------------------------
# PDF Processor Class
# -----------------------------------------------------------------------------


class PDFProcessor:
    """Process PDF files to extract text, images, and metadata for WAFR assessment."""

    def __init__(
        self,
        aws_region: str = DEFAULT_AWS_REGION,
        use_textract: bool = True,
        ocr_fallback: bool = True,
    ):
        """
        Initialize PDF processor with available libraries.

        Args:
            aws_region: AWS region for Textract (if used).
            use_textract: Use Amazon Textract for OCR.
            ocr_fallback: Fallback to pytesseract if Textract unavailable.
        """
        self.logger = logger
        self.aws_region = aws_region
        self.use_textract = use_textract
        self.ocr_fallback = ocr_fallback
        self._textract_client = None

        self._log_available_dependencies()

    # -------------------------------------------------------------------------
    # Initialization & Dependencies
    # -------------------------------------------------------------------------

    def _log_available_dependencies(self) -> None:
        """Log which PDF processing libraries are available."""
        available = self._get_available_libraries()

        if available:
            self.logger.info(f"PDF processing libraries available: {', '.join(available)}")
        else:
            self.logger.warning(
                "No PDF processing libraries available - "
                "install pdfplumber, Pillow, pdf2image, or PyPDF2"
            )

    def _get_available_libraries(self) -> List[str]:
        """Get list of available PDF processing libraries."""
        libraries = [
            ("pdfplumber", PDFPLUMBER_AVAILABLE),
            ("Pillow", PILLOW_AVAILABLE),
            ("pdf2image", PDF2IMAGE_AVAILABLE),
            ("PyPDF2", PYPDF2_AVAILABLE),
            ("pytesseract", PYTESSERACT_AVAILABLE),
            ("boto3", BOTO3_AVAILABLE),
        ]
        return [name for name, available in libraries if available]

    @property
    def textract_client(self):
        """Lazy initialization of Textract client."""
        if self._textract_client is None and self.use_textract and BOTO3_AVAILABLE:
            try:
                self._textract_client = boto3.client(
                    "textract",
                    region_name=self.aws_region,
                )
            except Exception as e:
                self.logger.warning(f"Failed to initialize Textract client: {e}")
        return self._textract_client

    # -------------------------------------------------------------------------
    # Text Extraction
    # -------------------------------------------------------------------------

    def extract_text(self, pdf_path: str) -> str:
        """
        Extract text content from PDF file.

        Tries text extraction first, then OCR for scanned PDFs.

        Args:
            pdf_path: Path to PDF file.

        Returns:
            Extracted text content.

        Raises:
            FileNotFoundError: If PDF file does not exist.
        """
        self._validate_file_exists(pdf_path)

        # Try pdfplumber first (best for text extraction)
        extracted_text = self._extract_text_with_pdfplumber(pdf_path)
        if self._is_sufficient_text(extracted_text):
            return extracted_text

        # Fallback to PyPDF2
        extracted_text = self._extract_text_with_pypdf2(pdf_path)
        if self._is_sufficient_text(extracted_text):
            return extracted_text

        # If text extraction failed or got minimal text, try OCR
        self.logger.info("Attempting OCR extraction for scanned PDF")
        ocr_text = self._extract_with_ocr(pdf_path)
        if ocr_text:
            return ocr_text

        self.logger.error("No PDF text extraction method available")
        return ""

    def _extract_text_with_pdfplumber(self, pdf_path: str) -> str:
        """Extract text using pdfplumber library."""
        if not PDFPLUMBER_AVAILABLE:
            return ""

        try:
            text_content = []
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages, 1):
                    text = page.extract_text()
                    if text:
                        text_content.append(f"\n--- Page {page_num} ---\n{text}")

                extracted_text = "\n".join(text_content)
                text_length = len(extracted_text.strip())

                if text_length >= MIN_TEXT_LENGTH_THRESHOLD:
                    self.logger.info(
                        f"Extracted text from {len(pdf.pages)} pages using pdfplumber"
                    )
                    return extracted_text
                else:
                    self.logger.info(
                        f"Low text content ({text_length} chars), attempting OCR"
                    )
                    return ""

        except Exception as e:
            self.logger.warning(f"pdfplumber extraction failed: {e}, trying PyPDF2")
            return ""

    def _extract_text_with_pypdf2(self, pdf_path: str) -> str:
        """Extract text using PyPDF2 library."""
        if not PYPDF2_AVAILABLE:
            return ""

        try:
            text_content = []
            with open(pdf_path, "rb") as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page_num, page in enumerate(pdf_reader.pages, 1):
                    text = page.extract_text()
                    if text:
                        text_content.append(f"\n--- Page {page_num} ---\n{text}")

                extracted_text = "\n".join(text_content)
                text_length = len(extracted_text.strip())

                if text_length >= MIN_TEXT_LENGTH_THRESHOLD:
                    self.logger.info(
                        f"Extracted text from {len(pdf_reader.pages)} pages using PyPDF2"
                    )
                    return extracted_text
                else:
                    self.logger.info(
                        f"Low text content ({text_length} chars), attempting OCR"
                    )
                    return ""

        except Exception as e:
            self.logger.warning(f"PyPDF2 extraction failed: {e}")
            return ""

    def _is_sufficient_text(self, text: str) -> bool:
        """Check if extracted text meets minimum threshold."""
        return len(text.strip()) >= MIN_TEXT_LENGTH_THRESHOLD

    # -------------------------------------------------------------------------
    # OCR Extraction
    # -------------------------------------------------------------------------

    def _extract_with_ocr(self, pdf_path: str) -> str:
        """
        Extract text using OCR (Textract or pytesseract).

        Args:
            pdf_path: Path to PDF file.

        Returns:
            Extracted text from OCR.
        """
        # Try Amazon Textract first
        if self.use_textract and self.textract_client:
            try:
                return self._extract_with_textract(pdf_path)
            except Exception as e:
                self.logger.warning(f"Textract extraction failed: {e}")
                if self.ocr_fallback:
                    self.logger.info("Falling back to pytesseract")

        # Fallback to pytesseract
        if self.ocr_fallback and PYTESSERACT_AVAILABLE and PDF2IMAGE_AVAILABLE:
            try:
                return self._extract_with_pytesseract(pdf_path)
            except Exception as e:
                self.logger.warning(f"pytesseract extraction failed: {e}")

        return ""

    def _extract_with_textract(self, pdf_path: str) -> str:
        """
        Extract text using Amazon Textract.

        Args:
            pdf_path: Path to PDF file.

        Returns:
            Extracted text.

        Raises:
            Exception: If Textract extraction fails.
        """
        self.logger.info("Using Amazon Textract for OCR")

        try:
            with open(pdf_path, "rb") as f:
                document_bytes = f.read()

            # For single-page documents, use synchronous API
            # For multi-page, would need async API with S3
            response = self.textract_client.detect_document_text(
                Document={"Bytes": document_bytes}
            )

            text_blocks = self._parse_textract_response(response)
            extracted_text = "\n".join(text_blocks)

            self.logger.info(f"Textract extracted {len(extracted_text)} characters")
            return extracted_text

        except Exception as e:
            self.logger.error(f"Textract extraction failed: {e}")
            raise

    def _parse_textract_response(self, response: Dict) -> List[str]:
        """Parse Textract response to extract text lines."""
        text_blocks = []
        for block in response.get("Blocks", []):
            if block["BlockType"] == "LINE":
                text_blocks.append(block.get("Text", ""))
        return text_blocks

    def _extract_with_pytesseract(self, pdf_path: str) -> str:
        """
        Extract text using pytesseract (local OCR).

        Args:
            pdf_path: Path to PDF file.

        Returns:
            Extracted text.

        Raises:
            ImportError: If pdf2image is not available.
            Exception: If OCR extraction fails.
        """
        self.logger.info("Using pytesseract for OCR")

        if not PDF2IMAGE_AVAILABLE:
            raise ImportError("pdf2image required for pytesseract OCR")

        try:
            from pdf2image import convert_from_path
            import pytesseract

            images = convert_from_path(pdf_path, dpi=DEFAULT_DPI_OCR)

            text_parts = []
            for page_num, image in enumerate(images, 1):
                text = pytesseract.image_to_string(image)
                if text.strip():
                    text_parts.append(f"\n--- Page {page_num} (OCR) ---\n{text}")

            extracted_text = "\n".join(text_parts)
            self.logger.info(
                f"pytesseract extracted {len(extracted_text)} characters "
                f"from {len(images)} pages"
            )
            return extracted_text

        except ImportError as e:
            self.logger.error(f"OCR dependencies not available: {e}")
            raise
        except Exception as e:
            self.logger.error(f"pytesseract extraction failed: {e}")
            raise

    # -------------------------------------------------------------------------
    # Image Extraction
    # -------------------------------------------------------------------------

    def extract_images(
        self,
        pdf_path: str,
        output_dir: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Extract images/diagrams from PDF file.

        Args:
            pdf_path: Path to PDF file.
            output_dir: Optional directory to save extracted images.

        Returns:
            List of image dictionaries with metadata.

        Raises:
            FileNotFoundError: If PDF file does not exist.
        """
        self._validate_file_exists(pdf_path)

        images = []

        # Method 1: Extract embedded images using pdfplumber
        embedded_images = self._extract_embedded_images(pdf_path)
        images.extend(embedded_images)

        # Method 2: Convert PDF pages to images (for diagram extraction)
        page_images = self._convert_pages_to_images(pdf_path)
        images.extend(page_images)

        return images

    def _extract_embedded_images(self, pdf_path: str) -> List[Dict[str, Any]]:
        """Extract embedded images using pdfplumber."""
        if not PDFPLUMBER_AVAILABLE:
            return []

        images = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages, 1):
                    page_images = page.images
                    for img_num, img in enumerate(page_images, 1):
                        images.append({
                            "page": page_num,
                            "image_number": img_num,
                            "x0": img.get("x0"),
                            "y0": img.get("y0"),
                            "x1": img.get("x1"),
                            "y1": img.get("y1"),
                            "width": img.get("width"),
                            "height": img.get("height"),
                            "type": "embedded",
                        })

            if images:
                self.logger.info(
                    f"Found {len(images)} embedded images using pdfplumber"
                )

        except Exception as e:
            self.logger.warning(f"pdfplumber image extraction failed: {e}")

        return images

    def _convert_pages_to_images(self, pdf_path: str) -> List[Dict[str, Any]]:
        """Convert PDF pages to images for diagram extraction."""
        if not (PDF2IMAGE_AVAILABLE and PILLOW_AVAILABLE):
            return []

        images = []
        try:
            pdf_images = convert_from_path(pdf_path, dpi=DEFAULT_DPI_IMAGES)
            for page_num, img in enumerate(pdf_images, 1):
                images.append({
                    "page": page_num,
                    "image": img,  # PIL Image object
                    "type": "page_image",
                    "width": img.width,
                    "height": img.height,
                })

            self.logger.info(f"Converted {len(pdf_images)} pages to images")

        except Exception as e:
            self.logger.warning(f"PDF to image conversion failed: {e}")

        return images

    # -------------------------------------------------------------------------
    # Metadata Extraction
    # -------------------------------------------------------------------------

    def extract_metadata(self, pdf_path: str) -> Dict[str, Any]:
        """
        Extract metadata from PDF file.

        Args:
            pdf_path: Path to PDF file.

        Returns:
            Dictionary with PDF metadata.

        Raises:
            FileNotFoundError: If PDF file does not exist.
        """
        self._validate_file_exists(pdf_path)

        metadata = self._create_base_metadata(pdf_path)

        # Try PyPDF2 for metadata
        self._extract_metadata_with_pypdf2(pdf_path, metadata)

        # Try pdfplumber for page count if not already set
        if metadata["num_pages"] == 0:
            self._extract_page_count_with_pdfplumber(pdf_path, metadata)

        return metadata

    def _create_base_metadata(self, pdf_path: str) -> Dict[str, Any]:
        """Create base metadata dictionary with file information."""
        return {
            "file_path": pdf_path,
            "file_name": os.path.basename(pdf_path),
            "file_size": os.path.getsize(pdf_path),
            "title": None,
            "author": None,
            "subject": None,
            "creator": None,
            "producer": None,
            "creation_date": None,
            "modification_date": None,
            "num_pages": 0,
        }

    def _extract_metadata_with_pypdf2(
        self,
        pdf_path: str,
        metadata: Dict[str, Any],
    ) -> None:
        """Extract metadata using PyPDF2 and update metadata dict in place."""
        if not PYPDF2_AVAILABLE:
            return

        try:
            with open(pdf_path, "rb") as file:
                pdf_reader = PyPDF2.PdfReader(file)
                metadata["num_pages"] = len(pdf_reader.pages)

                if pdf_reader.metadata:
                    self._populate_document_metadata(pdf_reader.metadata, metadata)

        except Exception as e:
            self.logger.warning(f"PyPDF2 metadata extraction failed: {e}")

    def _populate_document_metadata(
        self,
        pdf_metadata: Any,
        metadata: Dict[str, Any],
    ) -> None:
        """Populate metadata dict with PDF document metadata."""
        metadata["title"] = pdf_metadata.get("/Title")
        metadata["author"] = pdf_metadata.get("/Author")
        metadata["subject"] = pdf_metadata.get("/Subject")
        metadata["creator"] = pdf_metadata.get("/Creator")
        metadata["producer"] = pdf_metadata.get("/Producer")
        metadata["creation_date"] = pdf_metadata.get("/CreationDate")
        metadata["modification_date"] = pdf_metadata.get("/ModDate")

    def _extract_page_count_with_pdfplumber(
        self,
        pdf_path: str,
        metadata: Dict[str, Any],
    ) -> None:
        """Extract page count using pdfplumber."""
        if not PDFPLUMBER_AVAILABLE:
            return

        try:
            with pdfplumber.open(pdf_path) as pdf:
                metadata["num_pages"] = len(pdf.pages)
        except Exception as e:
            self.logger.warning(f"pdfplumber page count failed: {e}")

    # -------------------------------------------------------------------------
    # Table Extraction
    # -------------------------------------------------------------------------

    def extract_tables(self, pdf_path: str) -> List[Dict[str, Any]]:
        """
        Extract tables from PDF file.

        Args:
            pdf_path: Path to PDF file.

        Returns:
            List of extracted tables.

        Raises:
            FileNotFoundError: If PDF file does not exist.
        """
        if not PDFPLUMBER_AVAILABLE:
            self.logger.warning("pdfplumber required for table extraction")
            return []

        self._validate_file_exists(pdf_path)

        tables = []

        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages, 1):
                    page_tables = page.extract_tables()
                    for table_num, table in enumerate(page_tables, 1):
                        if table:
                            tables.append({
                                "page": page_num,
                                "table_number": table_num,
                                "data": table,
                                "rows": len(table),
                                "cols": len(table[0]) if table else 0,
                            })

            if tables:
                self.logger.info(f"Extracted {len(tables)} tables from PDF")

        except Exception as e:
            self.logger.warning(f"Table extraction failed: {e}")

        return tables

    # -------------------------------------------------------------------------
    # PDF Analysis
    # -------------------------------------------------------------------------

    def is_scanned_pdf(self, pdf_path: str) -> bool:
        """
        Check if PDF is scanned (image-based) rather than text-based.

        Args:
            pdf_path: Path to PDF file.

        Returns:
            True if PDF appears to be scanned.
        """
        if not os.path.exists(pdf_path):
            return False

        text = self.extract_text(pdf_path)
        return self._is_text_quality_poor(text)

    def _is_text_quality_poor(self, text: str) -> bool:
        """Check if extracted text quality indicates a scanned PDF."""
        text_length = len(text.strip())

        # Very little text extracted indicates scanned PDF
        if text_length < MIN_TEXT_LENGTH_THRESHOLD:
            return True

        # Check if text is mostly whitespace or garbage
        if text_length > 0:
            non_whitespace = sum(1 for c in text if c.isalnum())
            alphanumeric_ratio = non_whitespace / text_length
            if alphanumeric_ratio < MIN_ALPHANUMERIC_RATIO:
                return True

        return False

    # -------------------------------------------------------------------------
    # Complete PDF Processing
    # -------------------------------------------------------------------------

    def process_pdf(self, pdf_path: str) -> Dict[str, Any]:
        """
        Process PDF file and extract all available content.

        Args:
            pdf_path: Path to PDF file.

        Returns:
            Dictionary with all extracted content including text, images,
            tables, metadata, and processing status.
        """
        self.logger.info(f"Processing PDF: {pdf_path}")

        result = self._create_empty_result()

        try:
            result["metadata"] = self.extract_metadata(pdf_path)

            self._extract_text_safely(pdf_path, result)
            self._extract_images_safely(pdf_path, result)
            self._extract_tables_safely(pdf_path, result)

            result["is_scanned"] = self.is_scanned_pdf(pdf_path)

            self._log_processing_summary(result)

        except Exception as e:
            result["processing_status"] = "error"
            result["errors"].append(f"PDF processing failed: {str(e)}")
            self.logger.error(f"PDF processing error: {e}", exc_info=True)

        return result

    def _create_empty_result(self) -> Dict[str, Any]:
        """Create empty result dictionary for PDF processing."""
        return {
            "text": "",
            "images": [],
            "tables": [],
            "metadata": {},
            "is_scanned": False,
            "processing_status": "success",
            "errors": [],
        }

    def _extract_text_safely(self, pdf_path: str, result: Dict[str, Any]) -> None:
        """Extract text with error handling."""
        try:
            result["text"] = self.extract_text(pdf_path)
            if not result["text"]:
                result["errors"].append("No text extracted from PDF")
        except Exception as e:
            result["errors"].append(f"Text extraction error: {str(e)}")
            self.logger.error(f"Text extraction failed: {e}")

    def _extract_images_safely(self, pdf_path: str, result: Dict[str, Any]) -> None:
        """Extract images with error handling."""
        try:
            result["images"] = self.extract_images(pdf_path)
        except Exception as e:
            result["errors"].append(f"Image extraction error: {str(e)}")
            self.logger.error(f"Image extraction failed: {e}")

    def _extract_tables_safely(self, pdf_path: str, result: Dict[str, Any]) -> None:
        """Extract tables with error handling."""
        try:
            result["tables"] = self.extract_tables(pdf_path)
        except Exception as e:
            result["errors"].append(f"Table extraction error: {str(e)}")
            self.logger.warning(f"Table extraction failed: {e}")

    def _log_processing_summary(self, result: Dict[str, Any]) -> None:
        """Log summary of PDF processing results."""
        self.logger.info(
            f"PDF processed: {result['metadata']['num_pages']} pages, "
            f"{len(result['text'])} chars text, "
            f"{len(result['images'])} images, "
            f"{len(result['tables'])} tables"
        )

    # -------------------------------------------------------------------------
    # Batch Processing
    # -------------------------------------------------------------------------

    def process_multiple_pdfs(self, pdf_paths: List[str]) -> Dict[str, Any]:
        """
        Process multiple PDF files.

        Args:
            pdf_paths: List of PDF file paths.

        Returns:
            Dictionary with combined results from all PDFs.
        """
        self.logger.info(f"Processing {len(pdf_paths)} PDF files")

        all_text = []
        all_images = []
        all_tables = []
        all_metadata = []
        combined_errors = []

        for pdf_path in pdf_paths:
            self._process_single_pdf_for_batch(
                pdf_path,
                all_text,
                all_images,
                all_tables,
                all_metadata,
                combined_errors,
            )

        return {
            "text": "\n".join(all_text),
            "images": all_images,
            "tables": all_tables,
            "metadata": all_metadata,
            "num_pdfs": len(pdf_paths),
            "errors": combined_errors,
            "processing_status": "success" if not combined_errors else "partial",
        }

    def _process_single_pdf_for_batch(
        self,
        pdf_path: str,
        all_text: List[str],
        all_images: List[Dict],
        all_tables: List[Dict],
        all_metadata: List[Dict],
        combined_errors: List[str],
    ) -> None:
        """Process a single PDF and append results to batch collections."""
        try:
            result = self.process_pdf(pdf_path)

            if result["text"]:
                file_name = os.path.basename(pdf_path)
                all_text.append(f"\n\n=== PDF: {file_name} ===\n{result['text']}")

            all_images.extend(result["images"])
            all_tables.extend(result["tables"])
            all_metadata.append(result["metadata"])
            combined_errors.extend(result["errors"])

        except Exception as e:
            error_msg = f"Failed to process {pdf_path}: {str(e)}"
            combined_errors.append(error_msg)
            self.logger.error(error_msg)

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------

    def _validate_file_exists(self, pdf_path: str) -> None:
        """
        Validate that the PDF file exists.

        Raises:
            FileNotFoundError: If file does not exist.
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")


# -----------------------------------------------------------------------------
# Factory Function
# -----------------------------------------------------------------------------


def create_pdf_processor(
    aws_region: str = DEFAULT_AWS_REGION,
    use_textract: bool = True,
    ocr_fallback: bool = True,
) -> PDFProcessor:
    """
    Create and return a PDFProcessor instance.

    Args:
        aws_region: AWS region for Textract.
        use_textract: Whether to use Amazon Textract for OCR.
        ocr_fallback: Whether to fallback to pytesseract if Textract unavailable.

    Returns:
        Configured PDFProcessor instance.
    """
    return PDFProcessor(
        aws_region=aws_region,
        use_textract=use_textract,
        ocr_fallback=ocr_fallback,
    )