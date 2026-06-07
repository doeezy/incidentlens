from __future__ import annotations

import unittest

from app.config import Settings
from app.services.log.enrich_service import (
    LlmLogEnrichmentService,
    _LlmEnrichedLogSchema,
)


class LlmLogEnrichmentServiceTest(unittest.TestCase):
    def test_normalize_output_constructs_enriched_log(self) -> None:
        service = LlmLogEnrichmentService(Settings(openai_api_key=None))
        model = _LlmEnrichedLogSchema(
            module_name="auth",
            class_name="AuthService",
            method_name="login",
            log_level="WARN",
            stack_trace=None,
            error_type="ClassNotFoundException",
            error_message="JWT class missing",
            normalized_summary="JWT 클래스 로딩에 실패했습니다.",
            extracted_keywords=[" jwt ", "jwt", "class"],
            domain_tags=[" auth "],
            correction_notes="로그 레벨을 정규화했습니다.",
            parser_confidence="high",
        )

        output = service._normalize_output(model)

        self.assertEqual(output.module_name, "auth")
        self.assertEqual(output.log_level, "WARN")
        self.assertEqual(output.extracted_keywords, ["class", "jwt"])
        self.assertEqual(output.domain_tags, ["auth"])
        self.assertEqual(output.parser_confidence, "high")


if __name__ == "__main__":
    unittest.main()
