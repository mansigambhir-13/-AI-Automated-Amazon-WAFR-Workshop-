"""
WAFR Knowledge Base Context Loader
Provides WAFR context and best practices to agents
Fetches official AWS Well-Architected Framework schema from AWS API
"""
import json
import os
import logging
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# Cache for official AWS schema
_aws_schema_cache: Optional[Dict] = None


def load_wafr_schema(schema_path: Optional[str] = None, use_aws_api: bool = True) -> Dict:
    """
    Load WAFR schema - tries AWS API first, falls back to file.
    
    Args:
        schema_path: Optional path to schema file
        use_aws_api: Whether to try fetching from AWS API first (default: True)
    
    Returns:
        WAFR schema dictionary (never None, always returns at least {'pillars': []})
    """
    global _aws_schema_cache
    
    # Try AWS API first if enabled
    if use_aws_api and _aws_schema_cache is None:
        try:
            logger.info("Attempting to fetch official AWS Well-Architected Framework schema from AWS API...")
            aws_schema = _fetch_official_aws_schema()
            if aws_schema and isinstance(aws_schema, dict) and aws_schema.get('pillars'):
                _aws_schema_cache = aws_schema
                logger.info(f"Successfully loaded official AWS schema with {len(aws_schema.get('pillars', []))} pillars")
                return aws_schema
            else:
                logger.warning("AWS API returned empty or invalid schema, falling back to file")
        except ImportError as import_err:
            logger.warning(f"AWS API client not available: {import_err}. Falling back to file.")
        except Exception as e:
            logger.warning(f"Could not fetch schema from AWS API: {e}. Falling back to file.")
    
    # Return cached AWS schema if available
    if _aws_schema_cache and isinstance(_aws_schema_cache, dict):
        return _aws_schema_cache
    
    # Fall back to file-based schema
    if schema_path is None:
        # Look in multiple possible locations
        base_dir = os.path.dirname(__file__)
        possible_paths = [
            # Relative to workspace
            'knowledge_base/wafr-schema.json',
            'schemas/wafr-schema.json',
            'data/schemas/wafr-schema.json',
            'data/schemas/schemas/wafr-schema.json',
            # Relative to this file
            os.path.join(base_dir, '..', 'knowledge_base', 'wafr-schema.json'),
            os.path.join(base_dir, '..', 'schemas', 'wafr-schema.json'),
            os.path.join(base_dir, '..', '..', 'knowledge_base', 'wafr-schema.json'),
            os.path.join(base_dir, '..', '..', 'data', 'schemas', 'schemas', 'wafr-schema.json'),
            # Deployment paths
            '/opt/wafr/knowledge_base/wafr-schema.json',
            '/opt/wafr/schemas/wafr-schema.json',
        ]
        
        for path in possible_paths:
            abs_path = os.path.abspath(path)
            if os.path.exists(abs_path):
                schema_path = abs_path
                logger.debug(f"Found schema file at: {abs_path}")
                break
    
    if schema_path and os.path.exists(schema_path):
        try:
            with open(schema_path, 'r', encoding='utf-8') as f:
                file_schema = json.load(f)
                
                # Validate schema structure
                if not isinstance(file_schema, dict):
                    logger.error(f"Schema file is not a dictionary: {type(file_schema)}")
                    return {'pillars': []}
                
                if 'pillars' not in file_schema:
                    logger.warning(f"Schema file missing 'pillars' key, wrapping content")
                    file_schema = {'pillars': file_schema.get('questions', [])}
                
                logger.info(f"Loaded schema from file: {schema_path} ({len(file_schema.get('pillars', []))} pillars)")
                return file_schema
        except json.JSONDecodeError as json_err:
            logger.error(f"Invalid JSON in schema file {schema_path}: {json_err}")
        except Exception as e:
            logger.error(f"Error loading WAFR schema from file {schema_path}: {e}", exc_info=True)
    else:
        logger.warning(f"Schema file not found. Checked paths: {schema_path or 'multiple locations'}")
    
    logger.warning("No schema available - using empty schema. This may cause limited functionality.")
    return {'pillars': []}


