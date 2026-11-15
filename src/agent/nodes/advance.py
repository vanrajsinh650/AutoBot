"""
Advance Node for AutoBot v2 LangGraph Agent.

Educational Concept:
Pagination and multi-keyword sequencing represent the exploration frontier of the bot:
1. Pagination Stepping:
   When `unprocessed_jobs` is drained, the advance node checks if `current_page < max_pages`.
   If so, it increments `current_page` to fetch the next batch from the search results.
2. Keyword Stepping:
   If maximum pagination for the current keyword has been reached, the advance node
   increments `keyword_index` and resets `current_page = 1` to explore the next query.
3. Termination Sentinel:
   When all keywords and pagination bounds have been thoroughly explored, it sets
   `is_complete = True`, signaling to the conditional edge that the search space is exhausted.
"""

from typing import Any, Dict

from src.agent.state import AgentState
from src.utils.logger import logger


class AdvanceNode:
    """
    Advances pagination or steps to the next search keyword when the current queue is empty.
    """

    def __call__(self, state: AgentState) -> Dict[str, Any]:
        current_page = state.get("current_page", 1)
        max_pages = state.get("max_pages", 5)
        keywords = state.get("keywords", [])
        keyword_index = state.get("keyword_index", 0)

        # ── 1. Check if more pages exist for current keyword ──────────
        if current_page < max_pages:
            next_page = current_page + 1
            logger.info(
                f"[agent]⏭ Advancing to page {next_page} of {max_pages} for '{state.get('current_keyword')}'[/agent]"
            )
            return {
                "current_page": next_page,
                "is_complete": False,
                "status_message": f"Stepping to page {next_page} for '{state.get('current_keyword')}'",
            }

        # ── 2. Pages exhausted: step to next keyword ───────────────────
        next_keyword_index = keyword_index + 1
        if next_keyword_index < len(keywords):
            next_keyword = keywords[next_keyword_index]
            logger.info(
                f"[agent]⏭ Pages exhausted for '{state.get('current_keyword')}'. "
                f"Stepping to next keyword: '{next_keyword}'[/agent]"
            )
            return {
                "keyword_index": next_keyword_index,
                "current_keyword": next_keyword,
                "current_page": 1,
                "is_complete": False,
                "status_message": f"Stepping to next keyword: '{next_keyword}'",
            }

        # ── 3. All keywords and pages fully exhausted ──────────────────
        logger.info("[agent]🏁 All search keywords and pages fully explored.[/agent]")
        return {
            "is_complete": True,
            "status_message": "Search space exhausted.",
        }
