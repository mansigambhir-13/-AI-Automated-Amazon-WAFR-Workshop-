"""
Base Agent Class - Common functionality for all WAFR agents.

Provides abstract base for agents interacting with AWS Bedrock Claude models.
"""

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

# =============================================================================
# Configuration
# =============================================================================

DEFAULT_MODEL_ID = "anthropic.claude-3-sonnet-20240229-v1:0"
DEFAULT_REGION = "us-east-1"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.1

# Precompiled patterns for JSON extraction (better performance)
_JSON_CODE_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

logger = logging.getLogger(__name__)


# =============================================================================
# Exceptions
# =============================================================================

class AgentError(Exception):
    """Base exception for agent operations."""


class ModelInvocationError(AgentError):
    """Raised when Bedrock model invocation fails."""


# =============================================================================
# Base Agent
# =============================================================================

class BaseAgent(ABC):
    """
    Abstract base class for all WAFR agents.
    
    Example:
        class MyAgent(BaseAgent):
            def process(self, input_data: dict[str, Any]) -> dict[str, Any]:
                return self.invoke_model("Analyze this", system_prompt="Be helpful")
    """

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        region_name: str = DEFAULT_REGION,
    ):
        """
        Initialize agent with Bedrock configuration.
        
        Args:
            model_id: Bedrock model identifier
            region_name: AWS region for Bedrock client
        """
        self.model_id = model_id
        self.region_name = region_name
        self._client: Any = None  # Lazy initialization

    @property
    def bedrock(self) -> Any:
        """Lazily initialize Bedrock client on first use."""
        if self._client is None:
            self._client = boto3.client("bedrock-runtime", region_name=self.region_name)
        return self._client
    
    def _validate_credentials_before_call(self) -> None:
        """Validate AWS credentials before making Bedrock calls."""
        from wafr.agents.utils import validate_aws_credentials
        is_valid, error_msg = validate_aws_credentials()
        if not is_valid:
            raise ModelInvocationError(
                f"AWS credentials validation failed:\n{error_msg}\n\n"
                "Please configure valid AWS credentials before using Bedrock."
            )

    def invoke_model(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Invoke Bedrock Claude model.
        
        Args:
            prompt: User message
            system_prompt: System instructions (optional)
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0.0-1.0)
            **kwargs: Additional model parameters
            
        Returns:
            Parsed JSON response or {"raw_text": response_text}
            
        Raises:
            ModelInvocationError: If API call fails
        """
        # Build request body
        # NOTE: Claude API expects 'system' as top-level param, NOT in messages
        body: dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
            **kwargs,
        }
        
        if system_prompt:
            body["system"] = system_prompt

        # Invoke model
        try:
            response = self.bedrock.invoke_model(
                modelId=self.model_id,
                body=json.dumps(body),
            )
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            
            # Handle Anthropic use case details error
            if error_code == 'ResourceNotFoundException' and 'use case details' in error_msg.lower():
                logger.error("Anthropic use case details not submitted: %s", error_msg)
                raise ModelInvocationError(
                    "⚠️  Anthropic Use Case Details Required\n\n"
                    "To use Claude models in AWS Bedrock, you must:\n"
                    "1. Go to AWS Bedrock Console: https://console.aws.amazon.com/bedrock/home?region=us-east-1\n"
                    "2. Navigate to 'Model access'\n"
                    "3. Request access to Anthropic Claude models\n"
                    "4. Fill out the use case details form\n"
                    "5. Wait for approval (usually instant, up to 15 minutes)\n\n"
                    "Alternatively, use a legacy model by setting:\n"
                    "BEDROCK_MODEL_ID=anthropic.claude-3-sonnet-20240229-v1:0\n\n"
                    f"Original error: {error_msg}"
                ) from e
            
            # Handle credential-related errors with helpful messages
            if error_code in ['UnrecognizedClientException', 'InvalidClientTokenId', 'InvalidUserID.NotFound']:
                logger.error("Bedrock invocation failed due to invalid credentials: %s", error_msg)
                from wafr.agents.utils import validate_aws_credentials
                _, cred_error_msg = validate_aws_credentials()
                raise ModelInvocationError(
                    f"Bedrock call failed: {error_msg}\n\n"
                    f"{cred_error_msg}\n\n"
                    "Please configure valid AWS credentials before using Bedrock."
                ) from e
            elif error_code == 'ExpiredToken':
                logger.error("Bedrock invocation failed due to expired token: %s", error_msg)
                raise ModelInvocationError(
                    f"Bedrock call failed: {error_msg}\n\n"
                    "Your AWS session token has expired. Please refresh your credentials:\n"
                    "- If using SSO: Run 'aws sso login'\n"
                    "- If using temporary credentials: Refresh your session token\n"
                    "- If using permanent credentials: Run 'aws configure'"
                ) from e
            else:
                logger.error("Bedrock invocation failed: %s - %s", error_code, error_msg)
                raise ModelInvocationError(f"Model invocation failed: {error_code} - {error_msg}") from e
        except BotoCoreError as e:
            logger.error("Bedrock invocation failed: %s", e)
            raise ModelInvocationError(f"Model invocation failed: {e}") from e

        # Parse response
        result = json.loads(response["body"].read())
        content = result.get("content", [])

        if not content:
            return {"error": "No content in response"}

        text = content[0].get("text", "")
        
        # Try to parse as JSON, fallback to raw text
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw_text": text}

    def extract_json_from_text(self, text: str) -> dict[str, Any]:
        """
        Extract JSON from markdown code blocks or plain text.
        
        Tries multiple strategies:
        1. JSON in ```json ``` code blocks
        2. Raw JSON object in text
        3. Returns {"raw_text": text} if no JSON found
        
        Args:
            text: Text potentially containing JSON
            
        Returns:
            Parsed JSON dict or {"raw_text": text}
        """
        # Strategy 1: Code block
        if match := _JSON_CODE_BLOCK.search(text):
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # Strategy 2: Raw JSON object
        if match := _JSON_OBJECT.search(text):
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        return {"raw_text": text}

    @abstractmethod
    def process(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """
        Process input data and return results.
        
        Args:
            input_data: Agent-specific input data
            
        Returns:
            Processing results dictionary
        """

    def log_processing(
        self,
        session_id: str,
        agent_name: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Log agent processing activity.
        
        Args:
            session_id: Unique session identifier
            agent_name: Name of the processing agent
            metadata: Additional context to log
        """
        logger.info(
            "Agent: %s | Session: %s | Metadata: %s",
            agent_name,
            session_id,
            metadata or {},
        )