def _fetch_official_aws_schema() -> Optional[Dict]:
    """
    Fetch official AWS Well-Architected Framework schema from AWS API.
    
    Note: AWS get_lens() only returns metadata. To get questions, we need a workload.
    We'll create a temporary workload, get all questions, then optionally clean it up.
    
    Returns:
        Official AWS schema dictionary or None if failed
    """
    try:
        from wafr.agents.wa_tool_client import WellArchitectedToolClient
        from wafr.agents.config import BEDROCK_REGION
        from datetime import datetime
        
        # Initialize WA Tool client
        wa_client = WellArchitectedToolClient(region=BEDROCK_REGION)
        
        # Get lens metadata first
        logger.info("Fetching official 'wellarchitected' lens metadata from AWS...")
        lens_response = wa_client.get_lens(lens_alias='wellarchitected')
        
        if not lens_response or 'Lens' not in lens_response:
            logger.error("Invalid response from AWS get_lens API")
            return None
        
        lens_metadata = lens_response.get('Lens', {})
        lens_version = lens_metadata.get('LensVersion', 'unknown')
        lens_name = lens_metadata.get('Name', 'AWS Well-Architected Framework')
        
        # Create a temporary workload to get questions
        logger.info("Creating temporary workload to fetch all questions...")
        temp_workload_name = f"WAFR_Schema_Fetch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        try:
            workload = wa_client.create_workload(
                workload_name=temp_workload_name,
                description="Temporary workload for schema fetching",
                environment='PREPRODUCTION',  # AWS only accepts PRODUCTION or PREPRODUCTION
                aws_regions=[BEDROCK_REGION],
                lenses=['wellarchitected'],
                tags={'Purpose': 'SchemaFetch', 'Temporary': 'true'}
            )
            workload_id = workload.get('WorkloadId')
            logger.info(f"Created temporary workload: {workload_id}")
            
            # Get all questions from the workload
            logger.info("Fetching all questions from workload...")
            all_questions = _get_all_questions_from_workload(wa_client, workload_id, 'wellarchitected')
            
            if not all_questions:
                logger.warning("No questions found in workload")
                # Clean up
                try:
                    wa_client.delete_workload(workload_id)
                    logger.info("Cleaned up temporary workload")
                except Exception as cleanup_error:
                    logger.debug(f"Could not delete temporary workload during cleanup: {cleanup_error}")
                return None
            
            logger.info(f"Found {len(all_questions)} questions from AWS")
            
            # Transform questions to schema format
            schema = _transform_questions_to_schema(all_questions, lens_metadata)
            
            # Clean up temporary workload (optional - comment out if you want to keep it)
            try:
                wa_client.delete_workload(workload_id)
                logger.info("Cleaned up temporary workload")
            except Exception as cleanup_error:
                logger.warning(f"Could not delete temporary workload {workload_id}: {cleanup_error}")
                logger.info(f"You may want to manually delete workload: {workload_id}")
            
            if schema and schema.get('pillars'):
                logger.info(f"Successfully transformed AWS questions to schema with {len(schema['pillars'])} pillars")
                return schema
            else:
                logger.error("Failed to transform questions to schema format")
                return None
                
        except Exception as workload_error:
            logger.error(f"Error creating/fetching from workload: {str(workload_error)}")
            return None
            
    except ImportError:
        logger.warning("WA Tool client not available - cannot fetch from AWS API")
        return None
    except Exception as e:
        logger.error(f"Error fetching official AWS schema: {str(e)}", exc_info=True)
        return None


