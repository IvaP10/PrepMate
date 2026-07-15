import unittest

from interview_profiles import PROFILE_CONFIGS, get_profile_config, get_profile_duration


class InterviewProfileConfigTests(unittest.TestCase):
    def test_profiles_are_versioned_and_use_product_labels(self):
        self.assertEqual(PROFILE_CONFIGS["top_tier"]["label"], "Top Tier")
        self.assertEqual(PROFILE_CONFIGS["mid_tier"]["label"], "Mid Tier")
        self.assertEqual(PROFILE_CONFIGS["startup"]["label"], "Startup")
        self.assertTrue(all(config.get("config_version") for config in PROFILE_CONFIGS.values()))

    def test_duration_targets_match_company_profile(self):
        self.assertEqual(get_profile_duration("top_tier"), {"min_minutes": 45, "target_minutes": 60, "max_minutes": 60})
        self.assertEqual(get_profile_duration("mid_tier"), {"min_minutes": 45, "target_minutes": 50, "max_minutes": 60})
        self.assertEqual(get_profile_duration("startup"), {"min_minutes": 45, "target_minutes": 45, "max_minutes": 60})
        self.assertEqual(get_profile_duration("custom"), {"min_minutes": 45, "target_minutes": 50, "max_minutes": 60})

    def test_every_profile_stays_inside_the_natural_interview_window(self):
        for config in PROFILE_CONFIGS.values():
            duration = config["duration"]
            self.assertGreaterEqual(duration["min_minutes"], 45)
            self.assertLessEqual(duration["max_minutes"], 60)
            self.assertLessEqual(duration["min_minutes"], duration["target_minutes"])
            self.assertLessEqual(duration["target_minutes"], duration["max_minutes"])

    def test_each_profile_has_interview_followup_behavioral_and_technical_instructions(self):
        for profile_type in ("top_tier", "mid_tier", "startup"):
            config = get_profile_config(profile_type)
            self.assertIn("interview_instruction", config)
            self.assertIn("followup_instruction", config)
            self.assertIn("behavioral_instruction", config)
            self.assertIn("technical_instruction", config)
            self.assertTrue(config["technical_rounds"])
            self.assertGreater(len(config["interview_instruction"]), 80)
            self.assertGreater(len(config["technical_instruction"]), 80)

    def test_top_tier_and_startup_are_distinct_modes(self):
        top_tier = PROFILE_CONFIGS["top_tier"]["technical_instruction"].lower()
        startup = PROFILE_CONFIGS["startup"]["technical_instruction"].lower()

        self.assertIn("dynamic programming", top_tier)
        self.assertIn("time pressure", startup)
        self.assertNotEqual(top_tier, startup)


if __name__ == "__main__":
    unittest.main()
