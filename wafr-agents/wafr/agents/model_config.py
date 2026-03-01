"""
Model configuration for Strands agents
"""
import logging
from typing import Optional, Any

from wafr.agents.config import DEFAULT_MODEL_ID, BEDROCK_REGION

logger = logging.getLogger(__name__)


def get_strands_model(model_id: Optional[str] = None, max_tokens: Optional[int] = None) -> Any:
    """
    Get configured model for Strands Agent.
    
    Note: Claude 3.7 Sonnet works directly with ConverseStream API.
    If Strands fails, agents will fall back to direct Bedrock invoke_model API.
    
    Args:
        model_id: Optional model ID (defaults to Claude 3.7 Sonnet)
        max_tokens: Optional max tokens for the model (defaults to 8192 for complex tasks)
        
    Returns:
        Model instance for Strands Agent, or None to use fallback
    """
    if model_id is None:
        model_id = DEFAULT_MODEL_ID
    
    if max_tokens is None:
        max_tokens = 8192  # Increased default for complex validation tasks
    
    try:
        # Try to import and create BedrockModel from Strands
        from strands.models.bedrock import BedrockModel
        
        # Try to pass max_tokens if supported
        try:
            model = BedrockModel(
                model_id=model_id,
                max_tokens=max_tokens
            )
        except TypeError:
            # If max_tokens not supported in constructor, create without it
            model = BedrockModel(model_id=model_id)
        
        return model
    except ImportError:
        # If BedrockModel not available, try alternative import
        try:
            from strands.models import BedrockModel
            try:
                model = BedrockModel(
                    model_id=model_id,
                    max_tokens=max_tokens
                )
            except TypeError:
                model = BedrockModel(model_id=model_id)
            return model
        except (ImportError, Exception) as e:
            # Fallback: return None and let Strands use default
            # Strands might auto-detect or use environment variables
            # If Strands fails, agents will use direct Bedrock invoke_model API
            logger.warning(f"Could not create BedrockModel explicitly: {e}. Will use direct Bedrock API fallback.")
            return None

