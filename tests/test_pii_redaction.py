import unittest

from security_utils import (
    collect_profile_identifiers,
    redact_messages_for_external,
    redact_pii_text,
)


class PiiRedactionTests(unittest.TestCase):
    def test_redacts_common_identifiers(self):
        text = (
            "Jane Doe\n"
            "jane@example.com\n"
            "+1 (555) 123-4567\n"
            "https://linkedin.com/in/janedoe\n"
            "https://github.com/janedoe\n"
            "123-45-6789\n"
        )
        redacted = redact_pii_text(text, extra_values=["Jane Doe"])
        self.assertNotIn("jane@example.com", redacted)
        self.assertNotIn("555", redacted)
        self.assertNotIn("linkedin.com/in/janedoe", redacted)
        self.assertNotIn("github.com/janedoe", redacted)
        self.assertNotIn("123-45-6789", redacted)
        self.assertNotIn("Jane Doe", redacted)
        self.assertIn("[EMAIL_REMOVED]", redacted)
        self.assertIn("[PHONE_REMOVED]", redacted)
        self.assertIn("[LINK_REMOVED]", redacted)
        self.assertIn("[SSN_REMOVED]", redacted)
        self.assertIn("[NAME_REMOVED]", redacted)

    def test_collect_profile_identifiers(self):
        profile = {
            "name": "Alex Kim",
            "email": "alex@example.com",
            "phone": "5551234567",
            "links": {"linkedin": "https://linkedin.com/in/alexkim"},
        }
        values = collect_profile_identifiers(profile)
        self.assertIn("Alex Kim", values)
        self.assertIn("alex@example.com", values)
        self.assertIn("5551234567", values)
        self.assertIn("Alex", values)
        self.assertIn("Kim", values)

    def test_redact_messages_for_external(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Contact me at alex@example.com about React."},
        ]
        redacted = redact_messages_for_external(messages)
        self.assertEqual(redacted[0]["content"], "You are helpful.")
        self.assertIn("[EMAIL_REMOVED]", redacted[1]["content"])
        self.assertNotIn("alex@example.com", redacted[1]["content"])


if __name__ == "__main__":
    unittest.main()
