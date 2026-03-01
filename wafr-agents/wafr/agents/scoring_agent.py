"""
Answer Scoring and Ranking Agent - Multi-dimensional scoring with grade assignment
Uses direct Bedrock API for parallel processing
"""
import boto3
import json
import logging
import threading
from typing import Any, Dict, List, Optional

from strands import Agent, tool

from wafr.agents.config import DEFAULT_MODEL_ID, ModelSelectionStrategy
from wafr.agents.model_config import get_strands_model
from wafr.agents.utils import (
    batch_process,
    extract_json_from_text,
    retry_with_backoff,
)
from wafr.agents.wafr_context import get_question_context, load_wafr_schema

logger = logging.getLogger(__name__)


def get_scoring_system_prompt(wafr_schema: Optional[Dict[str, Any]] = None) -> str:
    """Generate enhanced system prompt with WAFR context."""
    base_prompt = """
You are an expert WAFR (AWS Well-Architected Framework Review) evaluator. You score answers on multiple dimensions using WAFR best practices.

SCORING DIMENSIONS:

1. CONFIDENCE (40% weight): Evidence quality and verification
   - Evidence citations present and verifiable
   - Evidence verified in transcript
   - Source reliability and accuracy
   - No unsupported claims or assumptions

2. COMPLETENESS (30% weight): How well answer addresses the WAFR question
   - Best practices from WAFR schema addressed
   - Answer specificity and detail
   - AWS service mentions with context
   - Coverage of question intent

3. COMPLIANCE (30% weight): Alignment with WAFR best practices
   - Adherence to recommended best practices
   - Anti-pattern penalties (if present)
   - HRI (High-Risk Issue) indicators (negative impact)
   - Recommended AWS services mentioned (positive)
   - Alignment with WAFR pillar principles

GRADE ASSIGNMENT:
- A (90-100): Excellent, fully compliant with WAFR best practices
- B (80-89): Good, minor gaps, mostly aligned with best practices
- C (70-79): Adequate, some improvements needed, partial compliance
- D (60-69): Needs significant work, missing key best practices
- F (<60): Critical gaps, non-compliant, or missing essential practices

SCORING PROCESS:
1. Review the answer against WAFR question best practices
2. Assess evidence quality and verification
3. Evaluate completeness against question requirements
4. Check compliance with WAFR best practices
5. Calculate composite score using weighted average
6. Assign grade based on composite score
7. Identify best practices met and missing
8. Flag any HRI indicators

Be thorough and fair in your evaluation. Use WAFR best practices as the standard.
"""
    
    return base_prompt


@tool
def calculate_composite_score(
    confidence_score: float,
    completeness_score: float,
    compliance_score: float
) -> Dict:
    """
    Calculate composite score from three dimensions.
    
    Args:
        confidence_score: Confidence score (0-100)
        completeness_score: Completeness score (0-100)
        compliance_score: Compliance score (0-100)
        
    Returns:
        Composite score and grade
    """
    # Weighted average
    composite = (
        confidence_score * 0.4 +
        completeness_score * 0.3 +
        compliance_score * 0.3
    )
    
    # Assign grade
    if composite >= 90:
        grade = 'A'
    elif composite >= 80:
        grade = 'B'
    elif composite >= 70:
        grade = 'C'
    elif composite >= 60:
        grade = 'D'
    else:
        grade = 'F'
    
    return {
        'composite_score': round(composite, 2),
        'grade': grade,
        'confidence': round(confidence_score, 2),
        'completeness': round(completeness_score, 2),
        'compliance': round(compliance_score, 2)
    }


