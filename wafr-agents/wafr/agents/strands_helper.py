"""
Helper for Strands Agent compatibility
"""
import logging
from typing import Any, Callable, List, Optional

logger = logging.getLogger(__name__)


def safe_create_agent(
    system_prompt: str, 
    name: str, 
    tools: Optional[List[Callable[..., Any]]] = None
) -> Any:
    """
    Safely create a Strands agent with fallback handling.
    
    Args:
        system_prompt: System prompt for the agent
        name: Agent name
        tools: List of tool functions (optional)
        
    Returns:
        Agent instance or None if creation fails
    """
    try:
        from strands import Agent
        
        agent = Agent(
            system_prompt=system_prompt,
            name=name
        )
        
        # Try to add tools if method exists and tools provided
        if tools and hasattr(agent, 'add_tool'):
            for tool in tools:
                try:
                    agent.add_tool(tool)
                except Exception as e:
                    logger.warning(f"Could not add tool {tool.__name__}: {e}")
        
        return agent
        
    except Exception as e:
        logger.warning(f"Could not create Strands agent {name}: {e}")
        return None

