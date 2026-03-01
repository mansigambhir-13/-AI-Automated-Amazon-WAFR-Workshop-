"""
Smart Prompt Generator Agent - Generates context-aware prompts for gaps.

Uses Strands framework to create intelligent prompts that guide users
in answering WAFR questions.
"""

import logging
from typing import Any, Dict, List, Optional

from strands import Agent, tool

from wafr.agents.config import DEFAULT_MODEL_ID
from wafr.agents.model_config import get_strands_model
from wafr.agents.wafr_context import load_wafr_schema

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

MAX_HINTS_TO_DISPLAY = 3
MAX_QUICK_OPTIONS = 5

AGENT_NAME = "PromptGeneratorAgent"

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# System Prompt
# -----------------------------------------------------------------------------


def get_prompt_generator_system_prompt(
    wafr_schema: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Generate enhanced system prompt with WAFR context.

    Args:
        wafr_schema: Optional WAFR schema for additional context.

    Returns:
        System prompt string for the agent.
    """
    return """
You are an expert at generating intelligent, context-aware prompts to help users
answer WAFR (AWS Well-Architected Framework Review) questions.

PROMPT GENERATION PRINCIPLES:
1. Be clear and specific about what's needed for the WAFR question
2. Include relevant hints based on WAFR best practices from the schema
3. Provide example good answers based on best practice examples
4. Reference any related discussion from transcript (context hints)
5. Offer quick-select options for common answer patterns
6. Make prompts actionable and user-friendly
7. Align with WAFR pillar principles and best practices
8. For partial evidence: Show what we understood and ask for clarification
9. For incomplete knowledge: Request specific information needed
10. Always frame requests professionally and helpfully

PROMPT STRUCTURE:
- Question text (from WAFR schema)
- Pillar and criticality information
- Hints based on best practices (top 3)
- Context from transcript (if available)
- Example good answer (from best practices)
- Quick-select options (common answer patterns)

Use generate_smart_prompt() to create comprehensive prompts that guide users
to provide complete, WAFR-aligned answers.
"""


# -----------------------------------------------------------------------------
# Tool Definition
# -----------------------------------------------------------------------------


@tool
def generate_smart_prompt(
    question_id: str,
    question_text: str,
    pillar: str,
    criticality: str,
    hints: List[str],
    example_answer: Optional[str] = None,
    context_hint: Optional[str] = None,
    quick_options: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Generate a smart prompt for a gap question.

    Args:
        question_id: Question identifier.
        question_text: Full question text.
        pillar: Pillar name.
        criticality: Criticality level.
        hints: List of hints based on best practices.
        example_answer: Example good answer.
        context_hint: Context from transcript if available.
        quick_options: Quick-select answer options.

    Returns:
        Prompt dictionary with all components.
    """
    return {
        "question_id": question_id,
        "question_text": question_text,
        "pillar": pillar,
        "criticality": criticality,
        "hints": hints,
        "example_answer": example_answer,
        "context_hint": context_hint,
        "quick_options": quick_options or [],
        "prompt_text": _format_prompt_text(
            question_text=question_text,
            pillar=pillar,
            hints=hints,
            example_answer=example_answer,
            context_hint=context_hint,
        ),
    }


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------


def _format_prompt_text(
    question_text: str,
    pillar: str,
    hints: List[str],
    example_answer: Optional[str] = None,
    context_hint: Optional[str] = None,
) -> str:
    """
    Format prompt text from components.

    Args:
        question_text: The question to display.
        pillar: The WAFR pillar name.
        hints: List of hints to include.
        example_answer: Optional example answer.
        context_hint: Optional context from transcript.

    Returns:
        Formatted prompt text string.
    """
    lines = [
        f"**{pillar} Question:**",
        question_text,
        "",
        "**Hints:**",
    ]

    for i, hint in enumerate(hints[:MAX_HINTS_TO_DISPLAY], 1):
        lines.append(f"{i}. {hint}")

    if context_hint:
        lines.append("")
        lines.append(f"**Context:** {context_hint}")

    if example_answer:
        lines.append("")
        lines.append("**Example Answer:**")
        lines.append(example_answer)

    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Agent Class
# -----------------------------------------------------------------------------


class PromptGeneratorAgent:
    """Agent that generates smart prompts for gap questions."""

    def __init__(self, wafr_schema: Optional[Dict] = None):
        """
        Initialize Prompt Generator Agent.

        Args:
            wafr_schema: Optional WAFR schema for context.
        """
        if wafr_schema is None:
            wafr_schema = load_wafr_schema()

        self.wafr_schema = wafr_schema
        
        # Thread-local storage for agents (to support parallel processing)
        import threading
        self._thread_local = threading.local()
        
        # Store system prompt and model for thread-local agent creation
        self.system_prompt = get_prompt_generator_system_prompt(self.wafr_schema)
        try:
            self.model = get_strands_model(DEFAULT_MODEL_ID)
        except Exception as e:
            logger.warning(f"Failed to get model: {e}")
            self.model = None
        
        self.agent = self._initialize_agent()

    def _initialize_agent(self) -> Optional[Agent]:
        """
        Initialize the Strands agent with tools.

        Returns:
            Configured Agent instance or None if initialization fails.
        """
        system_prompt = get_prompt_generator_system_prompt(self.wafr_schema)

        try:
            model = get_strands_model(DEFAULT_MODEL_ID)

            agent_kwargs = {
                "system_prompt": system_prompt,
                "name": AGENT_NAME,
            }

            if model:
                agent_kwargs["model"] = model

            agent = Agent(**agent_kwargs)
            self._register_tools(agent)

            return agent

        except Exception as e:
            logger.warning(
                f"Strands Agent initialization issue: {e}, using direct Bedrock"
            )
            return None

    def _register_tools(self, agent: Agent) -> None:
        """
        Register tools with the agent.

        Args:
            agent: The Agent instance to register tools with.
        """
        try:
            # Try add_tool method first
            agent.add_tool(generate_smart_prompt)
        except AttributeError:
            try:
                # Fall back to register_tool method
                agent.register_tool(generate_smart_prompt)
            except AttributeError:
                # Tools may be auto-detected
                pass
        except Exception as e:
            logger.warning(f"Could not add tools to prompt generator agent: {e}")

    def process(self, gap: Dict, wafr_question: Dict) -> Dict[str, Any]:
        """
        Generate smart prompt for a gap.

        Args:
            gap: Gap dictionary from gap detection.
            wafr_question: Full WAFR question schema data.

        Returns:
            Generated prompt dictionary.
        """
        question_id = gap["question_id"]
        logger.info(f"PromptGeneratorAgent: Generating prompt for question {question_id}")

        # Extract components from question data
        hints = self._extract_hints(wafr_question)
        example_answer = self._extract_example_answer(wafr_question)
        quick_options = self._extract_quick_options(wafr_question)

        # Try agent-based generation first
        if self.agent:
            response = self._generate_with_agent(gap, hints)
            if self._is_valid_prompt_response(response):
                return response

        # Fallback to manual construction
        return self._generate_fallback_prompt(gap, hints, example_answer, quick_options)

    def _extract_hints(self, wafr_question: Dict) -> List[str]:
        """
        Extract hints from best practices.

        Args:
            wafr_question: WAFR question schema data.

        Returns:
            List of hint strings.
        """
        best_practices = wafr_question.get("best_practices", [])
        return [
            bp.get("text", "")
            for bp in best_practices[:MAX_HINTS_TO_DISPLAY]
        ]

    def _extract_example_answer(self, wafr_question: Dict) -> Optional[str]:
        """
        Extract example answer from best practices.

        Args:
            wafr_question: WAFR question schema data.

        Returns:
            Example answer string or None.
        """
        best_practices = wafr_question.get("best_practices", [])
        if best_practices:
            return best_practices[0].get("example_good_answer")
        return None

    def _extract_quick_options(self, wafr_question: Dict) -> List[str]:
        """
        Extract quick options from best practices.

        Args:
            wafr_question: WAFR question schema data.

        Returns:
            List of quick option strings.
        """
        best_practices = wafr_question.get("best_practices", [])
        return [
            bp.get("text", "")
            for bp in best_practices[:MAX_QUICK_OPTIONS]
            if bp.get("text")
        ]

    def _generate_with_agent(self, gap: Dict, hints: List[str]) -> Any:
        """
        Generate prompt using the Strands agent (thread-safe for parallel processing).

        Args:
            gap: Gap dictionary with question details.
            hints: List of hints from best practices.

        Returns:
            Agent response.
        """
        # Get or create thread-local agent
        if not hasattr(self._thread_local, 'agent') or self._thread_local.agent is None:
            # Create a new agent for this thread
            try:
                import threading
                agent_kwargs = {
                    "system_prompt": self.system_prompt,
                    "name": f"{AGENT_NAME}-Thread-{threading.get_ident()}",
                }
                if self.model:
                    agent_kwargs["model"] = self.model
                
                thread_agent = Agent(**agent_kwargs)
                self._register_tools(thread_agent)
                
                self._thread_local.agent = thread_agent
                logger.debug(f"Created thread-local prompt generator agent for thread {threading.get_ident()}")
                
            except Exception as e:
                logger.warning(f"Failed to create thread-local agent: {e}, using fallback")
                # Don't set thread_local.agent, let it fall through to None check below
                self._thread_local.agent = None
        
        agent_to_use = self._thread_local.agent
        
        # If thread-local agent creation failed, return None to trigger fallback
        if not agent_to_use:
            logger.warning("No agent available (thread-local creation failed), using fallback prompt generation")
            return None
        
        prompt = f"""
        Generate a smart prompt for this WAFR question gap:

        Question: {gap['question_text']}
        Pillar: {gap['pillar']}
        Criticality: {gap['criticality']}

        Best Practices Hints: {hints}
        Context: {gap.get('context_hint', 'None')}

        Use generate_smart_prompt() to create the prompt with all components.
        Make it user-friendly and actionable.
        """

        try:
            return agent_to_use(prompt)
        except Exception as e:
            # If agent call fails (e.g., concurrent invocation), return None for fallback
            logger.warning(f"Agent call failed: {e}, using fallback prompt generation")
            return None

    def _is_valid_prompt_response(self, response: Any) -> bool:
        """
        Check if agent response is a valid prompt dictionary.

        Args:
            response: Response from the agent.

        Returns:
            True if response is a valid prompt dictionary.
        """
        return isinstance(response, dict) and "question_id" in response

    def _generate_fallback_prompt(
        self,
        gap: Dict,
        hints: List[str],
        example_answer: Optional[str],
        quick_options: List[str],
    ) -> Dict[str, Any]:
        """
        Generate prompt using direct tool call (fallback method).

        Args:
            gap: Gap dictionary with question details.
            hints: List of hints from best practices.
            example_answer: Optional example answer.
            quick_options: List of quick option strings.

        Returns:
            Generated prompt dictionary.
        """
        return generate_smart_prompt(
            question_id=gap["question_id"],
            question_text=gap["question_text"],
            pillar=gap["pillar"],
            criticality=gap["criticality"],
            hints=hints,
            example_answer=example_answer,
            context_hint=gap.get("context_hint"),
            quick_options=quick_options,
        )


# -----------------------------------------------------------------------------
# Factory Function
# -----------------------------------------------------------------------------


def create_prompt_generator_agent(
    wafr_schema: Optional[Dict] = None,
) -> PromptGeneratorAgent:
    """
    Factory function to create Prompt Generator Agent.

    Args:
        wafr_schema: Optional WAFR schema for context.

    Returns:
        Configured PromptGeneratorAgent instance.
    """
    return PromptGeneratorAgent(wafr_schema)