@tool
def assess_answer(
    answer: str,
    question_id: str,
    best_practices: List[Dict],
    evidence_quotes: List[str],
    source: str
) -> Dict:
    """
    Assess an answer and return scores.
    
    Args:
        answer: Answer content
        question_id: Question identifier
        best_practices: List of best practices for question
        evidence_quotes: List of evidence quotes
        source: Answer source (transcript_direct, user_input, etc.)
        
    Returns:
        Assessment with scores
    """
    # This would be enhanced by LLM reasoning
    # For now, provide structure
    return {
        'question_id': question_id,
        'answer': answer,
        'best_practices_met': [],
        'best_practices_missing': [],
        'hri_indicators': [],
        'improvement_suggestions': []
    }


@tool
def calculate_rank_priority(
    question_id: str,
    grade: str,
    hri_indicators: List[str],
    criticality: str,
    source: str
) -> int:
    """
    Calculate review priority (1 = highest priority).
    Lower number = needs attention first.
    
    Args:
        question_id: Question identifier
        grade: Answer grade (A-F)
        hri_indicators: List of HRI indicators
        criticality: Question criticality
        source: Answer source
        
    Returns:
        Priority rank (1-100)
    """
    priority = 100
    
    # Criticality adjustment
    criticality_adjustments = {
        'critical': -40,
        'high': -20,
        'medium': 0,
        'low': 20
    }
    priority += criticality_adjustments.get(criticality, 0)
    
    # Grade adjustment
    grade_adjustments = {
        'F': -30,
        'D': -15,
        'C': 0,
        'B': 15,
        'A': 30
    }
    priority += grade_adjustments.get(grade, 0)
    
    # HRI adjustment
    if hri_indicators:
        priority -= 25
    
    # Source adjustment
    if source == 'not_answered':
        priority -= 35
    elif source == 'transcript_inferred':
        priority -= 10
    
    return max(1, priority)