def _get_all_questions_from_workload(wa_client, workload_id: str, lens_alias: str) -> List[Dict]:
    """
    Get all questions from a workload by iterating through pillars.
    
    Args:
        wa_client: WellArchitectedToolClient instance
        workload_id: Workload ID
        lens_alias: Lens alias
        
    Returns:
        List of all questions with full details
    """
    all_questions = []
    
    try:
        # Get lens review to get pillar structure
        lens_review = wa_client.get_lens_review(
            workload_id=workload_id,
            lens_alias=lens_alias
        )
        
        lens_review_data = lens_review.get('LensReview', {})
        pillar_review_summaries = lens_review_data.get('PillarReviewSummaries', [])
        
        # Iterate through each pillar
        for pillar_summary in pillar_review_summaries:
            pillar_id = pillar_summary.get('PillarId', '')
            
            # List answers for this pillar
            answers = wa_client.list_answers(
                workload_id=workload_id,
                lens_alias=lens_alias,
                pillar_id=pillar_id
            )
            
            # Get full question details for each answer
            for answer_summary in answers:
                question_id = answer_summary.get('QuestionId', '')
                if not question_id:
                    continue
                
                try:
                    # Get full question details
                    answer_details = wa_client.get_answer(
                        workload_id=workload_id,
                        lens_alias=lens_alias,
                        question_id=question_id
                    )
                    
                    question_data = answer_details.get('Question', {})
                    answer_data = answer_details.get('Answer', {})
                    
                    # Question title might be in answer_summary or question_data
                    question_title = (
                        answer_summary.get('QuestionTitle', '') or 
                        question_data.get('QuestionTitle', '') or
                        question_data.get('Title', '')
                    )
                    question_description = (
                        answer_summary.get('QuestionDescription', '') or
                        question_data.get('QuestionDescription', '') or
                        question_data.get('Description', '')
                    )
                    
                    # Combine question and answer data
                    full_question = {
                        'QuestionId': question_id,
                        'QuestionTitle': question_title,
                        'QuestionDescription': question_description,
                        'PillarId': pillar_id,
                        'PillarName': pillar_summary.get('PillarName', ''),
                        'Choices': answer_data.get('Choices', []),
                        'HelpfulResource': question_data.get('HelpfulResource', {}),
                        'Risk': answer_summary.get('Risk', '')
                    }
                    
                    all_questions.append(full_question)
                    
                except Exception as e:
                    logger.warning(f"Error getting question {question_id}: {e}")
                    continue
        
        return all_questions
        
    except Exception as e:
        logger.error(f"Error getting questions from workload: {e}")
        return []


def _transform_questions_to_schema(questions: List[Dict], lens_metadata: Dict) -> Dict:
    """
    Transform list of AWS questions to schema format.
    
    Args:
        questions: List of question dictionaries from AWS API
        lens_metadata: Lens metadata from get_lens()
    
    Returns:
        Schema dictionary
    """
    try:
        schema = {
            'version': lens_metadata.get('LensVersion', 'unknown'),
            'description': lens_metadata.get('Description', lens_metadata.get('Name', 'AWS Well-Architected Framework')),
            'last_updated': datetime.utcnow().isoformat(),
            'pillars': []
        }
        
        # Group questions by pillar - AWS uses these exact pillar IDs
        pillar_id_map = {
            'operationalExcellence': 'OPS',
            'security': 'SEC',
            'reliability': 'REL',
            'performance': 'PERF',  # AWS uses 'performance', not 'performanceEfficiency'
            'costOptimization': 'COST',
            'sustainability': 'SUS'
        }
        
        pillar_name_map = {
            'operationalExcellence': 'Operational Excellence',
            'security': 'Security',
            'reliability': 'Reliability',
            'performance': 'Performance Efficiency',  # AWS uses 'performance'
            'costOptimization': 'Cost Optimization',
            'sustainability': 'Sustainability'
        }
        
        questions_by_pillar = {}
        for question in questions:
            pillar_id_aws = question.get('PillarId', '')
            pillar_id = pillar_id_map.get(pillar_id_aws, pillar_id_aws.upper()[:3] if pillar_id_aws else 'UNKNOWN')
            
            if pillar_id not in questions_by_pillar:
                questions_by_pillar[pillar_id] = {
                    'pillar_id': pillar_id,
                    'pillar_name': pillar_name_map.get(pillar_id_aws, question.get('PillarName', pillar_id)),
                    'questions': []
                }
            
            # Transform question
            transformed_question = _transform_single_question(question, pillar_id)
            if transformed_question:
                questions_by_pillar[pillar_id]['questions'].append(transformed_question)
        
        # Convert to schema format
        for pillar_id, pillar_data in questions_by_pillar.items():
            schema['pillars'].append({
                'id': pillar_data['pillar_id'],
                'name': pillar_data['pillar_name'],
                'description': f"AWS Well-Architected Framework {pillar_data['pillar_name']} pillar",
                'questions': pillar_data['questions']
            })
        
        logger.info(f"Transformed {len(questions)} questions into {len(schema['pillars'])} pillars")
        return schema
        
    except Exception as e:
        logger.error(f"Error transforming questions to schema: {str(e)}", exc_info=True)
        return {'pillars': []}


