"""Resume upload and parsing endpoint."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.schemas import ResumeParseResponse

router = APIRouter()

# Skills we know how to detect
KNOWN_SKILLS = [
    "Python", "Java", "C++", "C#", "C", "JavaScript", "TypeScript",
    "R", "MATLAB", "SQL", "Rust", "Go", "Kotlin", "Swift",
    "PyTorch", "TensorFlow", "scikit-learn", "pandas", "NumPy",
    "OpenCV", "HuggingFace", "transformers",
    "machine learning", "deep learning", "NLP",
    "data analysis", "data visualization",
    "Linux", "Git", "Docker", "Kubernetes",
    "React", "Flask", "FastAPI", "Django", "Node.js",
    "AWS", "GCP", "Azure",
    "LaTeX", "Excel", "SPSS", "SAS", "Stata",
]

# Course pattern: 2-4 letters + space + 3-4 digits
COURSE_PATTERN = re.compile(r"\b([A-Z]{2,4})\s+(\d{3,4})\b")

EXPERIENCE_KEYWORDS = {
    "strong": ["led", "managed", "architected", "published", "co-author", "principal"],
    "some": ["assisted", "contributed", "developed", "implemented", "designed", "built"],
    "beginner": ["coursework", "class project", "learning", "familiar"],
}


def _extract_text_from_pdf(file_path: str) -> str:
    """Extract text from a PDF file. Uses PyPDF2 if available, else basic fallback."""
    try:
        import PyPDF2

        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            text_parts = []
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
            return "\n".join(text_parts)
    except ImportError:
        # Fallback: try pdfplumber
        try:
            import pdfplumber

            with pdfplumber.open(file_path) as pdf:
                return "\n".join(page.extract_text() or "" for page in pdf.pages)
        except ImportError:
            raise HTTPException(
                status_code=500,
                detail="No PDF parsing library available. Install PyPDF2 or pdfplumber.",
            )


def _extract_skills(text: str) -> list[str]:
    """Find known skills mentioned in resume text."""
    text_lower = text.lower()
    found = []
    for skill in KNOWN_SKILLS:
        if skill.lower() in text_lower:
            found.append(skill)
    return found


def _extract_coursework(text: str) -> list[str]:
    """Extract course identifiers like 'CS 124', 'ECE 220'."""
    matches = COURSE_PATTERN.findall(text)
    courses = [f"{dept} {num}" for dept, num in matches]
    return sorted(set(courses))


def _infer_experience_level(text: str) -> str:
    """Infer experience level from resume language."""
    text_lower = text.lower()

    for level in ["strong", "some", "beginner"]:
        keywords = EXPERIENCE_KEYWORDS[level]
        hits = sum(1 for kw in keywords if kw in text_lower)
        if level == "strong" and hits >= 2:
            return "strong"
        if level == "some" and hits >= 2:
            return "some"

    return "beginner"


@router.post("/resume/upload", response_model=ResumeParseResponse)
async def upload_resume(file: UploadFile = File(...)):
    """Upload and parse a PDF resume to extract profile data."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # Validate file type
    allowed_types = {"application/pdf", "application/x-pdf"}
    content_type = file.content_type or ""
    filename = file.filename.lower()

    if content_type not in allowed_types and not filename.endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are supported. Please upload a .pdf file.",
        )

    # Validate file size (max 5MB)
    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 5MB.")

    # Save to temp file and parse
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        raw_text = _extract_text_from_pdf(tmp_path)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to parse PDF: {str(e)}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if not raw_text.strip():
        return ResumeParseResponse(
            extracted_skills=[],
            extracted_coursework=[],
            experience_level="beginner",
            raw_text="",
            success=False,
            message="Could not extract text from PDF. The file may be image-based.",
        )

    skills = _extract_skills(raw_text)
    coursework = _extract_coursework(raw_text)
    experience = _infer_experience_level(raw_text)

    return ResumeParseResponse(
        extracted_skills=skills,
        extracted_coursework=coursework,
        experience_level=experience,
        raw_text=raw_text[:3000],  # Cap to avoid huge responses
        success=True,
        message=f"Extracted {len(skills)} skills, {len(coursework)} courses from resume.",
    )
