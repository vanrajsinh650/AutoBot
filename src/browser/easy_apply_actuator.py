"""
Policy Enforcement Module for LinkedIn Easy Apply in AutoBot v2.1.
Enforces complete prohibition of automated form filling, modal traversal,
and automated submission on LinkedIn Easy Apply.
"""

from src.application.workflows import LinkedInPolicyViolationError
from src.utils.logger import logger


class EasyApplyActuator:
    """
    Deprecated / Prohibited.
    Automated LinkedIn Easy Apply form filling and submission is strictly forbidden.
    Raises LinkedInPolicyViolationError on any initialization or method call.
    """

    MAX_STEPS = 0

    def __init__(self, *args, **kwargs):
        raise LinkedInPolicyViolationError(
            "Compliance Policy Violation: Automated Easy Apply modal traversal, form filling, "
            "and submission on LinkedIn is strictly prohibited. "
            "Applications to LinkedIn jobs must be completed directly on LinkedIn by the candidate "
            "using the candidate-assisted workflow."
        )

    async def apply(self, *args, **kwargs) -> bool:
        raise LinkedInPolicyViolationError(
            "Compliance Policy Violation: Automated submission to LinkedIn is strictly prohibited."
        )