def _transform_single_question(aws_question: Dict, pillar_id: str) -> Optional[Dict]:
    """Transform a single AWS question to our schema format."""
    try:
        question_id = aws_question.get('QuestionId', '')
        question_title = aws_question.get('QuestionTitle', '')
        question_description = aws_question.get('QuestionDescription', '')
        
        if not question_id or not question_title:
            return None
        
        choices = aws_question.get('Choices', [])
        best_practices = []
        hri_indicators = []
        related_services = []
        
        # Process choices
        for choice in choices:
            choice_title = choice.get('Title', '')
            choice_description = choice.get('Description', '')
            choice_id = choice.get('ChoiceId', '')
            
            choice_id_lower = choice_id.lower() if choice_id else ''
            
            # High-risk indicators
            if any(term in choice_id_lower for term in ['high', 'risk', 'none', 'not', 'missing', 'no']):
                if choice_description:
                    hri_indicators.append(choice_description[:200])
                elif choice_title:
                    hri_indicators.append(choice_title[:200])
            
            # Best practices (exclude high-risk choices)
            if choice_title and choice_description and not any(term in choice_id_lower for term in ['high', 'risk', 'none', 'not']):
                best_practices.append({
                    'id': f"{question_id}_BP{len(best_practices) + 1:02d}",
                    'text': choice_title,
                    'example_good_answer': choice_description[:300],
                    'keywords': _extract_keywords(choice_title + ' ' + choice_description)
                })
        
        # Extract keywords
        full_text = f"{question_title} {question_description}".strip()
        keywords = _extract_keywords(full_text)
        
        # Determine criticality
        risk = aws_question.get('Risk', '')
        criticality = 'medium'
        if 'critical' in risk.lower() or 'high' in risk.lower():
            criticality = 'critical'
        elif 'medium' in risk.lower():
            criticality = 'high'
        
        # Extract related services
        helpful_resource = aws_question.get('HelpfulResource', {})
        if helpful_resource:
            display_text = helpful_resource.get('DisplayText', '')
            aws_services = ['CloudWatch', 'X-Ray', 'IAM', 'S3', 'RDS', 'Lambda', 'EC2', 'EKS', 'ECS',
                           'Secrets Manager', 'Parameter Store', 'Auto Scaling', 'Route 53',
                           'Service Quotas', 'Cost Explorer', 'AWS Budgets', 'Compute Optimizer',
                           'Access Analyzer', 'GuardDuty', 'Security Hub', 'CloudTrail', 'VPC',
                           'Elastic Load Balancing', 'API Gateway', 'DynamoDB', 'SQS', 'SNS']
            for service in aws_services:
                if service.lower() in display_text.lower():
                    if service not in related_services:
                        related_services.append(service)
        
        return {
            'id': question_id,
            'text': question_title,
            'description': question_description,
            'criticality': criticality,
            'category': _categorize_question(question_title, pillar_id),
            'keywords': keywords[:10],
            'best_practices': best_practices[:5],
            'hri_indicators': hri_indicators[:5],
            'related_services': related_services[:10]
        }
        
    except Exception as e:
        logger.warning(f"Error transforming question: {e}")
        return None


