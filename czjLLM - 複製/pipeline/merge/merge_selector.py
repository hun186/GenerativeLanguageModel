from .event_strategy import EventStrategy
from .interview_strategy import InterviewStrategy
from .profile_strategy import ProfileStrategy
from .issue_strategy import IssueStrategy
from .report_strategy import ReportStrategy
from .legal_strategy import LegalStrategy
from .mixed_strategy import MixedStrategy


def get_merge_strategy(doc_type: str):
    mapping = {
        "event": EventStrategy,
        "interview": InterviewStrategy,
        "profile": ProfileStrategy,
        "issue": IssueStrategy,
        "report": ReportStrategy,
        "legal": LegalStrategy,
        "mixed": MixedStrategy,
    }
    return mapping.get(doc_type, MixedStrategy)()
