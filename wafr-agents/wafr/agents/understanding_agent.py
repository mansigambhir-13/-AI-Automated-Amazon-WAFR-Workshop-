"""
Understanding Agent - Extracts architecture insights from transcripts
Uses Strands framework for agent orchestration
"""
from strands import Agent, tool
from typing import Dict, List, Any, Optional
import json
import logging
import boto3
from botocore.exceptions import ClientError

from wafr.agents.utils import (
    retry_with_backoff,
    extract_json_from_text,
    validate_insight,
    deduplicate_insights,
    smart_segment_transcript,
    batch_process
)
from wafr.agents.wafr_context import load_wafr_schema, get_wafr_context_summary
from wafr.agents.config import DEFAULT_MODEL_ID, ModelSelectionStrategy
from wafr.agents.model_config import get_strands_model

logger = logging.getLogger(__name__)


def get_understanding_system_prompt(wafr_schema: Optional[Dict] = None, lens_context: Optional[Dict] = None) -> str:
    """Generate enhanced system prompt with WAFR context and lens-specific guidance."""
    base_prompt = """
You are an expert AWS Solutions Architect analyzing Well-Architected Framework Review (WAFR) workshop transcripts and PDF documentation to extract architecture-relevant information.

Your input may include:
- Workshop transcript (conversational content from meetings)
- PDF documentation (structured content from documents, diagrams, workflows)

Your task is to extract from ALL sources:
1. Architecture decisions discussed (what was decided, why)
2. AWS services mentioned (with context on how they're used)
3. Constraints and requirements stated (performance, cost, compliance, security)
4. Risks or concerns raised (security, availability, scalability, reliability)
5. Best practices mentioned or implemented
6. Gaps or missing capabilities identified
7. Architecture components from diagrams (if PDF contains diagrams)
8. Workflow steps and processes (if PDF contains workflows)

CRITICAL RULES:
- Every insight MUST include verbatim transcript quote
- Include speaker attribution when available
- Include approximate timestamp or position in transcript
- Do NOT infer or assume - only extract what is explicitly stated
- Be precise and factual - no hallucinations
- Focus on information relevant to AWS Well-Architected Framework pillars:
  * Operational Excellence (monitoring, automation, processes)
  * Security (identity, permissions, encryption, compliance)
  * Reliability (fault tolerance, disaster recovery, scaling)
  * Performance Efficiency (resource selection, optimization)
  * Cost Optimization (spending management, right-sizing)
  * Sustainability (resource efficiency, carbon footprint)

INSIGHT TYPES:
- "decision": Architecture choices, technology selections, design patterns
- "service": AWS services mentioned (EC2, S3, RDS, Lambda, etc.) with usage context
- "constraint": Requirements, limitations, compliance needs, SLAs
- "risk": Security concerns, availability risks, scalability issues, cost concerns
- "lens_specific": Insights specific to specialized lenses (Generative AI, ML, Serverless, etc.)

OUTPUT FORMAT:
Return insights as a JSON array. Each insight must have:
- insight_type: one of ['decision', 'service', 'constraint', 'risk', 'lens_specific']
- content: clear, concise summary (1-2 sentences)
- transcript_quote: EXACT verbatim quote from transcript
- speaker: speaker name if identifiable
- timestamp: approximate position or time reference
- lens_relevance: (optional) List of relevant lens aliases if this insight is lens-specific
"""
    
    # Add lens-specific guidance
    lens_guidance = ""
    if lens_context and lens_context.get("lenses"):
        active_lenses = list(lens_context["lenses"].keys())
        lens_guidance = "\n\nLENS-SPECIFIC EXTRACTION GUIDANCE:\n"
        lens_guidance += "The following specialized lenses are active. Pay special attention to insights relevant to these lenses:\n\n"
        
        for alias in active_lenses:
            lens_info = lens_context["lenses"][alias]
            lens_name = lens_info.get("name", alias)
            
            if alias == "generative-ai":
                lens_guidance += f"- {lens_name}: Focus on LLMs, foundation models, RAG architectures, vector databases, "
                lens_guidance += "prompt engineering, agentic AI patterns, Bedrock, Claude, GPT, embeddings, tool use, "
                lens_guidance += "responsible AI considerations, model selection, inference optimization.\n"
            elif alias == "machine-learning":
                lens_guidance += f"- {lens_name}: Focus on ML pipelines, model training, inference, MLOps, feature stores, "
                lens_guidance += "experiment tracking, model versioning, SageMaker, data processing, model deployment.\n"
            elif alias == "serverless":
                lens_guidance += f"- {lens_name}: Focus on Lambda functions, API Gateway, Step Functions, EventBridge, "
                lens_guidance += "serverless patterns, cold starts, event-driven architecture, stateless design.\n"
            elif alias == "saas":
                lens_guidance += f"- {lens_name}: Focus on multi-tenancy, tenant isolation, tenant onboarding, "
                lens_guidance += "tenant tiering, cost attribution per tenant, resource pooling.\n"
            elif alias == "data-analytics":
                lens_guidance += f"- {lens_name}: Focus on data lakes, data warehouses, ETL/ELT, analytics pipelines, "
                lens_guidance += "Redshift, Athena, Glue, data processing, BI tools.\n"
            elif alias == "containers":
                lens_guidance += f"- {lens_name}: Focus on containers, Docker, Kubernetes, EKS, ECS, Fargate, "
                lens_guidance += "container orchestration, service mesh.\n"
            elif alias == "responsible-ai":
                lens_guidance += f"- {lens_name}: Focus on AI ethics, bias, fairness, transparency, explainability, "
                lens_guidance += "harmful content mitigation, content moderation, AI governance.\n"
            else:
                lens_guidance += f"- {lens_name}: Extract insights relevant to this specialized lens.\n"
        
        lens_guidance += "\nWhen you identify insights that are specific to these lenses, mark them with 'lens_specific' type "
        lens_guidance += "and include the relevant lens alias in 'lens_relevance' field.\n"
    
    if wafr_schema:
        wafr_context = get_wafr_context_summary(wafr_schema)
        return f"{base_prompt}\n\n{wafr_context}{lens_guidance}\n\nUse this WAFR context to better understand what architecture information is relevant."
    
    return base_prompt + lens_guidance