def _transform_aws_lens_to_schema_old(aws_lens: Dict) -> Dict:
    """
    Transform AWS lens API response to our schema format.
    
    AWS Lens structure (from get_lens API):
    - Lens: {
        - LensArn, LensVersion, Name, Description
        - Pillars: List of pillar objects with:
          - PillarId, PillarName, PillarReviewSummary
          - Questions: List of question objects with:
            - QuestionId, QuestionTitle, QuestionDescription
            - Choices: List of choice objects with Title, Description, ChoiceId
            - Risk, HelpfulResource
      }
    
    Our schema format:
    - version, description
    - pillars: List with id, name, description, questions
      - questions: List with id, text, criticality, category, keywords, best_practices, hri_indicators, related_services
    """
    try:
        # Handle different response structures
        lens_data = aws_lens.get('Lens', aws_lens)
        
        schema = {
            'version': lens_data.get('LensVersion', lens_data.get('Version', 'unknown')),
            'description': lens_data.get('Description', lens_data.get('Name', 'AWS Well-Architected Framework')),
            'last_updated': lens_data.get('UpdatedAt', ''),
            'pillars': []
        }
        
        pillars = lens_data.get('Pillars', [])
        if not pillars:
            # Try alternative structure
            pillars = aws_lens.get('Pillars', [])
        
        logger.info(f"Processing {len(pillars)} pillars from AWS lens")
        
        # Pillar ID mapping (AWS uses different IDs)
        pillar_id_map = {
            'operationalExcellence': 'OPS',
            'security': 'SEC',
            'reliability': 'REL',
            'performanceEfficiency': 'PERF',
            'costOptimization': 'COST',
            'sustainability': 'SUS'
        }
        
        pillar_name_map = {
            'operationalExcellence': 'Operational Excellence',
            'security': 'Security',
            'reliability': 'Reliability',
            'performanceEfficiency': 'Performance Efficiency',
            'costOptimization': 'Cost Optimization',
            'sustainability': 'Sustainability'
        }
        
        for aws_pillar in pillars:
            pillar_id_aws = aws_pillar.get('PillarId', '')
            pillar_id = pillar_id_map.get(pillar_id_aws, pillar_id_aws.upper()[:3])
            pillar_name = pillar_name_map.get(pillar_id_aws, aws_pillar.get('PillarName', ''))
            
            pillar_summary = aws_pillar.get('PillarReviewSummary', {})
            questions = aws_pillar.get('Questions', [])
            
            logger.info(f"Processing pillar {pillar_id} ({pillar_name}) with {len(questions)} questions")
            
            transformed_questions = []
            for aws_question in questions:
                question_id = aws_question.get('QuestionId', '')
                question_title = aws_question.get('QuestionTitle', aws_question.get('Title', ''))
                question_description = aws_question.get('QuestionDescription', aws_question.get('Description', ''))
                
                if not question_id or not question_title:
                    logger.warning(f"Skipping question without ID or title: {aws_question}")
                    continue
                
                # Extract choices (best practices are often in choices)
                choices = aws_question.get('Choices', [])
                best_practices = []
                hri_indicators = []
                related_services = []
                keywords = []
                
                # Process choices to extract best practices
                for choice in choices:
                    choice_title = choice.get('Title', choice.get('Name', ''))
                    choice_description = choice.get('Description', '')
                    choice_id = choice.get('ChoiceId', choice.get('Id', ''))
                    
                    # High-risk choices often indicate HRIs
                    choice_id_lower = choice_id.lower() if choice_id else ''
                    if any(term in choice_id_lower for term in ['high', 'risk', 'none', 'not', 'missing', 'no']):
                        if choice_description:
                            hri_indicators.append(choice_description[:200])
                        elif choice_title:
                            hri_indicators.append(choice_title[:200])
                    
                    # Good choices are best practices (exclude high-risk ones)
                    if choice_title and choice_description and not any(term in choice_id_lower for term in ['high', 'risk', 'none', 'not']):
                        best_practices.append({
                            'id': f"{question_id}_BP{len(best_practices) + 1:02d}",
                            'text': choice_title,
                            'example_good_answer': choice_description[:300],
                            'keywords': _extract_keywords(choice_title + ' ' + choice_description)
                        })
                
                # Extract keywords from question text
                full_text = f"{question_title} {question_description}".strip()
                keywords = _extract_keywords(full_text)
                
                # Determine criticality from question ID or risk
                risk = aws_question.get('Risk', '')
                criticality = 'medium'
                if 'critical' in risk.lower() or 'high' in risk.lower():
                    criticality = 'critical'
                elif 'medium' in risk.lower():
                    criticality = 'high'
                
                # Extract related services from helpful resources
                helpful_resources = aws_question.get('HelpfulResource', {})
                if helpful_resources:
                    display_text = helpful_resources.get('DisplayText', '')
                    # Extract AWS service names (common patterns)
                    aws_services = ['CloudWatch', 'X-Ray', 'IAM', 'S3', 'RDS', 'Lambda', 'EC2', 'EKS', 'ECS', 
                                   'Secrets Manager', 'Parameter Store', 'Auto Scaling', 'Route 53', 
                                   'Service Quotas', 'Cost Explorer', 'AWS Budgets', 'Compute Optimizer',
                                   'Access Analyzer', 'GuardDuty', 'Security Hub', 'CloudTrail']
                    for service in aws_services:
                        if service.lower() in display_text.lower():
                            if service not in related_services:
                                related_services.append(service)
                
                transformed_question = {
                    'id': question_id,
                    'text': question_title,
                    'description': question_description,
                    'criticality': criticality,
                    'category': _categorize_question(question_title, pillar_id),
                    'keywords': keywords[:10],  # Limit to top 10 keywords
                    'best_practices': best_practices[:5],  # Limit to top 5 best practices
                    'hri_indicators': hri_indicators[:5],  # Limit to top 5 HRI indicators
                    'related_services': related_services[:10]  # Limit to top 10 services
                }
                
                transformed_questions.append(transformed_question)
            
            pillar = {
                'id': pillar_id,
                'name': pillar_name,
                'description': pillar_summary.get('Notes', '') or f"AWS Well-Architected Framework {pillar_name} pillar",
                'questions': transformed_questions
            }
            
            schema['pillars'].append(pillar)
            logger.info(f"Transformed pillar {pillar_id}: {len(transformed_questions)} questions")
        
        return schema
        
    except Exception as e:
        logger.error(f"Error transforming AWS lens to schema: {str(e)}", exc_info=True)
        return {'pillars': []}