class ScoringAgent:
    """Agent that scores and ranks WAFR answers."""
    
    def __init__(self, wafr_schema: Optional[Dict] = None):
        """
        Initialize Scoring Agent.
        
        Args:
            wafr_schema: Optional WAFR schema for context
        """
        if wafr_schema is None:
            wafr_schema = load_wafr_schema()
        
        self.wafr_schema = wafr_schema
        system_prompt = get_scoring_system_prompt(wafr_schema)
        self.system_prompt = system_prompt
        self._bedrock_client = None
        self.region_name = "us-east-1"  # Default region

        # Thread-local storage for agents (to support parallel processing)
        import threading
        self._thread_local = threading.local()
        
        try:
            # Use Haiku for scoring (simpler task, cost optimization)
            scoring_model_id = ModelSelectionStrategy.get_model("scoring", complexity="simple")
            model = get_strands_model(scoring_model_id)
            self.model = model  # Store for thread-local agent creation
            self.scoring_model_id = scoring_model_id
            
            agent_kwargs = {
                'system_prompt': system_prompt,
                'name': 'ScoringAgent'
            }
            if model:
                agent_kwargs['model'] = model
            
            self.agent = Agent(**agent_kwargs)
            # Try to add tools if method exists
            try:
                try:
                    self.agent.add_tool(calculate_composite_score)
                    self.agent.add_tool(assess_answer)
                    self.agent.add_tool(calculate_rank_priority)
                except AttributeError:
                    try:
                        self.agent.register_tool(calculate_composite_score)
                        self.agent.register_tool(assess_answer)
                        self.agent.register_tool(calculate_rank_priority)
                    except AttributeError:
                        pass  # Tools may be auto-detected
            except Exception as e:
                logger.warning(f"Could not add tools to scoring agent: {e}")
        except Exception as e:
            logger.warning(f"Strands Agent initialization issue: {e}, using direct Bedrock")
            self.agent = None
            self.model = None
            self.scoring_model_id = None

    @property
    def bedrock(self) -> Any:
        """Lazily initialize Bedrock client on first use for parallel processing."""
        if self._bedrock_client is None:
            self._bedrock_client = boto3.client(
                "bedrock-runtime", region_name=self.region_name
            )
        return self._bedrock_client

    def process(
        self,
        answers: List[Dict],
        wafr_schema: Dict,
        session_id: str
    ) -> Dict[str, Any]:
        """
        Score and rank all answers.
        
        Args:
            answers: List of answer dictionaries
            wafr_schema: WAFR schema with best practices
            session_id: Session identifier
            
        Returns:
            Scored and ranked answers
        """
        logger.info(f"[SESSION:{session_id}] ScoringAgent: Scoring {len(answers)} answers")
        
        if not answers:
            return {
                'session_id': session_id,
                'total_answers': 0,
                'scored_answers': [],
                'review_queues': self._organize_review_queues([]),
                'agent': 'scoring'
            }
        
        # Process answers in batches
        def process_answer(answer: Dict) -> Dict:
            question_id = answer.get('question_id')
            question_data = self._get_question_data(question_id, wafr_schema)
            
            if not question_data:
                logger.warning(f"Question data not found for {question_id}")
                return None
            
            # Get detailed question context
            question_context = get_question_context(question_id, self.wafr_schema)
            context_section = ""
            if question_context:
                context_section = f"\n\nWAFR QUESTION CONTEXT:\n{question_context}\n"
            
            best_practices = question_data.get('best_practices', [])
            bp_text = "\n".join([f"  - {bp.get('text', '')}" for bp in best_practices])
            
            hri_indicators = question_data.get('hri_indicators', [])
            hri_text = ""
            if hri_indicators:
                hri_text = f"\n\nHIGH-RISK ISSUE INDICATORS (if present, reduce score):\n" + "\n".join([f"  - {hri}" for hri in hri_indicators])
            
            # Use agent to score answer
            prompt = f"""
Score this WAFR answer using WAFR best practices:

Question ID: {question_id}
Question: {answer.get('question_text', '')}
Answer: {answer.get('answer_content', '')}
Evidence Quotes: {answer.get('evidence_quotes', [])}
Source: {answer.get('source', 'unknown')}
Confidence Score: {answer.get('confidence_score', 0)}
{context_section}

BEST PRACTICES FOR THIS QUESTION:
{bp_text}
{hri_text}

SCORING INSTRUCTIONS:
1. Evaluate CONFIDENCE (40% weight): Evidence quality, verification, reliability. Score 0-100.
2. Evaluate COMPLETENESS (30% weight): How well it addresses the question and best practices. Score 0-100.
3. Evaluate COMPLIANCE (30% weight): Alignment with WAFR best practices, HRI indicators. Score 0-100.
4. Calculate composite_score = confidence_score * 0.4 + completeness_score * 0.3 + compliance_score * 0.3
5. Identify which best practices are met and which are missing.
6. Flag any HRI indicators present in the answer.

You MUST return your response as a single JSON object with EXACTLY these field names:
```json
{{
  "confidence_score": <0-100>,
  "completeness_score": <0-100>,
  "compliance_score": <0-100>,
  "composite_score": <0-100>,
  "grade": "<A|B|C|D|F>",
  "best_practices_met": ["..."],
  "best_practices_missing": ["..."],
  "hri_indicators": ["..."]
}}
```
Return ONLY the JSON object, no other text.
            """
            
            try:
                response = self._call_agent_with_retry(prompt)
                scores = self._parse_scoring(response, answer, question_data)
                return scores
            except Exception as e:
                logger.error(f"Error scoring answer: {str(e)}")
                return self._create_default_scores_for_answer(answer, question_data)
        
        # Process answers in parallel using direct Bedrock API (not Strands agents)
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading

        scored_answers = []
        lock = threading.Lock()
        total_answers = len(answers)
        processed_count = 0

        # Maximum parallel scoring calls
        MAX_PARALLEL_SCORING = 5

        logger.info(f"[SESSION:{session_id}] Starting parallel scoring for {total_answers} answers (max {MAX_PARALLEL_SCORING} concurrent)")

        def score_single_answer(answer: Dict, index: int) -> Optional[Dict]:
            """Score a single answer with error handling."""
            question_id = answer.get('question_id', 'unknown')

            try:
                result = process_answer(answer)
                if result:
                    logger.info(f"[SESSION:{session_id}] Scored answer {index+1}/{total_answers}: {question_id}")
                    return result
                else:
                    logger.warning(f"[SESSION:{session_id}] No result for answer {index+1}: {question_id}")
                    return None

            except Exception as e:
                logger.error(f"[SESSION:{session_id}] Error scoring answer {index+1}: {question_id}: {e}")
                return None

        # Process answers in parallel
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_SCORING) as executor:
            future_to_answer = {
                executor.submit(score_single_answer, answer, i): (i, answer)
                for i, answer in enumerate(answers)
            }

            for future in as_completed(future_to_answer):
                idx, answer = future_to_answer[future]

                with lock:
                    processed_count += 1

                try:
                    result = future.result()
                    if result:
                        with lock:
                            scored_answers.append(result)
                except Exception as e:
                    logger.error(f"[SESSION:{session_id}] Exception in parallel scoring for answer {idx+1}: {e}")

        logger.info(f"[SESSION:{session_id}] Completed parallel scoring: {len(scored_answers)}/{total_answers} answers scored")
        
        # Calculate priorities and organize into queues
        for scored in scored_answers:
            priority = calculate_rank_priority(
                question_id=scored['question_id'],
                grade=scored['grade'],
                hri_indicators=scored.get('hri_indicators', []),
                criticality=scored.get('criticality', 'medium'),
                source=scored.get('source', 'unknown')
            )
            scored['rank_priority'] = priority
        
        # Sort by priority
        scored_answers.sort(key=lambda x: x.get('rank_priority', 100))
        
        # Organize into review queues
        queues = self._organize_review_queues(scored_answers)
        
        # Calculate aggregate scores for frontend consumption
        aggregate_scores = self._calculate_aggregate_scores(scored_answers, wafr_schema)
        
        return {
            'session_id': session_id,
            'total_answers': len(scored_answers),
            'scored_answers': scored_answers,
            'review_queues': queues,
            'scores': aggregate_scores,  # Aggregate scores for frontend
            'agent': 'scoring'
        }
    
    def _calculate_aggregate_scores(self, scored_answers: List[Dict], wafr_schema: Dict) -> Dict:
        """Calculate aggregate scores by pillar and overall."""
        if not scored_answers:
            return {
                'overall_score': 0.0,
                'pillar_scores': {},
                'pillar_coverage': {},
                'grade_distribution': {'A': 0, 'B': 0, 'C': 0, 'D': 0, 'F': 0}
            }
        
        # Group by pillar
        pillar_answers = {}
        for answer in scored_answers:
            question_id = answer.get('question_id', '')
            pillar = self._get_pillar_for_question(question_id, wafr_schema)
            if pillar not in pillar_answers:
                pillar_answers[pillar] = []
            pillar_answers[pillar].append(answer)
        
        # Calculate pillar scores
        pillar_scores = {}
        for pillar, answers in pillar_answers.items():
            if answers:
                avg_composite = sum(a.get('composite_score', 50) for a in answers) / len(answers)
                pillar_scores[pillar] = {
                    'score': round(avg_composite / 100, 2),  # Convert to 0-1 scale
                    'num_answers': len(answers),
                    'avg_composite': round(avg_composite, 1)
                }
        
        # Calculate overall score
        all_composites = [a.get('composite_score', 50) for a in scored_answers]
        overall_score = sum(all_composites) / len(all_composites) / 100 if all_composites else 0.0
        
        # Grade distribution
        grade_dist = {'A': 0, 'B': 0, 'C': 0, 'D': 0, 'F': 0}
        for answer in scored_answers:
            grade = answer.get('grade', 'C')
            if grade in grade_dist:
                grade_dist[grade] += 1
        
        # Pillar coverage (how many questions answered per pillar)
        pillar_coverage = {}
        for pillar, answers in pillar_answers.items():
            pillar_coverage[pillar] = {
                'answered': len(answers),
                'coverage_percentage': round(len(answers) / max(len(scored_answers), 1) * 100, 1)
            }
        
        return {
            'overall_score': round(overall_score, 2),
            'pillar_scores': pillar_scores,
            'pillar_coverage': pillar_coverage,
            'grade_distribution': grade_dist,
            'total_scored': len(scored_answers)
        }
    
    def _get_pillar_for_question(self, question_id: str, wafr_schema: Dict) -> str:
        """Get pillar name for a question ID."""
        if not wafr_schema or 'pillars' not in wafr_schema:
            return 'unknown'
        
        for pillar in wafr_schema['pillars']:
            for question in pillar.get('questions', []):
                if question.get('id') == question_id:
                    return pillar.get('name', pillar.get('id', 'unknown'))
        
        return 'unknown'
    
    @retry_with_backoff(max_retries=3, initial_delay=1.0)
    def _call_agent_with_retry(self, prompt: str) -> Any:
        """Call Bedrock API directly for parallel-safe scoring."""
        # Use direct Bedrock API instead of Strands agent for thread-safety
        try:
            model_id = self.scoring_model_id or "us.anthropic.claude-3-5-haiku-20241022-v1:0"

            response = self.bedrock.invoke_model(
                modelId=model_id,
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 2000,
                    "system": self.system_prompt,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ]
                })
            )

            response_body = json.loads(response['body'].read())
            return response_body['content'][0]['text']

        except Exception as e:
            logger.error(f"Error calling Bedrock API: {e}")
            raise
    
    def _get_question_data(self, question_id: str, wafr_schema: Dict) -> Optional[Dict]:
        """Get question data from schema."""
        if not wafr_schema or 'pillars' not in wafr_schema:
            return None
        
        for pillar in wafr_schema['pillars']:
            for question in pillar.get('questions', []):
                if question.get('id') == question_id:
                    return question
        
        return None
    
    def _parse_scoring(self, response: Any, answer: Dict, question_data: Dict) -> Dict:
        """Parse scoring response from agent with improved JSON extraction."""
        try:
            if isinstance(response, dict):
                scores = response
            elif isinstance(response, str):
                parsed = extract_json_from_text(response, strict=False)
                if parsed and isinstance(parsed, dict):
                    scores = parsed
                else:
                    scores = self._create_default_scores()
            else:
                parsed = extract_json_from_text(str(response), strict=False)
                if parsed and isinstance(parsed, dict):
                    scores = parsed
                else:
                    scores = self._create_default_scores()
        except Exception as e:
            logger.error(f"Error parsing scoring: {str(e)}")
            scores = self._create_default_scores()

        # Normalize field names - Claude may return scores under various keys
        field_aliases = {
            'confidence_score': ['confidence', 'evidence_quality', 'evidence_score'],
            'completeness_score': ['completeness', 'coverage_score', 'coverage'],
            'compliance_score': ['compliance', 'alignment_score', 'alignment'],
            'composite_score': ['composite', 'overall_score', 'total_score', 'final_score', 'weighted_score'],
        }
        for canonical, aliases in field_aliases.items():
            if canonical not in scores:
                for alias in aliases:
                    if alias in scores:
                        val = scores[alias]
                        if isinstance(val, (int, float)):
                            scores[canonical] = float(val)
                            break

        # If we have the three dimension scores but no composite, calculate it
        has_conf = 'confidence_score' in scores and isinstance(scores['confidence_score'], (int, float))
        has_comp = 'completeness_score' in scores and isinstance(scores['completeness_score'], (int, float))
        has_compl = 'compliance_score' in scores and isinstance(scores['compliance_score'], (int, float))

        if has_conf and has_comp and has_compl and 'composite_score' not in scores:
            scores['composite_score'] = (
                float(scores['confidence_score']) * 0.4 +
                float(scores['completeness_score']) * 0.3 +
                float(scores['compliance_score']) * 0.3
            )
            logger.info(f"Calculated composite_score={scores['composite_score']:.1f} from dimensions: "
                       f"conf={scores['confidence_score']}, comp={scores['completeness_score']}, compl={scores['compliance_score']}")

        # Merge with answer data
        scores.update({
            'question_id': answer.get('question_id'),
            'question_text': answer.get('question_text'),
            'pillar': answer.get('pillar'),
            'answer_content': answer.get('answer_content'),
            'evidence_quotes': answer.get('evidence_quotes', []),
            'source': answer.get('source', 'unknown'),
            'criticality': question_data.get('criticality', 'medium')
        })

        # Ensure composite_score exists - use dimension scores if available, else default
        if 'composite_score' not in scores:
            if has_conf or has_comp or has_compl:
                conf = float(scores.get('confidence_score', 50.0))
                comp = float(scores.get('completeness_score', 50.0))
                compl = float(scores.get('compliance_score', 50.0))
                scores['composite_score'] = conf * 0.4 + comp * 0.3 + compl * 0.3
            else:
                scores['composite_score'] = 50.0  # True default when no scoring data
                logger.warning(f"No scoring dimensions found for {answer.get('question_id')}, using default 50.0")

        if 'grade' not in scores:
            # Calculate grade from composite score
            composite = scores.get('composite_score', 50.0)
            if composite >= 90:
                scores['grade'] = 'A'
            elif composite >= 80:
                scores['grade'] = 'B'
            elif composite >= 70:
                scores['grade'] = 'C'
            elif composite >= 60:
                scores['grade'] = 'D'
            else:
                scores['grade'] = 'F'

        return scores
    
    def _create_default_scores_for_answer(self, answer: Dict, question_data: Dict) -> Dict:
        """Create default scores for an answer."""
        scores = self._create_default_scores()
        scores.update({
            'question_id': answer.get('question_id'),
            'question_text': answer.get('question_text'),
            'pillar': answer.get('pillar'),
            'answer_content': answer.get('answer_content'),
            'evidence_quotes': answer.get('evidence_quotes', []),
            'source': answer.get('source', 'unknown'),
            'criticality': question_data.get('criticality', 'medium')
        })
        return scores
    
    def _create_default_scores(self) -> Dict:
        """Create default scoring structure."""
        return {
            'confidence_score': 50.0,
            'completeness_score': 50.0,
            'compliance_score': 50.0,
            'composite_score': 50.0,
            'grade': 'F',
            'best_practices_met': [],
            'best_practices_missing': [],
            'hri_indicators': []
        }
    
    def _organize_review_queues(self, scored_answers: List[Dict]) -> Dict:
        """Organize answers into review queues."""
        critical = [a for a in scored_answers if a['grade'] == 'F' or a.get('hri_indicators')]
        needs_improvement = [a for a in scored_answers if a['grade'] == 'D' and not a.get('hri_indicators')]
        suggested_review = [a for a in scored_answers if a['grade'] == 'C']
        auto_approved = [a for a in scored_answers if a['grade'] in ['A', 'B']]
        
        return {
            'critical_review': critical,
            'needs_improvement': needs_improvement,
            'suggested_review': suggested_review,
            'auto_approved': auto_approved,
            'summary': {
                'total': len(scored_answers),
                'critical': len(critical),
                'with_hri': len([a for a in scored_answers if a.get('hri_indicators')]),
                'auto_approved_pct': round(len(auto_approved) / len(scored_answers) * 100, 1) if scored_answers else 0
            }
        }


def create_scoring_agent(wafr_schema: Optional[Dict] = None) -> ScoringAgent:
    """
    Factory function to create Scoring Agent.
    
    Args:
        wafr_schema: Optional WAFR schema for context
    """
    return ScoringAgent(wafr_schema)

