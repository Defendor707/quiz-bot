"""File parser - turli formatdagi fayllardan matn ajratish"""
import logging
from io import BytesIO
import docx
import PyPDF2

logger = logging.getLogger(__name__)


class FileParser:
    """Fayl tahlil qiluvchi - TXT, PDF, DOCX formatlarni qo'llab-quvvatlaydi"""
    
    @staticmethod
    def extract_from_txt(file_content: bytes) -> str:
        """TXT fayldan matn ajratish"""
        try:
            return file_content.decode('utf-8')
        except UnicodeDecodeError:
            return file_content.decode('utf-8', errors='ignore')
    
    @staticmethod
    def extract_from_pdf(file_content: bytes) -> str:
        """PDF fayldan matn ajratish"""
        try:
            pdf_file = BytesIO(file_content)
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            text = ""
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
            return text
        except Exception as e:
            logger.error(f"PDF xatolik: {e}")
            return ""
    
    @staticmethod
    def extract_from_docx(file_content: bytes) -> str:
        """DOCX fayldan matn ajratish"""
        try:
            doc_file = BytesIO(file_content)
            doc = docx.Document(doc_file)
            text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
            return text
        except Exception as e:
            logger.error(f"DOCX xatolik: {e}")
            return ""
    
    @staticmethod
    def extract_text(file_content: bytes, file_extension: str) -> str:
        """Fayl kengaytmasiga qarab matn ajratish"""
        extension = file_extension.lower()
        
        if extension == '.txt':
            return FileParser.extract_from_txt(file_content)
        elif extension == '.pdf':
            return FileParser.extract_from_pdf(file_content)
        elif extension in ['.docx', '.doc']:
            return FileParser.extract_from_docx(file_content)
        else:
            # Noma'lum format - UTF-8 sifatida o'qishga harakat
            try:
                return file_content.decode('utf-8')
            except (UnicodeDecodeError, UnicodeError, AttributeError) as e:
                logger.debug(f"Noma'lum format fayl UTF-8 decode xatolik: {e}")
                return file_content.decode('utf-8', errors='ignore')


# Alias for backward compatibility
FileAnalyzer = FileParser