def _extract_keywords(text: str) -> List[str]:
    """Extract keywords from text."""
    if not text:
        return []
    
    # Common AWS and technical keywords
    keywords = []
    text_lower = text.lower()
    
    # AWS services
    aws_services = ['cloudwatch', 'x-ray', 'iam', 's3', 'rds', 'lambda', 'ec2', 'eks', 'ecs',
                   'secrets manager', 'parameter store', 'auto scaling', 'route 53',
                   'service quotas', 'cost explorer', 'aws budgets', 'compute optimizer',
                   'access analyzer', 'guardduty', 'security hub', 'cloudtrail', 'vpc',
                   'elastic load balancing', 'api gateway', 'dynamodb', 'sqs', 'sns']
    
    for service in aws_services:
        if service in text_lower:
            keywords.append(service.title())
    
    # Technical terms
    tech_terms = ['monitoring', 'logging', 'observability', 'metrics', 'tracing', 'alerting',
                 'authentication', 'authorization', 'encryption', 'backup', 'disaster recovery',
                 'high availability', 'scalability', 'performance', 'cost', 'security',
                 'compliance', 'governance', 'automation', 'deployment', 'testing']
    
    for term in tech_terms:
        if term in text_lower and term not in [k.lower() for k in keywords]:
            keywords.append(term)
    
    return keywords[:10]  # Return top 10 keywords


def _categorize_question(question_text: str, pillar_id: str) -> str:
    """Categorize question based on text and pillar."""
    text_lower = question_text.lower()
    
    category_map = {
        'OPS': {
            'monitoring': 'Observability',
            'logging': 'Observability',
            'metrics': 'Observability',
            'tracing': 'Observability',
            'deployment': 'Deployment',
            'automation': 'Automation',
            'process': 'Process Management',
            'priority': 'Workload Management'
        },
        'SEC': {
            'identity': 'Identity and Access Management',
            'iam': 'Identity and Access Management',
            'permission': 'Access Control',
            'encryption': 'Data Protection',
            'compliance': 'Compliance',
            'threat': 'Threat Detection'
        },
        'REL': {
            'failure': 'Fault Tolerance',
            'backup': 'Backup and Recovery',
            'quota': 'Service Management',
            'scaling': 'Scaling'
        },
        'PERF': {
            'resource': 'Resource Selection',
            'performance': 'Performance Optimization',
            'monitoring': 'Performance Monitoring'
        },
        'COST': {
            'cost': 'Financial Management',
            'budget': 'Financial Management',
            'optimization': 'Cost Optimization'
        },
        'SUS': {
            'region': 'Region Selection',
            'carbon': 'Carbon Footprint',
            'energy': 'Energy Efficiency'
        }
    }
    
    categories = category_map.get(pillar_id, {})
    for keyword, category in categories.items():
        if keyword in text_lower:
            return category
    
    return 'General'


def get_wafr_context_summary(wafr_schema: Dict) -> str:
    """Generate a comprehensive WAFR context summary for agents."""
    if not wafr_schema or 'pillars' not in wafr_schema:
        return "WAFR schema not available."
    
    context_parts = [
        "AWS WELL-ARCHITECTED FRAMEWORK REVIEW (WAFR) CONTEXT",
        "=" * 70,
        "",
        f"Schema Version: {wafr_schema.get('version', 'unknown')}",
        f"Last Updated: {wafr_schema.get('last_updated', 'unknown')}",
        "",
        "THE SIX WAFR PILLARS:",
        ""
    ]
    
    for pillar in wafr_schema.get('pillars', []):
        pillar_id = pillar.get('id', 'UNKNOWN')
        pillar_name = pillar.get('name', 'Unknown')
        description = pillar.get('description', '')
        questions = pillar.get('questions', [])
        
        context_parts.append(f"{pillar_id} - {pillar_name}")
        context_parts.append(f"  Description: {description}")
        context_parts.append(f"  Questions: {len(questions)}")
        context_parts.append("")
    
    context_parts.append("")
    context_parts.append("KEY WAFR PRINCIPLES:")
    context_parts.append("1. Operational Excellence: Run and monitor systems to deliver business value")
    context_parts.append("2. Security: Protect information and assets")
    context_parts.append("3. Reliability: Recover from failures and meet demand")
    context_parts.append("4. Performance Efficiency: Use resources efficiently")
    context_parts.append("5. Cost Optimization: Manage costs effectively")
    context_parts.append("6. Sustainability: Minimize environmental impact")
    context_parts.append("")
    
    return "\n".join(context_parts)


