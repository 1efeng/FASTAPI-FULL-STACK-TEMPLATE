from pathlib import Path

TRAVEL_PLANNING_SKILL_PATH = (
    Path(__file__).parent / "skills" / "travel-planning" / "SKILL.md"
)


def load_travel_planning_skill() -> str:
    """Load the travel-planning instructions used by the chat agent."""
    return TRAVEL_PLANNING_SKILL_PATH.read_text(encoding="utf-8").strip()
