import tempfile
import unittest

from pre_interview import _extract_target_role, extract_resume_with_rules
from resume_parser import parse_resume_structured, _normalize_text


class ResumeParserTests(unittest.TestCase):
    def test_extract_target_role_from_experience_header(self):
        text = """
        Jane Doe
        EXPERIENCE
        Senior Software Engineer at Acme Corp
        Jan 2022 - Present
        Built APIs
        """
        sections = {
            "experience": ["Senior Software Engineer at Acme Corp", "Jan 2022 - Present", "Built APIs"],
            "summary": [],
        }
        role = _extract_target_role(text, sections)
        self.assertEqual(role, "Senior Software Engineer")

    def test_rule_extraction_includes_target_role(self):
        text = """
        Alex Kim
        alex@example.com
        EXPERIENCE
        Data Analyst at Contoso
        2021 - 2023
        SQL, Python, Tableau
        SKILLS
        Python, SQL, Tableau
        """
        profile = extract_resume_with_rules(
            text,
            {"email": "alex@example.com", "phone": None},
            {"linkedin": None, "github": None, "portfolio": None},
            {"parser": "pymupdf", "links": []},
        )
        self.assertEqual(profile.get("target_role"), "Data Analyst")
        self.assertIn("Python", profile.get("skills", []))

    def test_parse_pdf_fast_skips_ocr_metadata(self):
        try:
            import fitz
        except ImportError:
            self.skipTest("pymupdf not installed")

        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "John Smith\nSoftware Engineer at Example Inc\nPython, React, AWS")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            path = tmp.name
        doc.save(path)
        doc.close()

        try:
            parsed = parse_resume_structured(path, fast=True)
            self.assertTrue(parsed.get("metadata", {}).get("fast"))
            self.assertIn("Software Engineer", parsed.get("text", ""))
            self.assertEqual(parsed.get("metadata", {}).get("ocr_pages"), 0)
        finally:
            import os
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
