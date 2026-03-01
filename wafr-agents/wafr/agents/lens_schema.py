"""
Lens Schema Registry - Provides structured schema data for each lens.

Pre-defined schema structures for major AWS Well-Architected lenses.
These serve as fallback when the AWS API is unavailable.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# Generative AI Lens Schema
# =============================================================================

GENERATIVE_AI_LENS_SCHEMA: dict[str, Any] = {
    "lens_alias": "generative-ai",
    "lens_name": "Generative AI Lens",
    "version": "2.0",
    "description": "Best practices for building generative AI workloads on AWS",
    "lifecycle_phases": [
        "Scoping",
        "Model Selection",
        "Customization",
        "Integration",
        "Deployment",
        "Continuous Improvement",
    ],
    "pillars": {
        "operationalExcellence": {
            "name": "Operational Excellence",
            "focus_areas": [
                "Model output quality consistency",
                "Operational health monitoring",
                "Traceability and auditability",
                "Lifecycle automation",
                "Model customization decisions",
            ],
            "key_questions": [
                "How do you achieve consistent model output quality?",
                "How do you monitor and manage operational health?",
                "How do you maintain traceability of model decisions?",
                "How do you automate lifecycle management?",
                "When do you execute model customization?",
            ],
        },
        "security": {
            "name": "Security",
            "focus_areas": [
                "Endpoint protection",
                "Harmful output mitigation",
                "Excessive agency prevention",
                "Event monitoring and auditing",
                "Prompt security",
                "Model poisoning remediation",
            ],
            "key_questions": [
                "How do you protect generative AI endpoints?",
                "How do you mitigate risks of harmful outputs?",
                "How do you prevent excessive AI agency?",
                "How do you monitor and audit events?",
                "How do you secure prompts?",
                "How do you remediate model poisoning risks?",
            ],
        },
        "reliability": {
            "name": "Reliability",
            "focus_areas": [
                "Throughput management",
                "Component communication reliability",
                "Observability implementation",
                "Graceful failure handling",
                "Artifact versioning",
                "Distributed inference",
                "Computation verification",
            ],
            "key_questions": [
                "How do you handle throughput requirements?",
                "How do you maintain reliable component communication?",
                "How do you implement observability?",
                "How do you handle failures gracefully?",
                "How do you version artifacts?",
                "How do you distribute inference?",
                "How do you verify computation completion?",
            ],
        },
        "performanceEfficiency": {
            "name": "Performance Efficiency",
            "focus_areas": [
                "Model selection optimization",
                "Inference latency management",
                "Token optimization",
                "Caching strategies",
                "Batch processing",
            ],
            "key_questions": [
                "How do you select the right model for your use case?",
                "How do you manage inference latency?",
                "How do you optimize token usage?",
                "How do you implement caching strategies?",
                "How do you handle batch processing?",
            ],
        },
        "costOptimization": {
            "name": "Cost Optimization",
            "focus_areas": [
                "Model cost analysis",
                "Right-sizing inference resources",
                "Provisioned throughput optimization",
                "Cost monitoring and allocation",
            ],
            "key_questions": [
                "How do you analyze model costs?",
                "How do you right-size inference resources?",
                "How do you optimize provisioned throughput?",
                "How do you monitor and allocate costs?",
            ],
        },
        "sustainability": {
            "name": "Sustainability",
            "focus_areas": [
                "Training resource minimization",
                "Hosting efficiency",
                "Data processing optimization",
                "Model efficiency techniques",
                "Serverless architecture leverage",
            ],
            "key_questions": [
                "How do you minimize computational resources for training?",
                "How do you optimize hosting efficiency?",
                "How do you reduce data processing overhead?",
                "What model efficiency techniques do you use?",
                "How do you leverage serverless architectures?",
            ],
        },
    },
    "scenarios": [
        "Autonomous Call Centers",
        "Knowledge Worker Co-pilots",
        "Multi-tenant GenAI Platforms",
        "Generative Business Intelligence",
        "RAG-based Applications",
        "Agentic AI Systems",
        "Content Generation Pipelines",
        "Conversational AI Assistants",
    ],
    "agentic_patterns": [
        "ReACT (Reason and Act) loops",
        "Tool-augmented LLMs",
        "Memory-enhanced agents",
        "MCP protocol integrations",
        "Multi-agent orchestration",
    ],
}


# =============================================================================
# Machine Learning Lens Schema
# =============================================================================

MACHINE_LEARNING_LENS_SCHEMA: dict[str, Any] = {
    "lens_alias": "machine-learning",
    "lens_name": "Machine Learning Lens",
    "version": "2.0",
    "description": "Best practices for building machine learning workloads on AWS",
    "lifecycle_phases": [
        "Business Goal Identification",
        "ML Problem Framing",
        "Data Processing",
        "Model Development",
        "Model Training and Tuning",
        "Model Deployment",
        "Model Monitoring",
    ],
    "pillars": {
        "operationalExcellence": {
            "name": "Operational Excellence",
            "focus_areas": [
                "ML pipeline automation",
                "Model versioning",
                "Experiment tracking",
                "Feature store management",
                "MLOps practices",
            ],
            "key_questions": [
                "How do you automate ML pipelines?",
                "How do you version models and artifacts?",
                "How do you track experiments?",
                "How do you manage feature stores?",
                "What MLOps practices do you follow?",
            ],
        },
        "security": {
            "name": "Security",
            "focus_areas": [
                "Data privacy",
                "Model access control",
                "Adversarial attack protection",
                "Secure training environments",
            ],
            "key_questions": [
                "How do you protect data privacy?",
                "How do you control model access?",
                "How do you protect against adversarial attacks?",
                "How do you secure training environments?",
            ],
        },
        "reliability": {
            "name": "Reliability",
            "focus_areas": [
                "Model drift detection",
                "Data quality monitoring",
                "Fallback strategies",
                "A/B testing frameworks",
            ],
            "key_questions": [
                "How do you detect model drift?",
                "How do you monitor data quality?",
                "What fallback strategies do you use?",
                "How do you implement A/B testing?",
            ],
        },
        "performanceEfficiency": {
            "name": "Performance Efficiency",
            "focus_areas": [
                "Training optimization",
                "Inference optimization",
                "Hardware selection",
                "Distributed training",
            ],
            "key_questions": [
                "How do you optimize training?",
                "How do you optimize inference?",
                "How do you select hardware?",
                "How do you implement distributed training?",
            ],
        },
        "costOptimization": {
            "name": "Cost Optimization",
            "focus_areas": [
                "Training cost management",
                "Inference cost optimization",
                "Spot instance usage",
                "Resource right-sizing",
            ],
            "key_questions": [
                "How do you manage training costs?",
                "How do you optimize inference costs?",
                "How do you use spot instances?",
                "How do you right-size resources?",
            ],
        },
        "sustainability": {
            "name": "Sustainability",
            "focus_areas": [
                "Efficient model architectures",
                "Green ML practices",
                "Carbon footprint tracking",
            ],
            "key_questions": [
                "What efficient model architectures do you use?",
                "What green ML practices do you follow?",
                "How do you track carbon footprint?",
            ],
        },
    },
}


# =============================================================================
# Serverless Lens Schema
# =============================================================================

SERVERLESS_LENS_SCHEMA: dict[str, Any] = {
    "lens_alias": "serverless",
    "lens_name": "Serverless Applications Lens",
    "version": "1.0",
    "description": "Best practices for building serverless applications on AWS",
    "pillars": {
        "operationalExcellence": {
            "name": "Operational Excellence",
            "focus_areas": [
                "Deployment strategies",
                "Observability",
                "Error handling",
                "Configuration management",
            ],
            "key_questions": [
                "How do you deploy serverless applications?",
                "How do you implement observability?",
                "How do you handle errors?",
                "How do you manage configuration?",
            ],
        },
        "security": {
            "name": "Security",
            "focus_areas": [
                "Function security",
                "API security",
                "Data protection",
                "Dependency management",
            ],
            "key_questions": [
                "How do you secure Lambda functions?",
                "How do you secure APIs?",
                "How do you protect data?",
                "How do you manage dependencies?",
            ],
        },
        "reliability": {
            "name": "Reliability",
            "focus_areas": [
                "Async invocation handling",
                "Retry strategies",
                "Dead letter queues",
                "Idempotency",
            ],
            "key_questions": [
                "How do you handle async invocations?",
                "What retry strategies do you use?",
                "How do you use dead letter queues?",
                "How do you ensure idempotency?",
            ],
        },
        "performanceEfficiency": {
            "name": "Performance Efficiency",
            "focus_areas": [
                "Cold start optimization",
                "Memory tuning",
                "Provisioned concurrency",
                "Architecture patterns",
            ],
            "key_questions": [
                "How do you optimize cold starts?",
                "How do you tune memory?",
                "How do you use provisioned concurrency?",
                "What architecture patterns do you use?",
            ],
        },
        "costOptimization": {
            "name": "Cost Optimization",
            "focus_areas": [
                "Right-sizing functions",
                "Execution time optimization",
                "Concurrency management",
            ],
            "key_questions": [
                "How do you right-size functions?",
                "How do you optimize execution time?",
                "How do you manage concurrency?",
            ],
        },
        "sustainability": {
            "name": "Sustainability",
            "focus_areas": [
                "Efficient runtimes",
                "Arm64 adoption",
                "Batch processing",
            ],
            "key_questions": [
                "What efficient runtimes do you use?",
                "Do you use Arm64 processors?",
                "How do you handle batch processing?",
            ],
        },
    },
}


# =============================================================================
# SaaS Lens Schema
# =============================================================================

SAAS_LENS_SCHEMA: dict[str, Any] = {
    "lens_alias": "saas",
    "lens_name": "SaaS Lens",
    "version": "1.0",
    "description": "Best practices for building multi-tenant SaaS applications on AWS",
    "pillars": {
        "operationalExcellence": {
            "name": "Operational Excellence",
            "focus_areas": [
                "Tenant onboarding automation",
                "Multi-tenant monitoring",
                "Deployment strategies",
            ],
            "key_questions": [
                "How do you automate tenant onboarding?",
                "How do you monitor multi-tenant systems?",
                "What deployment strategies do you use?",
            ],
        },
        "security": {
            "name": "Security",
            "focus_areas": [
                "Tenant isolation",
                "Identity management",
                "Data segregation",
            ],
            "key_questions": [
                "How do you isolate tenants?",
                "How do you manage identities?",
                "How do you segregate data?",
            ],
        },
        "reliability": {
            "name": "Reliability",
            "focus_areas": [
                "Noisy neighbor prevention",
                "Tenant-aware scaling",
                "Fault isolation",
            ],
            "key_questions": [
                "How do you prevent noisy neighbors?",
                "How do you scale per tenant?",
                "How do you isolate faults?",
            ],
        },
        "performanceEfficiency": {
            "name": "Performance Efficiency",
            "focus_areas": [
                "Tenant tiering",
                "Resource pooling",
                "Caching strategies",
            ],
            "key_questions": [
                "How do you implement tenant tiering?",
                "How do you pool resources?",
                "What caching strategies do you use?",
            ],
        },
        "costOptimization": {
            "name": "Cost Optimization",
            "focus_areas": [
                "Cost attribution",
                "Consumption metering",
                "Resource optimization",
            ],
            "key_questions": [
                "How do you attribute costs?",
                "How do you meter consumption?",
                "How do you optimize resources?",
            ],
        },
        "sustainability": {
            "name": "Sustainability",
            "focus_areas": [
                "Resource sharing",
                "Efficient multi-tenancy",
            ],
            "key_questions": [
                "How do you share resources efficiently?",
                "What multi-tenancy patterns do you use?",
            ],
        },
    },
}


# =============================================================================
# Schema Registry
# =============================================================================

LENS_SCHEMA_REGISTRY: dict[str, dict[str, Any]] = {
    "generative-ai": GENERATIVE_AI_LENS_SCHEMA,
    "machine-learning": MACHINE_LEARNING_LENS_SCHEMA,
    "serverless": SERVERLESS_LENS_SCHEMA,
    "saas": SAAS_LENS_SCHEMA,
}


# =============================================================================
# Public Functions
# =============================================================================

def get_lens_schema(lens_alias: str) -> dict[str, Any] | None:
    """
    Get predefined schema for a lens.
    
    Args:
        lens_alias: The lens alias to look up
        
    Returns:
        Lens schema dictionary or None if not found
    """
    return LENS_SCHEMA_REGISTRY.get(lens_alias)


def get_all_lens_schemas() -> dict[str, dict[str, Any]]:
    """
    Get all predefined lens schemas.
    
    Returns:
        Copy of the complete lens schema registry
    """
    return LENS_SCHEMA_REGISTRY.copy()


def get_lens_focus_areas(lens_alias: str, pillar_id: str) -> list[str]:
    """
    Get focus areas for a specific pillar in a lens.
    
    Args:
        lens_alias: The lens alias to look up
        pillar_id: The pillar ID within the lens
        
    Returns:
        List of focus areas for the pillar (empty if not found)
    """
    schema = LENS_SCHEMA_REGISTRY.get(lens_alias, {})
    pillar = schema.get("pillars", {}).get(pillar_id, {})
    return pillar.get("focus_areas", [])