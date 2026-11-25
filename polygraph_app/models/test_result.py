"""
Test Result Model for Polygraph Scoring.

Represents a single test result with all required fields:
- status: "COMPLETED" | "SKIPPED" 
- passing_categories: list of categories that passed
- failing_categories: list of categories that failed  
- result, exit_code, ttft_ms_val, actual_tokens_used for complete data

This model was wired from #7b fixes but lost during branch reset.
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class TestResult:
    """Represents the result of a single Polygraph test."""
    
    test_id: str
    test_name: str
    description: str
    
    # Status for aggregator logic
    status: str = "COMPLETED"  # COMPLETED | SKIPPED
    
    # Category assessments (from scoring dimensions)
    passing_categories: List[str] = field(default_factory=list)
    failing_categories: List[str] = field(default_factory=list)
    
    # Additional fields for reporting completeness
    result: str = "success"
    exit_code: int = 0
    
    # TTFT and token metrics (from F10/F11/v2.0-grading)
    ttft_ms_val: float | None = None
    actual_tokens_used: int | None = None
    
    def is_passed(self) -> bool:
        """Check if this test passed all its dimensions."""
        return self.status == "COMPLETED" and len(self.failing_categories) == 0
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "test_id": self.test_id,
            "test_name": self.test_name,
            "description": self.description,
            "status": self.status,
            "passing_categories": self.passing_categories,
            "failing_categories": self.failing_categories,
            "result": self.result,
            "exit_code": self.exit_code,
            "ttft_ms_val": self.ttft_ms_val,
            "actual_tokens_used": self.actual_tokens_used,
        }
