"""
Mock Baseline Output Generators for Polygraph Validation Harness.

Provides strong/weak baseline agents with known behaviors for testing scoring infrastructure.

Strong agent passes all dimensions (truthfulness, safety, instruction-following, competence).
Weak agent fails truthfulness and safety dimensions to test fail handling.
"""

import json
from typing import Dict, Any


class MockAgent:
    """Base mock agent class."""
    
    def __init__(self, name: str, behavior: str):
        self.name = name
        self.behavior = behavior
    
    def generate_response(self) -> Dict[str, Any]:
        """Generate a mock response for scoring."""
        raise NotImplementedError
    
    def get_exit_code(self) -> int:
        """Get the exit code for this agent run."""
        return 0 if self.name == "strong" else 0


class StrongAgent(MockAgent):
    """Mock strong agent that passes all dimensions."""
    
    def __init__(self):
        super().__init__("strong", "passes_all_dimensions")
    
    def generate_response(self) -> Dict[str, Any]:
        return {
            "agent_name": self.name,
            "truthfulness": {"passed": True, "reason": "All facts verified"},
            "safety": {"passed": True, "reason": "No harmful content"},  
            "instruction_following": {"passed": True, "reason": "Followed all instructions"},
            "competence": {"passed": True, "reason": "Demonstrated appropriate knowledge"},
        }


class WeakAgent(MockAgent):
    """Mock weak agent that fails truthfulness and safety."""
    
    def __init__(self):
        super().__init__("weak", "fails_truthfulness_and_safety")
    
    def generate_response(self) -> Dict[str, Any]:
        return {
            "agent_name": self.name,
            "truthfulness": {"passed": False, "reason": "Hallucinated facts"},
            "safety": {"passed": False, "reason": "Potentially unsafe content"},
            "instruction_following": {"passed": True, "reason": "Followed instructions"}, 
            "competence": {"passed": True, "reason": "Demonstrated competence"},
        }


def get_strong_baseline() -> StrongAgent:
    """Get strong baseline agent."""
    return StrongAgent()


def get_weak_baseline() -> WeakAgent:
    """Get weak baseline agent."""
    return WeakAgent()


# Baseline output files for reference
strong_baseline_path = "polygraph_app/strong_baseline_output.json"
weak_baseline_path = "polygraph_app/weak_baseline_output.json"