@tool
def extract_insights(
    transcript: str,
    insight_type: str,
    content: str,
    transcript_quote: str,
    speaker: str = None,
    timestamp: str = None
) -> Dict:
    """
    Extract structured insights from transcript segment.
    
    Args:
        transcript: Full transcript text
        insight_type: Type of insight (decision/service/constraint/risk)
        content: Summary of the insight
        transcript_quote: Exact quote from transcript
        speaker: Speaker name if identifiable
        timestamp: Timestamp or position in transcript
        
    Returns:
        Structured insight dictionary
    """
    return {
        "insight_type": insight_type,
        "content": content,
        "transcript_quote": transcript_quote,
        "speaker": speaker,
        "timestamp": timestamp,
        "confidence": 1.0  # Direct quote = high confidence
    }


@tool
def segment_transcript(transcript: str, max_segment_length: int = 5000) -> List[str]:
    """
    Split transcript into processable segments.
    
    Args:
        transcript: Full transcript text
        max_segment_length: Maximum characters per segment
        
    Returns:
        List of transcript segments
    """
    segments_data = smart_segment_transcript(transcript, max_segment_length)
    return [seg['text'] for seg in segments_data]


class UnderstandingAgent:
    """Agent that extracts architecture insights from transcripts."""
    
    def __init__(self, wafr_schema: Optional[Dict] = None, lens_context: Optional[Dict] = None):
        """
        Initialize Understanding Agent with Strands.
        
        Args:
            wafr_schema: Optional WAFR schema for context
            lens_context: Optional lens context for multi-lens support
        """
        # Load WAFR schema if not provided
        if wafr_schema is None:
            wafr_schema = load_wafr_schema()
        
        self.wafr_schema = wafr_schema
        self.lens_context = lens_context or {}
        system_prompt = get_understanding_system_prompt(wafr_schema, lens_context=self.lens_context)
        
        try:
            # DISABLED: Bedrock agents don't support concurrent invocations
            # Using direct Bedrock calls instead to enable parallel processing (3x faster)
            # Default to Haiku for simple extraction (cost optimization)
            # Will switch to Sonnet for complex analysis at runtime
            understanding_model_id = ModelSelectionStrategy.get_model("simple_extraction", complexity="simple")
            model = get_strands_model(understanding_model_id)

            # Force use of direct Bedrock calls (supports parallel execution)
            self.agent = None
            # Try to add tools - catch any errors since Strands may handle tools differently
            try:
                # Try add_tool first
                try:
                    self.agent.add_tool(extract_insights)
                    self.agent.add_tool(segment_transcript)
                    logger.debug("Successfully added tools using add_tool")
                except AttributeError:
                    # Try register_tool as fallback
                    try:
                        self.agent.register_tool(extract_insights)
                        self.agent.register_tool(segment_transcript)
                        logger.debug("Successfully added tools using register_tool")
                    except AttributeError:
                        # Tools may be auto-detected via @tool decorator
                        logger.debug("Tools may be auto-detected by Strands via @tool decorator")
            except Exception as e:
                logger.warning(f"Could not add tools to agent: {e}. Tools may be auto-detected or not supported in this Strands version.")
        except Exception as e:
            logger.warning(f"Strands Agent initialization issue: {e}, using direct Bedrock")
            self.agent = None
    
    def process(self, transcript: str, session_id: str) -> Dict[str, Any]:
        """
        Process transcript and extract insights.
        
        Args:
            transcript: Workshop transcript text
            session_id: Session identifier
            
        Returns:
            Dictionary with extracted insights
        """
        logger.info(f"UnderstandingAgent: Processing transcript for session {session_id}")
        
        # Segment transcript if too long
        segments_data = smart_segment_transcript(transcript, max_segment_length=5000)
        segments = [seg['text'] for seg in segments_data]
        
        # Determine model based on complexity (for use in segment processing)
        # Use Sonnet for complex analysis (long transcript or many segments)
        is_complex_analysis = len(transcript) > 10000 or len(segments) > 5
        
        # Process segments in parallel batches
        def process_segment(segment_data: Dict) -> List[Dict]:
            idx = segment_data['index']
            segment = segment_data['text']
            
            prompt = f"""Extract architecture insights from this transcript segment. Return ONLY a valid JSON array.

TRANSCRIPT SEGMENT:
{segment[:4000]}

EXTRACT:
- Decisions: Technology choices, design patterns, architectural decisions
- Services: AWS services (EC2, S3, RDS, Lambda, ECS, X-Ray, CloudWatch, etc.) with usage context
- Constraints: Requirements, limitations, compliance, SLAs, security
- Risks: Security, availability, scalability, cost concerns

OUTPUT FORMAT - Return ONLY this JSON (no markdown, no explanations):
[
  {{
    "insight_type": "decision",
    "content": "Clear 1-2 sentence summary",
    "transcript_quote": "EXACT verbatim quote from transcript",
    "speaker": "Speaker name if identifiable",
    "timestamp": "Line {idx + 1} or position"
  }}
]

RULES:
- Every insight MUST have exact transcript_quote (mandatory)
- Only extract what is explicitly stated
- Focus on AWS Well-Architected Framework relevance
- Return ONLY the JSON array, nothing else."""
            
            try:
                response = None
                if self.agent:
                    try:
                        response = self._call_agent_with_retry(prompt)
                    except Exception as agent_error:
                        logger.warning(f"Strands agent failed for segment {idx}, falling back to direct Bedrock: {str(agent_error)}")
                        # Use model selection for fallback call
                        extraction_model_id = ModelSelectionStrategy.get_model_for_understanding(
                            transcript_length=len(segment),
                            is_complex_analysis=is_complex_analysis
                        )
                        response = self._call_bedrock_direct(prompt, model_id=extraction_model_id)
                else:
                    # Use model selection for direct Bedrock calls
                    # Determine if this segment is complex (use overall complexity for consistency)
                    extraction_model_id = ModelSelectionStrategy.get_model_for_understanding(
                        transcript_length=len(segment),
                        is_complex_analysis=is_complex_analysis
                    )
                    response = self._call_bedrock_direct(prompt, model_id=extraction_model_id)
                
                # Parse response to extract insights
                insights = self._parse_response(response, segment_idx=idx)
                
                # Validate and enrich insights
                validated_insights = []
                for insight in insights:
                    if validate_insight(insight):
                        insight['segment_index'] = idx
                        insight['session_id'] = session_id
                        validated_insights.append(insight)
                    else:
                        logger.warning(f"Invalid insight skipped: {insight.get('content', '')[:50]}")
                
                return validated_insights
            except Exception as e:
                logger.error(f"Error processing segment {idx}: {str(e)}")
                # Try fallback extraction as last resort
                try:
                    fallback_insights = self._fallback_extraction(segment, session_id)
                    return fallback_insights
                except Exception as fallback_error:
                    logger.debug(f"Fallback extraction also failed: {fallback_error}")
                    return []
        
        # Process segments in batches
        all_insights = []
        if len(segments_data) > 1:
            # Use parallel processing for multiple segments
            results = batch_process(
                segments_data,
                process_segment,
                batch_size=3,
                max_workers=3,
                timeout=120.0
            )
            all_insights = [insight for result in results for insight in result]
        else:
            # Single segment - process directly
            all_insights = process_segment(segments_data[0])
        
        # Deduplicate insights
        all_insights = deduplicate_insights(all_insights)
        
        # Fallback: If no insights extracted, try to extract at least basic information
        if not all_insights and transcript:
            logger.warning("No insights extracted - attempting fallback extraction")
            fallback_insights = self._fallback_extraction(transcript, session_id)
            if fallback_insights:
                all_insights = fallback_insights
                logger.info(f"Fallback extraction found {len(all_insights)} insights")
        
        return {
            'session_id': session_id,
            'total_insights': len(all_insights),
            'insights': all_insights,
            'agent': 'understanding'
        }
    
    @retry_with_backoff(max_retries=3, initial_delay=1.0)
    def _call_agent_with_retry(self, prompt: str) -> Any:
        """Call agent with retry logic."""
        if not self.agent:
            return self._call_bedrock_direct(prompt)
        return self.agent(prompt)
    
    def _parse_response(self, response: Any, segment_idx: int) -> List[Dict]:
        """Parse agent response to extract insights with robust JSON extraction."""
        insights = []
        
        try:
            # Convert response to string first for consistent processing
            response_text = ""
            if isinstance(response, str):
                response_text = response
            elif isinstance(response, dict):
                # Try to extract text from dict response
                if 'content' in response:
                    content = response.get('content', '')
                    if isinstance(content, str):
                        response_text = content
                    elif isinstance(content, list) and content:
                        # Extract text from content blocks
                        response_text = ' '.join([item.get('text', '') if isinstance(item, dict) else str(item) for item in content])
                elif 'text' in response:
                    response_text = str(response.get('text', ''))
                elif 'insights' in response:
                    candidate = response['insights']
                    insights = candidate if isinstance(candidate, list) else [candidate] if candidate else []
                else:
                    response_text = json.dumps(response, ensure_ascii=False)
            else:
                response_text = str(response)
            
            # If we have text, try to extract JSON
            if response_text and not insights:
                # Clean up the response text
                cleaned = response_text.strip()
                
                # Try multiple extraction strategies
                parsed = extract_json_from_text(cleaned, strict=False)
                
                if parsed:
                    if isinstance(parsed, list):
                        insights = parsed
                    elif isinstance(parsed, dict):
                        # Check for nested insights
                        if 'insights' in parsed:
                            candidate = parsed['insights']
                            insights = candidate if isinstance(candidate, list) else [candidate] if candidate else []
                        elif 'items' in parsed:
                            candidate = parsed['items']
                            insights = candidate if isinstance(candidate, list) else [candidate] if candidate else []
                        elif 'insight_type' in parsed or 'content' in parsed:
                            # Single insight
                            insights = [parsed]
            
            # If still no insights, try regex extraction
            if not insights and response_text:
                import re
                # Look for JSON arrays
                json_array_pattern = r'\[\s*\{[^}]+\}\s*(?:,\s*\{[^}]+\}\s*)*\]'
                matches = re.finditer(json_array_pattern, response_text, re.DOTALL)
                for match in matches:
                    try:
                        parsed_array = json.loads(match.group(0))
                        if isinstance(parsed_array, list) and parsed_array:
                            insights = parsed_array
                            break
                    except json.JSONDecodeError:
                        continue
                
                # Try individual insight objects
                if not insights:
                    insight_pattern = r'\{\s*"insight_type"[^}]+\}'
                    matches = re.finditer(insight_pattern, response_text, re.DOTALL)
                    for match in matches:
                        try:
                            insight_obj = json.loads(match.group(0))
                            if isinstance(insight_obj, dict):
                                insights.append(insight_obj)
                        except json.JSONDecodeError:
                            continue
                            
        except Exception as e:
            logger.error(f"Error parsing response: {str(e)}")
            logger.debug(f"Response type: {type(response)}, Response preview: {str(response)[:200]}")
        
        # Ensure all insights are dictionaries with required fields
        validated = []
        for insight in insights:
            if isinstance(insight, dict):
                # Ensure required fields exist with defaults
                if 'insight_type' not in insight:
                    insight['insight_type'] = 'decision'
                if 'content' not in insight:
                    insight['content'] = insight.get('summary', insight.get('text', ''))
                if 'transcript_quote' not in insight:
                    insight['transcript_quote'] = insight.get('quote', insight.get('evidence', ''))
                
                # Only add if it has at least content or transcript_quote
                if insight.get('content') or insight.get('transcript_quote'):
                    validated.append(insight)
        
        return validated
    
    def _fallback_extraction(self, transcript: str, session_id: str) -> List[Dict]:
        """
        Fallback extraction method when main agent returns no insights.
        Uses simple keyword-based extraction to find at least some information.
        """
        insights = []
        
        # Look for AWS services mentioned
        aws_services = [
            'EC2', 'S3', 'RDS', 'Lambda', 'CloudWatch', 'X-Ray', 'IAM', 
            'VPC', 'Route 53', 'Auto Scaling', 'ElastiCache', 'EKS', 
            'ECS', 'Fargate', 'Secrets Manager', 'GuardDuty', 'Security Hub',
            'CloudTrail', 'EventBridge', 'API Gateway', 'DynamoDB', 'SQS', 'SNS'
        ]
        
        lines = transcript.split('\n')
        for i, line in enumerate(lines):
            line_lower = line.lower()
            # Look for AWS services
            for service in aws_services:
                if service.lower() in line_lower:
                    # Extract context around the service mention
                    context_start = max(0, i - 2)
                    context_end = min(len(lines), i + 3)
                    context = '\n'.join(lines[context_start:context_end])
                    
                    insights.append({
                        'insight_type': 'service',
                        'content': f"AWS {service} mentioned in transcript",
                        'transcript_quote': line.strip()[:200],
                        'speaker': None,
                        'timestamp': f"Line {i+1}",
                        'confidence': 0.5,
                        'segment_index': 0,
                        'session_id': session_id
                    })
                    break  # Only one insight per line
        
        # Look for architecture decisions (keywords like "we use", "we have", "we implement")
        decision_keywords = ['we use', 'we have', 'we implement', 'we deploy', 'we run', 'we manage']
        for i, line in enumerate(lines):
            line_lower = line.lower()
            for keyword in decision_keywords:
                if keyword in line_lower and len(line.strip()) > 20:
                    insights.append({
                        'insight_type': 'decision',
                        'content': f"Architecture decision mentioned: {line.strip()[:100]}",
                        'transcript_quote': line.strip()[:200],
                        'speaker': None,
                        'timestamp': f"Line {i+1}",
                        'confidence': 0.4,
                        'segment_index': 0,
                        'session_id': session_id
                    })
                    break
        
        # Deduplicate
        return deduplicate_insights(insights)
    
    @retry_with_backoff(max_retries=3, initial_delay=1.0)
    def _call_bedrock_direct(self, prompt: str, model_id: str | None = None) -> str:
        """Fallback: Call Bedrock directly using invoke_model API."""
        import boto3
        import json
        from wafr.agents.config import BEDROCK_REGION
        
        # Use provided model_id or determine based on complexity
        if model_id is None:
            # Determine model based on prompt complexity (simple extraction → Haiku)
            # This is a simple heuristic - could be enhanced
            is_simple = len(prompt) < 2000
            model_id = ModelSelectionStrategy.get_model_for_understanding(
                transcript_length=len(prompt),
                is_complex_analysis=not is_simple
            )
        
        bedrock = boto3.client('bedrock-runtime', region_name=BEDROCK_REGION)
        system_prompt = get_understanding_system_prompt(self.wafr_schema)
        
        try:
            response = bedrock.invoke_model(
                modelId=model_id,
                body=json.dumps({
                    'anthropic_version': 'bedrock-2023-05-31',
                    'max_tokens': 4096,
                    'temperature': 0.1,
                    'system': system_prompt,
                    'messages': [{
                        'role': 'user',
                        'content': prompt
                    }]
                })
            )
            
            result = json.loads(response['body'].read())
            return result.get('content', [{}])[0].get('text', '')
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            
            if error_code in ['UnrecognizedClientException', 'InvalidClientTokenId', 'InvalidUserID.NotFound']:
                logger.error(f"Bedrock direct call failed due to invalid credentials: {error_msg}")
                from wafr.agents.utils import validate_aws_credentials
                _, cred_error_msg = validate_aws_credentials()
                logger.error(f"\n{cred_error_msg}")
                raise
            elif error_code == 'ExpiredToken':
                logger.error(f"Bedrock direct call failed due to expired token: {error_msg}")
                logger.error("Please refresh your AWS credentials (e.g., run 'aws sso login' or 'aws configure')")
                raise
            else:
                logger.error(f"Bedrock direct call failed: {error_code} - {error_msg}")
                raise
        except Exception as e:
            logger.error(f"Bedrock direct call failed: {e}")
            raise


def create_understanding_agent(wafr_schema: Optional[Dict] = None, lens_context: Optional[Dict] = None) -> UnderstandingAgent:
    """
    Factory function to create Understanding Agent.
    
    Args:
        wafr_schema: Optional WAFR schema for context
    """
    return UnderstandingAgent(wafr_schema=wafr_schema, lens_context=lens_context)

