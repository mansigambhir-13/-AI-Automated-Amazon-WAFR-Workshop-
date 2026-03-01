"""
User Context and Adaptation System

Captures user's domain, use case, and thinking style to enable agents
to adapt their reasoning and generate answers/reports from the user's perspective.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# User Context Data Structures
# =============================================================================

@dataclass
class UserContext:
    """
    Complete user context for adaptive agent behavior.
    
    Captures user's domain, use case, thinking style, and preferences
    to enable agents to think and respond from the user's perspective.
    """
    
    session_id: str
    
    # User Identity
    user_id: Optional[str] = None
    client_name: Optional[str] = None
    organization: Optional[str] = None
    
    # Domain & Industry
    industry: Optional[str] = None  # e.g., "healthcare", "finance", "retail"
    domain: Optional[str] = None  # e.g., "HIPAA-compliant healthcare", "PCI-DSS finance"
    use_case: Optional[str] = None  # e.g., "patient data management", "payment processing"
    
    # Workload Characteristics
    workload_type: Optional[str] = None  # e.g., "serverless", "containerized", "hybrid"
    workload_scale: Optional[str] = None  # e.g., "enterprise", "medium", "startup"
    compliance_requirements: List[str] = field(default_factory=list)  # e.g., ["HIPAA", "SOC2"]
    
    # Thinking Style & Preferences
    thinking_style: Optional[str] = None  # e.g., "technical", "business-focused", "practical"
    communication_style: Optional[str] = None  # e.g., "detailed", "concise", "executive"
    perspective: Optional[str] = None  # e.g., "architect", "developer", "manager", "CISO"
    
    # Domain-Specific Context
    domain_terminology: Dict[str, str] = field(default_factory=dict)  # Preferred terms
    domain_constraints: List[str] = field(default_factory=list)  # e.g., "budget-conscious", "security-first"
    business_priorities: List[str] = field(default_factory=list)  # e.g., "cost optimization", "security", "scalability"
    
    # Technical Context
    aws_services: List[str] = field(default_factory=list)  # Services they use
    technical_stack: List[str] = field(default_factory=list)  # Technologies they use
    architecture_patterns: List[str] = field(default_factory=list)  # Patterns they follow
    
    # Contextual Information
    environment: str = "PRODUCTION"  # PRODUCTION, PREPRODUCTION, DEVELOPMENT
    business_context: Dict[str, Any] = field(default_factory=dict)  # Additional business context
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "client_name": self.client_name,
            "organization": self.organization,
            "industry": self.industry,
            "domain": self.domain,
            "use_case": self.use_case,
            "workload_type": self.workload_type,
            "workload_scale": self.workload_scale,
            "compliance_requirements": self.compliance_requirements,
            "thinking_style": self.thinking_style,
            "communication_style": self.communication_style,
            "perspective": self.perspective,
            "domain_terminology": self.domain_terminology,
            "domain_constraints": self.domain_constraints,
            "business_priorities": self.business_priorities,
            "aws_services": self.aws_services,
            "technical_stack": self.technical_stack,
            "architecture_patterns": self.architecture_patterns,
            "environment": self.environment,
            "business_context": self.business_context,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserContext":
        """Create from dictionary."""
        return cls(
            session_id=data["session_id"],
            user_id=data.get("user_id"),
            client_name=data.get("client_name"),
            organization=data.get("organization"),
            industry=data.get("industry"),
            domain=data.get("domain"),
            use_case=data.get("use_case"),
            workload_type=data.get("workload_type"),
            workload_scale=data.get("workload_scale"),
            compliance_requirements=data.get("compliance_requirements", []),
            thinking_style=data.get("thinking_style"),
            communication_style=data.get("communication_style"),
            perspective=data.get("perspective"),
            domain_terminology=data.get("domain_terminology", {}),
            domain_constraints=data.get("domain_constraints", []),
            business_priorities=data.get("business_priorities", []),
            aws_services=data.get("aws_services", []),
            technical_stack=data.get("technical_stack", []),
            architecture_patterns=data.get("architecture_patterns", []),
            environment=data.get("environment", "PRODUCTION"),
            business_context=data.get("business_context", {}),
        )
    
    def get_adaptation_prompt(self) -> str:
        """
        Generate adaptation prompt for agents.
        
        Returns:
            Prompt section that instructs agents to think from user's perspective
        """
        parts = []
        
        # User perspective
        if self.perspective:
            parts.append(f"**User Perspective**: Think from the perspective of a {self.perspective}.")
        
        # Domain context
        if self.domain or self.industry:
            domain_desc = f"{self.domain} " if self.domain else ""
            industry_desc = f"in the {self.industry} industry" if self.industry else ""
            if domain_desc or industry_desc:
                parts.append(f"**Domain Context**: You are working with a {domain_desc}{industry_desc}.")
        
        # Use case
        if self.use_case:
            parts.append(f"**Use Case**: The user's specific use case is: {self.use_case}.")
        
        # Thinking style
        if self.thinking_style:
            style_guidance = {
                "technical": "Focus on technical details, implementation specifics, and architectural patterns.",
                "business-focused": "Focus on business value, ROI, and strategic implications.",
                "practical": "Focus on actionable, practical solutions that can be implemented quickly.",
            }
            guidance = style_guidance.get(self.thinking_style, "")
            if guidance:
                parts.append(f"**Thinking Style**: {guidance}")
        
        # Communication style
        if self.communication_style:
            comm_guidance = {
                "detailed": "Provide comprehensive, detailed explanations with examples.",
                "concise": "Be concise and to the point, focusing on key information.",
                "executive": "Provide high-level summaries with business impact focus.",
            }
            guidance = comm_guidance.get(self.communication_style, "")
            if guidance:
                parts.append(f"**Communication Style**: {guidance}")
        
        # Compliance requirements
        if self.compliance_requirements:
            parts.append(
                f"**Compliance Requirements**: The user must comply with: {', '.join(self.compliance_requirements)}. "
                f"Ensure all recommendations align with these requirements."
            )
        
        # Business priorities
        if self.business_priorities:
            parts.append(
                f"**Business Priorities**: Prioritize {', '.join(self.business_priorities)} in your recommendations."
            )
        
        # Domain constraints
        if self.domain_constraints:
            parts.append(
                f"**Constraints**: Consider these constraints: {', '.join(self.domain_constraints)}."
            )
        
        # Terminology preferences
        if self.domain_terminology:
            term_list = [f'use "{pref}" instead of "{term}"' for term, pref in list(self.domain_terminology.items())[:5]]
            if term_list:
                parts.append(f"**Terminology**: {', '.join(term_list)}.")
        
        if not parts:
            return ""
        
        return "\n\n".join(parts)


# =============================================================================
# User Context Manager
# =============================================================================

class UserContextManager:
    """
    Manages user context per session.
    
    Captures and provides user context for adaptive agent behavior.
    """
    
    def __init__(self):
        """Initialize user context manager."""
        self.contexts: Dict[str, UserContext] = {}
        logger.info("UserContextManager initialized")
    
    def get_context(self, session_id: str) -> UserContext:
        """
        Get or create user context for session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            UserContext instance
        """
        if session_id not in self.contexts:
            self.contexts[session_id] = UserContext(session_id=session_id)
            logger.debug(f"Created user context for session {session_id}")
        
        return self.contexts[session_id]
    
    def set_context(
        self,
        session_id: str,
        **kwargs,
    ) -> UserContext:
        """
        Set user context for session.
        
        Args:
            session_id: Session identifier
            **kwargs: User context fields
            
        Returns:
            Updated UserContext instance
        """
        context = self.get_context(session_id)
        
        # Update fields
        for key, value in kwargs.items():
            if hasattr(context, key) and value is not None:
                if isinstance(value, list) and isinstance(getattr(context, key), list):
                    # Merge lists
                    existing = getattr(context, key)
                    existing.extend([v for v in value if v not in existing])
                elif isinstance(value, dict) and isinstance(getattr(context, key), dict):
                    # Merge dicts
                    getattr(context, key).update(value)
                else:
                    setattr(context, key, value)
        
        logger.info(f"Updated user context for session {session_id}")
        return context
    
    def infer_from_transcript(
        self,
        session_id: str,
        transcript: str,
        insights: Optional[List[Dict[str, Any]]] = None,
    ) -> UserContext:
        """
        Infer user context from transcript and insights.
        
        Args:
            session_id: Session identifier
            transcript: Workshop transcript
            insights: Optional extracted insights
            
        Returns:
            UserContext with inferred information
        """
        context = self.get_context(session_id)
        
        # Infer from transcript (basic keyword matching)
        transcript_lower = transcript.lower()
        
        # Industry inference
        industry_keywords = {
            "healthcare": ["health", "patient", "hipaa", "medical", "hospital"],
            "finance": ["financial", "payment", "pci", "bank", "transaction"],
            "retail": ["retail", "ecommerce", "customer", "inventory"],
            "education": ["student", "education", "school", "university"],
        }
        
        for industry, keywords in industry_keywords.items():
            if any(keyword in transcript_lower for keyword in keywords):
                context.industry = industry
                break
        
        # Compliance inference
        if "hipaa" in transcript_lower:
            context.compliance_requirements.append("HIPAA")
        if "pci" in transcript_lower or "pci-dss" in transcript_lower:
            context.compliance_requirements.append("PCI-DSS")
        if "soc2" in transcript_lower or "soc 2" in transcript_lower:
            context.compliance_requirements.append("SOC2")
        if "gdpr" in transcript_lower:
            context.compliance_requirements.append("GDPR")
        
        # AWS services inference
        aws_services = [
            "lambda", "ec2", "s3", "rds", "dynamodb", "cloudfront",
            "api gateway", "ecs", "eks", "sns", "sqs", "cloudwatch",
        ]
        for service in aws_services:
            if service in transcript_lower:
                if service not in context.aws_services:
                    context.aws_services.append(service)
        
        logger.info(f"Inferred user context for session {session_id}")
        return context
    
    def get_adaptation_guidance(self, session_id: str) -> Dict[str, Any]:
        """
        Get adaptation guidance for agents.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Guidance dictionary
        """
        context = self.get_context(session_id)
        
        return {
            "user_context": context.to_dict(),
            "adaptation_prompt": context.get_adaptation_prompt(),
            "domain_context": {
                "industry": context.industry,
                "domain": context.domain,
                "use_case": context.use_case,
                "compliance_requirements": context.compliance_requirements,
            },
            "thinking_style": {
                "style": context.thinking_style,
                "communication": context.communication_style,
                "perspective": context.perspective,
            },
            "preferences": {
                "terminology": context.domain_terminology,
                "constraints": context.domain_constraints,
                "priorities": context.business_priorities,
            },
        }
    
    def clear_session(self, session_id: str) -> None:
        """Clear user context for session."""
        if session_id in self.contexts:
            del self.contexts[session_id]
            logger.info(f"Cleared user context for session {session_id}")


# Global user context manager instance
_user_context_manager = UserContextManager()


def get_user_context_manager() -> UserContextManager:
    """Get global user context manager instance."""
    return _user_context_manager