def get_question_context(question_id: str, wafr_schema: Dict) -> Optional[str]:
    """Get detailed context for a specific question."""
    if not wafr_schema or 'pillars' not in wafr_schema:
        return None
    
    for pillar in wafr_schema.get('pillars', []):
        for question in pillar.get('questions', []):
            if question.get('id') == question_id:
                context_parts = [
                    f"QUESTION: {question.get('text', '')}",
                    f"Pillar: {pillar.get('name', '')} ({pillar.get('id', '')})",
                    f"Criticality: {question.get('criticality', 'medium')}",
                    f"Category: {question.get('category', 'General')}",
                    ""
                ]
                
                if question.get('keywords'):
                    context_parts.append(f"Keywords: {', '.join(question.get('keywords', []))}")
                    context_parts.append("")
                
                best_practices = question.get('best_practices', [])
                if best_practices:
                    context_parts.append("BEST PRACTICES:")
                    for i, bp in enumerate(best_practices, 1):
                        context_parts.append(f"  {i}. {bp.get('text', '')}")
                        if bp.get('example_good_answer'):
                            context_parts.append(f"     Example: {bp.get('example_good_answer', '')[:100]}...")
                    context_parts.append("")
                
                hri_indicators = question.get('hri_indicators', [])
                if hri_indicators:
                    context_parts.append("HIGH-RISK ISSUE (HRI) INDICATORS:")
                    for indicator in hri_indicators:
                        context_parts.append(f"  - {indicator}")
                    context_parts.append("")
                
                related_services = question.get('related_services', [])
                if related_services:
                    context_parts.append(f"Related AWS Services: {', '.join(related_services)}")
                    context_parts.append("")
                
                return "\n".join(context_parts)
    
    return None


def get_pillar_questions_summary(pillar_id: str, wafr_schema: Dict) -> str:
    """Get summary of all questions for a pillar."""
    if not wafr_schema or 'pillars' not in wafr_schema:
        return ""
    
    for pillar in wafr_schema.get('pillars', []):
        if pillar.get('id') == pillar_id:
            questions = pillar.get('questions', [])
            summary_parts = [
                f"{pillar.get('name', '')} ({pillar_id}) Questions:",
                ""
            ]
            
            for q in questions:
                summary_parts.append(f"  {q.get('id', '')}: {q.get('text', '')}")
                summary_parts.append(f"    Criticality: {q.get('criticality', 'medium')}")
            
            return "\n".join(summary_parts)
    
    return ""


def refresh_aws_schema_cache() -> bool:
    """
    Force refresh of AWS schema cache.
    
    Returns:
        True if successful, False otherwise
    """
    global _aws_schema_cache
    _aws_schema_cache = None
    
    try:
        schema = load_wafr_schema(use_aws_api=True)
        if schema and schema.get('pillars'):
            logger.info(f"Successfully refreshed AWS schema cache with {len(schema['pillars'])} pillars")
            return True
        else:
            logger.warning("Failed to refresh AWS schema cache")
            return False
    except Exception as e:
        logger.error(f"Error refreshing AWS schema cache: {str(e)}")
        return False


def get_schema_source() -> str:
    """
    Get the source of the current schema (AWS API or file).
    
    Returns:
        'aws_api', 'file', or 'empty'
    """
    global _aws_schema_cache
    if _aws_schema_cache:
        return 'aws_api'
    
    # Check if file exists
    possible_paths = [
        'knowledge_base/wafr-schema.json',
        'schemas/wafr-schema.json',
        os.path.join(os.path.dirname(__file__), '..', 'knowledge_base', 'wafr-schema.json'),
        os.path.join(os.path.dirname(__file__), '..', 'schemas', 'wafr-schema.json')
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            return 'file'
    
    return 'empty'

