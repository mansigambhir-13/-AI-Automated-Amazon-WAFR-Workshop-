"""
Well-Architected Tool Agent
Integrates transcript analysis results with WA Tool API to create autonomous WAFR reviews
Uses Claude Sonnet as the brain to answer questions directly from transcript
Optimized with batching, parallel processing, and caching for speed
"""
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import boto3

from wafr.agents.config import BEDROCK_REGION, DEFAULT_MODEL_ID
from wafr.agents.wa_tool_client import WellArchitectedToolClient

logger = logging.getLogger(__name__)


class WAToolAgent:
    """Agent for managing WA Tool operations based on transcript analysis."""
    
    def __init__(self, region: str = None):
        """
        Initialize WA Tool Agent.
        
        Args:
            region: AWS region (default: from config)
        """
        self.region = region or BEDROCK_REGION
        self.wa_client = WellArchitectedToolClient(region=self.region)
        self.bedrock_runtime = boto3.client('bedrock-runtime', region_name=self.region)
        self.model_id = DEFAULT_MODEL_ID
        
        # Cache for question details (key: (workload_id, lens_alias, question_id))
        self._question_cache: Dict[Tuple[str, str, str], Dict] = {}
        
        logger.info(f"WAToolAgent initialized with model: {self.model_id} and question caching enabled")
        
        logger.info(f"WAToolAgent initialized with model: {self.model_id}")
    
    def create_workload_from_transcript(
        self,
        transcript_analysis: Dict,
        client_name: str,
        environment: str = 'PRODUCTION',
        aws_regions: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Create a WA Tool workload from transcript analysis.
        
        Args:
            transcript_analysis: Results from transcript analysis
            client_name: Client/company name
            environment: Environment type
            aws_regions: AWS regions used
            
        Returns:
            Created workload details
        """
        try:
            # Extract insights from transcript analysis
            insights = transcript_analysis.get('insights', [])
            session_id = transcript_analysis.get('session_id', 'unknown')
            
            # Create workload description from insights
            # AWS limit: 250 characters max for description
            client_name_short = client_name[:30] if client_name else "Client"
            session_id_short = session_id[:15] if session_id else "unknown"
            
            # Create concise description (must be <= 250 chars)
            description = f"WAFR review for {client_name_short} (Session: {session_id_short})"
            
            # Add top insight if available (truncate to fit 250 char limit)
            if insights:
                first_insight = insights[0].get('content', '')
                # Calculate remaining space
                remaining = 250 - len(description) - 3  # 3 for ". "
                if remaining > 20 and first_insight:
                    # Truncate insight to fit
                    truncated_insight = first_insight[:remaining]
                    description += f". {truncated_insight}"
            
            # Ensure description doesn't exceed 250 characters
            description = description[:250]
            
            # Sanitize client_name for workload name - AWS allows: letters, numbers, spaces, hyphens, underscores
            # Remove or replace invalid characters
            import re
            sanitized_client_name = re.sub(r'[^a-zA-Z0-9\s_-]', '', client_name)
            # Replace multiple spaces with single space
            sanitized_client_name = re.sub(r'\s+', ' ', sanitized_client_name).strip()
            # Truncate to reasonable length (AWS has 100 char limit for workload name)
            sanitized_client_name = sanitized_client_name[:40]
            
            # Create workload with unique name (include timestamp to avoid conflicts)
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            workload_name = f"{sanitized_client_name}_WAFR_{session_id[:8]}_{timestamp}"
            
            # Ensure workload name doesn't exceed 100 characters (AWS limit)
            workload_name = workload_name[:100]
            
            # Determine lenses to use
            from wafr.agents.lens_manager import LensManager
            lenses_to_use = ['wellarchitected']  # Always include base lens
            if 'lens_context' in transcript_analysis:
                lens_context = transcript_analysis['lens_context']
                if lens_context and lens_context.get('lenses'):
                    # Normalize lens aliases (e.g., generative-ai -> genai)
                    for alias in lens_context['lenses'].keys():
                        if alias != 'wellarchitected':
                            normalized = LensManager.normalize_lens_alias(alias)
                            if normalized not in lenses_to_use:
                                lenses_to_use.append(normalized)
                                if normalized != alias:
                                    logger.info(f"Normalized lens alias: '{alias}' -> '{normalized}'")
            
            # Sanitize tag values - AWS only allows: letters, numbers, spaces, _ . : / = + - @
            # Replace em dash (–) and other invalid characters with regular hyphen
            def sanitize_tag_value(value: str) -> str:
                """Sanitize tag value to meet AWS requirements."""
                if not value:
                    return value
                # Replace em dash, en dash, and other problematic characters with regular hyphen
                value = value.replace('–', '-').replace('—', '-').replace('−', '-')
                # Remove any other characters not in allowed set
                import re
                value = re.sub(r'[^a-zA-Z0-9\s_.:/=+\-@]', '', value)
                return value
            
            workload = self.wa_client.create_workload(
                workload_name=workload_name,
                description=description,
                environment=environment,
                aws_regions=aws_regions or [self.region],
                lenses=lenses_to_use,  # Multi-lens support
                tags={
                    'Source': 'Agentic_WAFR_System',
                    'Client': sanitize_tag_value(client_name),
                    'SessionId': sanitize_tag_value(session_id)
                }
            )
            
            workload_id = workload.get('WorkloadId')
            logger.info(f"Created workload {workload_id} for {client_name}")
            
            # Check lens creation metadata
            metadata = workload.get('_metadata', {})
            recovered_lenses = metadata.get('recovered_via_associate', [])
            final_failed = metadata.get('final_failed_lenses', [])

            if recovered_lenses:
                logger.info(
                    f"Lenses recovered via associate_lenses API: {recovered_lenses}"
                )
            if final_failed:
                logger.warning(
                    f"The following lenses could not be added: {final_failed}. "
                    f"Only accessible lenses will be processed."
                )

            # Get the actual lenses on the workload (prefer all_active_lenses from new metadata)
            actual_lenses = metadata.get('all_active_lenses') or metadata.get('working_lenses', lenses_to_use)
            if not actual_lenses:
                # Fallback: get from workload
                workload_details = self.wa_client.get_workload(workload_id)
                actual_lenses = workload_details.get('Workload', {}).get('Lenses', lenses_to_use)
            
            # Wait for lens reviews to be created (AWS may need a few seconds)
            import time
            logger.info("Waiting for lens reviews to be created...")
            time.sleep(3)  # Initial wait
            
            # Verify lens reviews exist (with retries) - only for actual lenses
            from wafr.agents.lens_manager import LensManager
            verified_lenses = []
            for lens in actual_lenses:
                # Normalize lens alias
                normalized_lens = LensManager.normalize_lens_alias(lens)
                for attempt in range(3):
                    try:
                        lens_review = self.wa_client.get_lens_review(workload_id, normalized_lens)
                        verified_lenses.append(normalized_lens)
                        if normalized_lens != lens:
                            logger.info(f"[OK] Lens review verified for '{lens}' (normalized to '{normalized_lens}')")
                        else:
                            logger.info(f"[OK] Lens review verified for '{normalized_lens}'")
                        break
                    except Exception as e:
                        if attempt < 2:
                            wait_time = 2 ** attempt
                            logger.warning(f"Lens review for '{normalized_lens}' not ready, waiting {wait_time}s...")
                            time.sleep(wait_time)
                        else:
                            logger.warning(
                                f"⚠ Lens review for '{normalized_lens}' not found. "
                                f"Lens may not be available in this account. Error: {str(e)}"
                            )
            
            if verified_lenses != actual_lenses:
                missing = set(actual_lenses) - set(verified_lenses)
                logger.warning(
                    f"Some lenses were not verified: {missing}. "
                    f"Only verified lenses will be processed: {verified_lenses}"
                )
            
            # Store verified lenses in workload response for downstream use
            workload['_verified_lenses'] = verified_lenses
            workload['_skipped_lenses'] = final_failed
            
            return workload
            
        except Exception as e:
            logger.error(f"Error creating workload from transcript: {str(e)}")
            raise
    
    def populate_answers_from_analysis(
        self,
        workload_id: str,
        transcript_analysis: Dict,
        transcript: str,
        lens_alias: str = 'wellarchitected',
        mapping_agent=None,
        lens_context: Optional[Dict] = None,
        verified_lenses: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Populate ALL WA Tool answers from transcript analysis for one or more lenses.
        Uses agents to map transcript context to each WAFR question.
        
        Args:
            workload_id: Workload ID
            transcript_analysis: Transcript analysis results with answers
            transcript: Original transcript text for context
            lens_alias: Lens alias to use
            mapping_agent: Optional mapping agent for question-to-transcript mapping
            verified_lenses: List of verified lenses from workload creation (preferred)
            
        Returns:
            Summary of populated answers
        """
        try:
            # Determine which lenses to process - prefer verified_lenses to avoid processing non-existent lenses
            lenses_to_process = [lens_alias]
            if verified_lenses:
                # Use verified lenses from workload creation (most reliable)
                lenses_to_process = verified_lenses
                logger.info(f"Populating answers for {len(lenses_to_process)} verified lens(es): {', '.join(lenses_to_process)}")
            elif lens_context and lens_context.get('lenses'):
                # Fallback: Process all active lenses from context
                lenses_to_process = list(lens_context['lenses'].keys())
                logger.info(f"Populating answers for {len(lenses_to_process)} lens(es): {', '.join(lenses_to_process)}")
            else:
                logger.info(f"Populating answers for workload {workload_id}, lens {lens_alias}")
            
            # Process each lens
            all_results = {}
            total_updated = 0
            total_failed = 0
            total_skipped = 0
            total_questions = 0
            
            from wafr.agents.lens_manager import LensManager
            
            for current_lens in lenses_to_process:
                # Normalize lens alias before processing
                normalized_lens = LensManager.normalize_lens_alias(current_lens)
                if normalized_lens != current_lens:
                    logger.info(f"Normalized lens alias: '{current_lens}' -> '{normalized_lens}'")
                
                logger.info(f"Processing lens: {normalized_lens}")
                
                # Step 1: Get ALL questions from the lens (with retry logic)
                logger.info(f"Getting all questions from lens {normalized_lens}...")
                all_questions = self._get_all_questions(workload_id, normalized_lens, max_retries=5)
                logger.info(f"Found {len(all_questions)} total questions")
                if len(all_questions) == 0:
                    logger.warning(
                        f"No questions found for lens {current_lens}! "
                        f"This may mean the lens review doesn't exist or the lens isn't available in this account."
                    )
                    all_results[current_lens] = {
                        'updated_answers': 0,
                        'failed_answers': 0,
                        'skipped_answers': 0,
                        'total_questions': 0,
                        'error': 'No questions found in lens review - lens may not be associated with workload or available in account'
                    }
                    continue
                
                # Step 2: Pre-extract key facts from transcript (ONE API call)
                logger.info("Pre-extracting key facts from transcript (optimization)...")
                preprocessed_facts = self._preprocess_transcript(transcript, transcript_analysis)
                
                # Step 3: Group questions by pillar for batching
                questions_by_pillar = self._group_questions_by_pillar(all_questions)
                logger.info(f"Grouped {len(all_questions)} questions into {len(questions_by_pillar)} pillars for batch processing")
                
                # Step 4: Process questions in batches by pillar (parallel processing)
                updated_count = 0
                failed_count = 0
                skipped_count = 0
                
                logger.info(f"Processing {len(questions_by_pillar)} pillars in parallel batches...")
                
                # Process all pillars in parallel (up to 6 for all WA Framework pillars)
                with ThreadPoolExecutor(max_workers=min(6, len(questions_by_pillar))) as executor:
                    future_to_pillar = {}
                    
                    for pillar_id, pillar_questions in questions_by_pillar.items():
                        pillar_name = pillar_questions[0].get('PillarName', pillar_id) if pillar_questions else pillar_id
                        logger.info(f"  Submitting {pillar_name} pillar ({len(pillar_questions)} questions) for batch processing...")
                        
                        future = executor.submit(
                            self._process_pillar_questions_batch,
                            workload_id=workload_id,
                            lens_alias=normalized_lens,  # Use normalized alias
                            pillar_id=pillar_id,
                            pillar_name=pillar_name,
                            questions=pillar_questions,
                            transcript=transcript,
                            preprocessed_facts=preprocessed_facts
                        )
                        future_to_pillar[future] = (pillar_id, pillar_name)
                    
                    # Collect results as they complete
                    for future in as_completed(future_to_pillar):
                        pillar_id, pillar_name = future_to_pillar[future]
                        try:
                            pillar_results = future.result()
                            pillar_updated = pillar_results.get('updated', 0)
                            pillar_failed = pillar_results.get('failed', 0)
                            pillar_skipped = pillar_results.get('skipped', 0)
                            
                            updated_count += pillar_updated
                            failed_count += pillar_failed
                            skipped_count += pillar_skipped
                            
                            logger.info(f"  [OK] {pillar_name}: {pillar_updated} updated, {pillar_failed} failed, {pillar_skipped} skipped")
                        except Exception as e:
                            logger.error(f"  [FAIL] {pillar_name} batch processing failed: {str(e)}")
                            failed_count += len(questions_by_pillar[pillar_id])
                
                # Store results for this lens (use original alias for user-facing results)
                lens_result = {
                    'updated_answers': updated_count,
                    'failed_answers': failed_count,
                    'skipped_answers': skipped_count,
                    'total_questions': len(all_questions)
                }
                all_results[current_lens] = lens_result  # Keep original alias for user
                
                # Validation: Warn if too many questions are being answered (indicates inflated confidence)
                if len(all_questions) > 0:
                    coverage_rate = updated_count / len(all_questions)
                    if coverage_rate > 0.75:
                        logger.warning(
                            f"⚠️  WARNING: {coverage_rate:.0%} coverage for {current_lens} lens - this may indicate "
                            f"inflated confidence scores. Expected coverage: 50-70% for quality answers. "
                            f"Review confidence scores to ensure they reflect actual evidence strength."
                        )
                    elif coverage_rate < 0.3:
                        logger.info(
                            f"[OK] Good: {coverage_rate:.0%} coverage for {current_lens} lens - "
                            f"system is being appropriately selective (quality over quantity)"
                        )
                
                total_updated += updated_count
                total_failed += failed_count
                total_skipped += skipped_count
                total_questions += len(all_questions)
            
            # Return combined results
            return {
                'workload_id': workload_id,
                'updated_answers': total_updated,
                'failed_answers': total_failed,
                'skipped_answers': total_skipped,
                'total_questions': total_questions,
                'per_lens_results': all_results,
                'lenses_processed': lenses_to_process
            }
            
        except Exception as e:
            logger.error(f"Error populating answers: {str(e)}")
            raise
    
    def clear_question_cache(self):
        """Clear the question details cache."""
        cache_size = len(self._question_cache)
        self._question_cache.clear()
        logger.info(f"Question cache cleared ({cache_size} entries removed)")
    
    def _get_all_questions(self, workload_id: str, lens_alias: str, max_retries: int = 2) -> List[Dict]:
        """
        Get all questions for a workload in AWS interface order.
        Returns questions sequentially by pillar and question order (as shown in AWS console).
        
        Args:
            workload_id: Workload ID
            lens_alias: Lens alias
            max_retries: Maximum number of retries if lens review not found (default: 2, reduced from 5 for speed)
        """
        import time
        
        for attempt in range(max_retries):
            try:
                # Get lens review to get pillar IDs in order
                lens_review = self.wa_client.get_lens_review(
                    workload_id=workload_id,
                    lens_alias=lens_alias
                )
                break  # Success, exit retry loop
            except Exception as e:
                error_msg = str(e)
                # Check if it's a "lens review not found" error
                if 'No lens review' in error_msg or 'ValidationException' in error_msg:
                    if attempt < max_retries - 1:
                        wait_time = 1  # Fixed 1 second wait instead of exponential backoff
                        logger.debug(
                            f"Lens review for '{lens_alias}' not found yet. "
                            f"Waiting {wait_time}s before retry (attempt {attempt + 1}/{max_retries})..."
                        )
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.info(
                            f"Lens review for '{lens_alias}' not found after {max_retries} attempts. "
                            f"Skipping this lens (may not be associated with workload)."
                        )
                        return []
                else:
                    # Different error, don't retry
                    logger.error(f"Error getting lens review: {error_msg}")
                    return []
        
        try:
            
            lens_review_data = lens_review.get('LensReview', {})
            pillar_summaries = lens_review_data.get('PillarReviewSummaries', [])
            
            # AWS pillar order: Operational Excellence, Security, Reliability, Performance Efficiency, Cost Optimization, Sustainability
            pillar_order = {
                'operationalExcellence': 1,
                'security': 2,
                'reliability': 3,
                'performance': 4,
                'costOptimization': 5,
                'sustainability': 6
            }
            
            # Sort pillars by AWS order
            sorted_pillars = sorted(
                pillar_summaries,
                key=lambda p: pillar_order.get(p.get('PillarId', '').lower(), 99)
            )
            
            all_questions = []
            # Get questions for each pillar in order
            for pillar in sorted_pillars:
                pillar_id = pillar.get('PillarId')
                pillar_name = pillar.get('PillarName', pillar_id)
                if not pillar_id:
                    continue
                
                try:
                    # List answers for this pillar to get question summaries (in AWS order)
                    answer_summaries = self.wa_client.list_answers(
                        workload_id=workload_id,
                        lens_alias=lens_alias,
                        pillar_id=pillar_id
                    )
                    
                    # AWS returns questions in order, so we maintain that order
                    for answer_summary in answer_summaries:
                        question_summary = {
                            'QuestionId': answer_summary.get('QuestionId'),
                            'PillarId': pillar_id,
                            'PillarName': pillar_name,
                            'QuestionTitle': answer_summary.get('QuestionTitle', ''),
                            'QuestionDescription': answer_summary.get('QuestionDescription', ''),
                            'QuestionNumber': answer_summary.get('QuestionNumber'),  # If available
                            'Risk': answer_summary.get('Risk'),  # Current risk level
                            'IsApplicable': answer_summary.get('IsApplicable', True)
                        }
                        all_questions.append(question_summary)
                    
                    logger.debug(f"  Added {len(answer_summaries)} questions from {pillar_name} pillar")
                        
                except Exception as e:
                    logger.warning(f"Error getting questions for pillar {pillar_id}: {str(e)}")
                    continue
            
            logger.info(f"Extracted {len(all_questions)} questions from {len(sorted_pillars)} pillars in AWS order")
            return all_questions
            
        except Exception as e:
            logger.error(f"Error getting all questions: {str(e)}")
            return []
    
    def _map_question_to_transcript(
        self,
        question: Dict,
        choices: List[Dict],
        transcript: str,
        transcript_analysis: Dict,
        mapping_agent
    ) -> tuple:
        """
        Use mapping agent to determine answer from transcript.
        
        Returns:
            (selected_choices: List[str], notes: str)
        """
        try:
            # Use mapping agent to map question to transcript
            question_id = question.get('QuestionId', '')
            question_title = question.get('QuestionTitle', '')
            question_description = question.get('QuestionDescription', '')
            
            # Format choices for agent
            choices_text = "\n".join([
                f"- {c.get('ChoiceId', '')}: {c.get('Title', '')} - {c.get('Description', '')}"
                for c in choices
            ])
            
            # Create mapping context
            mapping_context = {
                'question_id': question_id,
                'question_title': question_title,
                'question_description': question_description,
                'available_choices': choices_text,
                'transcript': transcript[:5000],  # Limit transcript size
                'transcript_analysis': transcript_analysis
            }
            
            # Use mapping agent to process
            result = mapping_agent.process([mapping_context], 'auto-fill')
            
            # Extract selected choices and notes
            mappings = result.get('mappings', [])
            if mappings:
                mapping = mappings[0]
                selected_choices = mapping.get('selected_choices', [])
                notes = mapping.get('notes', '')
                return (selected_choices, notes)
            
            return ([], '')
            
        except Exception as e:
            logger.warning(f"Error mapping question to transcript: {str(e)}")
            return ([], '')
    
    def _map_answer_to_choices_from_analysis(
        self,
        answer_data: Dict,
        available_choices: List[Dict]
    ) -> List[str]:
        """Map analysis answer to WA Tool choice IDs."""
        selected = []
        
        # Check if answer_data has selected_choices already
        if 'selected_choices' in answer_data:
            return answer_data['selected_choices']
        
        # Try to match based on answer content
        answer_content = answer_data.get('answer_content', '').lower()
        confidence = answer_data.get('confidence_score', 0)
        
        # If high confidence and positive answer, look for "yes" choices
        if confidence > 0.7:
            if any(keyword in answer_content for keyword in ['yes', 'implemented', 'configured', 'enabled', 'have']):
                for choice in available_choices:
                    choice_title = choice.get('Title', '').lower()
                    if any(keyword in choice_title for keyword in ['yes', 'implemented', 'configured']):
                        selected.append(choice.get('ChoiceId'))
        
        # If low confidence or negative, look for "no" or "not implemented" choices
        if not selected:
            if any(keyword in answer_content for keyword in ['no', 'not', 'missing', 'lack', 'none']):
                for choice in available_choices:
                    choice_title = choice.get('Title', '').lower()
                    if any(keyword in choice_title for keyword in ['no', 'not', 'missing']):
                        selected.append(choice.get('ChoiceId'))
        
        return selected
    
    def _get_question_choices(self, lens_info: Dict, question_id: str) -> List[Dict]:
        """Extract available choices for a question from lens info."""
        try:
            pillars = lens_info.get('Lens', {}).get('Pillars', [])
            for pillar in pillars:
                questions = pillar.get('QuestionIds', [])
                if question_id in questions:
                    # Find question details
                    question_details = self._find_question_in_lens(lens_info, question_id)
                    if question_details:
                        return question_details.get('Choices', [])
            return []
        except Exception as e:
            logger.warning(f"Error getting choices for {question_id}: {str(e)}")
            return []
    
    def _find_question_in_lens(self, lens_info: Dict, question_id: str) -> Optional[Dict]:
        """Find question details in lens structure."""
        try:
            # This is a simplified version - actual lens structure may vary
            # You may need to adjust based on actual WA Tool lens format
            lens = lens_info.get('Lens', {})
            # Search through lens structure for question
            # Implementation depends on actual lens JSON structure
            return None
        except Exception as e:
            logger.warning(f"Error finding question in lens: {str(e)}")
            return None
    
    def _map_answer_to_choices(
        self,
        answer_data: Dict,
        available_choices: List[Dict]
    ) -> List[str]:
        """
        Map answer content to WA Tool choice IDs.
        
        This is a simplified mapping - you may need to enhance based on
        actual choice structure and answer content.
        """
        selected = []
        
        # If answer has high confidence, select appropriate choice
        confidence = answer_data.get('confidence_score', 0)
        answer_content = answer_data.get('answer_content', '').lower()
        
        # Simple heuristic: map based on answer content keywords
        # In production, you'd want more sophisticated matching
        for choice in available_choices:
            choice_id = choice.get('ChoiceId', '')
            choice_title = choice.get('Title', '').lower()
            
            # Match based on keywords (simplified)
            if any(keyword in answer_content for keyword in ['yes', 'implemented', 'configured', 'enabled']):
                if 'yes' in choice_title or 'implemented' in choice_title:
                    selected.append(choice_id)
            elif any(keyword in answer_content for keyword in ['no', 'not', 'missing', 'lack']):
                if 'no' in choice_title or 'not' in choice_title:
                    selected.append(choice_id)
        
        # If no matches, select first choice as default (you may want to handle differently)
        if not selected and available_choices:
            selected.append(available_choices[0].get('ChoiceId'))
        
        return selected
    
    def _prepare_answer_notes(self, answer_data: Dict) -> str:
        """Prepare notes for WA Tool answer from answer data."""
        notes = []
        
        answer_content = answer_data.get('answer_content', '')
        if answer_content:
            notes.append(f"Answer: {answer_content}")
        
        evidence_quotes = answer_data.get('evidence_quotes', [])
        if evidence_quotes:
            notes.append("\nEvidence from transcript:")
            for quote in evidence_quotes[:3]:  # Limit to 3 quotes
                notes.append(f"- {quote}")
        
        confidence = answer_data.get('confidence_score', 0)
        if confidence:
            notes.append(f"\nConfidence: {confidence:.0%}")
        
        return "\n".join(notes)
    
    def _preprocess_transcript(
        self,
        transcript: str,
        transcript_analysis: Dict
    ) -> Dict:
        """
        Pre-extract key facts from transcript (ONE API call).
        This reduces context size for subsequent question-answering calls.
        
        Args:
            transcript: Full transcript text
            transcript_analysis: Transcript analysis results
            
        Returns:
            Dictionary of preprocessed facts by category
        """
        try:
            insights = transcript_analysis.get('insights', [])
            mappings = transcript_analysis.get('mappings', [])
            
            # Build summary context
            insights_summary = "\n".join([
                f"- {insight.get('content', '')[:200]}"
                for insight in insights[:15]
            ])
            
            prompt = f"""Extract structured facts from this transcript for AWS Well-Architected Framework review.

TRANSCRIPT:
{transcript[:5000]}

KEY INSIGHTS:
{insights_summary}

Extract and organize facts into these categories:
- operational_practices: Operational procedures, monitoring, automation
- security_measures: Identity, permissions, data protection, compliance
- reliability_patterns: Fault tolerance, backups, disaster recovery, scaling
- performance_optimizations: Resource selection, efficiency, optimization
- cost_management: Cost tracking, optimization, budgeting
- sustainability_efforts: Resource efficiency, environmental considerations

Return ONLY a JSON object:
{{
  "operational_practices": ["fact 1", "fact 2", ...],
  "security_measures": ["fact 1", "fact 2", ...],
  "reliability_patterns": ["fact 1", "fact 2", ...],
  "performance_optimizations": ["fact 1", "fact 2", ...],
  "cost_management": ["fact 1", "fact 2", ...],
  "sustainability_efforts": ["fact 1", "fact 2", ...]
}}

Return ONLY the JSON, no other text."""

            response = self.bedrock_runtime.invoke_model(
                modelId=self.model_id,
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 2000,
                    "temperature": 0.1,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ]
                }),
                contentType="application/json",
                accept="application/json"
            )
            
            response_body = json.loads(response['body'].read())
            content = response_body.get('content', [])
            if content:
                text = content[0].get('text', '')
                json_match = re.search(r'\{[^{}]*"operational_practices"[^{}]*\}', text, re.DOTALL)
                if json_match:
                    facts = json.loads(json_match.group())
                    logger.info(f"Pre-extracted facts: {sum(len(v) for v in facts.values())} total facts")
                    return facts
            
            # Fallback: return empty structure
            return {
                "operational_practices": [],
                "security_measures": [],
                "reliability_patterns": [],
                "performance_optimizations": [],
                "cost_management": [],
                "sustainability_efforts": []
            }
            
        except Exception as e:
            logger.warning(f"Error preprocessing transcript: {str(e)}")
            return {
                "operational_practices": [],
                "security_measures": [],
                "reliability_patterns": [],
                "performance_optimizations": [],
                "cost_management": [],
                "sustainability_efforts": []
            }
    
    def _group_questions_by_pillar(self, all_questions: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Group questions by pillar for batch processing.
        
        Args:
            all_questions: List of all questions
            
        Returns:
            Dictionary mapping pillar_id to list of questions
        """
        questions_by_pillar = {}
        for question in all_questions:
            pillar_id = question.get('PillarId', 'unknown')
            if pillar_id not in questions_by_pillar:
                questions_by_pillar[pillar_id] = []
            questions_by_pillar[pillar_id].append(question)
        return questions_by_pillar
    
    def _process_pillar_questions_batch(
        self,
        workload_id: str,
        lens_alias: str,
        pillar_id: str,
        pillar_name: str,
        questions: List[Dict],
        transcript: str,
        preprocessed_facts: Dict
    ) -> Dict[str, int]:
        """
        Process all questions for a pillar in ONE batch API call.
        Optimized to fetch question details in parallel.
        
        Args:
            workload_id: Workload ID
            lens_alias: Lens alias
            pillar_id: Pillar ID
            pillar_name: Pillar name
            questions: List of questions for this pillar
            transcript: Full transcript
            preprocessed_facts: Pre-extracted facts
            
        Returns:
            Dict with updated, failed, skipped counts
        """
        updated_count = 0
        failed_count = 0
        skipped_count = 0
        
        try:
            # OPTIMIZATION: Fetch question details in parallel
            question_data = []
            
            def fetch_question_details(question_summary):
                """Fetch question details for a single question"""
                question_id = question_summary.get('QuestionId')
                if not question_id:
                    return None
                
                try:
                    question_details = self.wa_client.get_answer(
                        workload_id=workload_id,
                        lens_alias=lens_alias,
                        question_id=question_id
                    )
                    
                    answer_data = question_details.get('Answer', {})
                    question = question_details.get('Question', {})
                    choices = answer_data.get('Choices', [])
                    
                    return {
                        'question_id': question_id,
                        'question': question,
                        'choices': choices,
                        'pillar_name': pillar_name
                    }
                except Exception as e:
                    logger.warning(f"Failed to get question {question_id}: {str(e)}")
                    return None
            
            # Fetch all question details in parallel (increased to 15 workers for faster processing)
            with ThreadPoolExecutor(max_workers=15) as executor:
                futures = {executor.submit(fetch_question_details, q): q for q in questions}
                for future in as_completed(futures):
                    result = future.result()
                    if result:
                        question_data.append(result)
                    else:
                        failed_count += 1
            
            if not question_data:
                return {'updated': 0, 'failed': failed_count, 'skipped': len(questions)}
            
            # Use smart batching: split large pillar groups into optimal batches (10-20 per call)
            from wafr.agents.batch_optimizer import smart_group_questions
            
            # Determine if we should use smart batching (for sets > 15 questions)
            if len(question_data) > 15:
                # Prepare questions in format for smart grouping
                questions_for_grouping = [
                    {"question": q_item["question"], "pillar": pillar_name, **q_item}
                    for q_item in question_data
                ]
                
                # Smart group into optimal batch sizes (10-20 per batch)
                smart_batches = smart_group_questions(questions_for_grouping)
                logger.info(f"  Smart grouped {len(question_data)} questions into {len(smart_batches)} optimized batches for {pillar_name}")
                
                all_batch_answers = []
                for batch_idx, batch in enumerate(smart_batches):
                    # Extract original question_data format
                    batch_question_data = [
                        {k: v for k, v in q.items() if k != "pillar"}
                        for q in batch
                    ]
                    
                    logger.info(f"    Processing batch {batch_idx + 1}/{len(smart_batches)} ({len(batch_question_data)} questions)")
                    batch_result = self._answer_questions_batch(
                        questions=batch_question_data,
                        transcript=transcript,
                        preprocessed_facts=preprocessed_facts,
                        pillar_id=pillar_id,
                        pillar_name=pillar_name,
                    )
                    if batch_result:
                        all_batch_answers.extend(batch_result)
                
                batch_answers = all_batch_answers
            else:
                # Single batch processing for small sets (<= 15 questions)
                logger.info(f"  Batch processing {len(question_data)} questions for {pillar_name}...")
                batch_answers = self._answer_questions_batch(
                    questions=question_data,
                    transcript=transcript,
                    preprocessed_facts=preprocessed_facts,
                    pillar_id=pillar_id,
                    pillar_name=pillar_name
                )
            
            # Update answers in WA Tool
            for question_item, answer_result in zip(question_data, batch_answers):
                question_id = question_item['question_id']
                selected_choices = answer_result.get('selected_choice_ids', [])
                notes = answer_result.get('notes', '')
                
                # Accept answers with confidence >= 0.7 for quality over quantity (STRICT)
                confidence = answer_result.get('confidence', 0.0)
                reasoning_type = answer_result.get('reasoning_type', 'unknown')
                
                if selected_choices and confidence >= 0.7:
                    try:
                        # Enhance notes with reasoning type for transparency
                        enhanced_notes = notes or ''
                        if reasoning_type and reasoning_type != 'unknown':
                            enhanced_notes += f"\n\n[Reasoning: {reasoning_type}, Confidence: {confidence:.0%}]"
                        
                        self.wa_client.update_answer(
                            workload_id=workload_id,
                            lens_alias=lens_alias,
                            question_id=question_id,
                            selected_choices=selected_choices,
                            notes=enhanced_notes or '',
                            is_applicable=True
                        )
                        updated_count += 1
                        logger.debug(f"    [OK] Updated {question_id} (confidence: {confidence:.0%}, reasoning: {reasoning_type})")
                    except Exception as e:
                        logger.warning(f"    [FAIL] Failed to update {question_id}: {str(e)}")
                        failed_count += 1
                elif selected_choices and confidence < 0.7:
                    # Log but don't update - confidence too low (STRICT threshold)
                    skipped_count += 1
                    logger.debug(f"    ⊘ Skipped {question_id} - confidence too low ({confidence:.0%} < 0.7)")
                else:
                    skipped_count += 1
                    logger.debug(f"    [SKIP] Skipped {question_id} - no answer")
            
            return {'updated': updated_count, 'failed': failed_count, 'skipped': skipped_count}
            
        except Exception as e:
            logger.error(f"Error processing {pillar_name} pillar batch: {str(e)}")
            return {'updated': updated_count, 'failed': failed_count + len(questions), 'skipped': skipped_count}
    
    def _answer_questions_batch(
        self,
        questions: List[Dict],
        transcript: str,
        preprocessed_facts: Dict,
        pillar_id: str,
        pillar_name: str
    ) -> List[Dict]:
        """
        Answer multiple questions in ONE API call (batching optimization).
        
        Args:
            questions: List of question dicts with question, choices
            transcript: Full transcript
            preprocessed_facts: Pre-extracted facts
            pillar_id: Pillar ID
            pillar_name: Pillar name
            
        Returns:
            List of answer dicts with selected_choice_ids and notes
        """
        try:
            # Format all questions
            questions_text = []
            for i, q_item in enumerate(questions, 1):
                question = q_item['question']
                choices = q_item['choices']
                question_id = q_item['question_id']
                
                choices_text = "\n".join([
                    f"  - {c.get('ChoiceId', '')}: {c.get('Title', '')}"
                    for c in choices
                ])
                
                questions_text.append(f"""
Question {i} (ID: {question_id}):
Title: {question.get('QuestionTitle', '')}
Description: {question.get('QuestionDescription', '')[:300]}
Available Choices:
{choices_text}
""")
            
            # Get relevant facts for this pillar
            pillar_facts_map = {
                'operationalExcellence': 'operational_practices',
                'security': 'security_measures',
                'reliability': 'reliability_patterns',
                'performance': 'performance_optimizations',
                'costOptimization': 'cost_management',
                'sustainability': 'sustainability_efforts'
            }
            
            relevant_facts_key = pillar_facts_map.get(pillar_id.lower(), 'operational_practices')
            relevant_facts = preprocessed_facts.get(relevant_facts_key, [])
            
            facts_text = "\n".join([f"- {fact}" for fact in relevant_facts[:20]]) if relevant_facts else "No specific facts extracted for this pillar."
            
            prompt = f"""You are an AWS Well-Architected Framework expert analyzing a client transcript. Your goal is to answer as MANY questions as possible using Claude's reasoning + transcript context.

PILLAR: {pillar_name}

RELEVANT FACTS FROM TRANSCRIPT:
{facts_text}

TRANSCRIPT EXCERPT:
{transcript[:4000]}

QUESTIONS TO ANSWER:
{''.join(questions_text)}

CRITICAL CHOICE SELECTION STRATEGY (BE HONEST):
1. ANALYZE CHOICES: For each question, identify which choices indicate GOOD PRACTICES (positive) vs PROBLEMS/RISKS (negative)
   - POSITIVE choices: "Yes", "Implemented", "Configured", "Enabled", "Using", "Established", "Active", "Available"
   - NEGATIVE choices: "No", "Not", "Missing", "None", "High Risk", "Not Implemented", "Absent", "Disabled"
   
2. MATCH TO TRANSCRIPT (REFLECT REALITY):
   - If transcript shows GOOD PRACTICES → Select POSITIVE choices (indicates compliance, good architecture)
   - If transcript shows PROBLEMS/ISSUES → Select NEGATIVE choices (indicates gaps, risks) - DO NOT hide problems!
   - If transcript is UNCLEAR/NEUTRAL → Use optimistic default (positive) ONLY when truly no evidence either way
   
3. HONESTY PRINCIPLE:
   - Reflect what the transcript ACTUALLY shows - don't artificially reduce HRIs
   - If transcript mentions problems, gaps, or missing implementations → Select NEGATIVE choices
   - Only use optimistic defaults when transcript is truly neutral/empty with no evidence
   - HRIs are valid and should be reported if they exist in the transcript

TASK: Analyze the transcript and facts above, then answer questions when you have reasonable evidence or can make reasonable inferences.

CRITICAL: DO NOT FORCE ANSWERS. Skipping questions is EXPECTED and GOOD.

ANSWER STRATEGY FOR EACH QUESTION (STRICT):
1. Direct Evidence ONLY (confidence 0.8-1.0): Explicit, clear statements in transcript that directly address the question
   - MUST have verbatim quotes or clear evidence
   - If no direct evidence → SKIP (do not answer)
   
2. Strong Indirect Inference (confidence 0.7-0.85): Related information + strong logical reasoning
   - MUST have clear related information in transcript
   - MUST be able to explain the logical connection
   - If connection is weak → SKIP (do not answer)
   
3. DO NOT use "best practice inference" or "domain knowledge" to fill gaps
   - This leads to hallucinations and incorrect answers
   - If transcript doesn't provide enough context → SKIP

STRICT RULES:
- ONLY answer if you have STRONG evidence (confidence >= 0.7)
- If transcript is vague, unclear, or has no relevant information → SKIP
- DO NOT guess or infer from general AWS knowledge
- DO NOT force answers to reach coverage targets
- It's EXPECTED that 30-50% of questions will be skipped (this is GOOD)
- Quality over quantity: Better to skip than to answer incorrectly

For EACH question:
1. FIRST: Search for direct evidence in transcript/facts
2. IF no direct evidence → SKIP (do not proceed to inference)
3. IF direct evidence exists → Answer with confidence 0.8-1.0
4. IF strong indirect evidence exists → Answer with confidence 0.7-0.85
5. IF weak or no evidence → SKIP (return empty selected_choice_ids)
6. CRITICAL: When selecting choices, reflect what transcript actually shows - don't hide problems

CRITICAL JSON FORMAT REQUIREMENTS:
- Return ONLY a valid JSON array
- Start your response with [ and end with ]
- No markdown code blocks (no ```json or ```)
- No explanations before or after the JSON
- No text outside the JSON array
- Ensure all strings are properly escaped
- Ensure all commas are present between array elements

Return ONLY this JSON array format:
[
  {{
    "question_id": "question_id_1",
    "selected_choice_ids": ["choice_id_1", "choice_id_2"],
    "notes": "Explanation with evidence quotes",
    "confidence": 0.85
  }},
  {{
    "question_id": "question_id_2",
    "selected_choice_ids": ["choice_id_3"],
    "notes": "Explanation with evidence quotes",
    "confidence": 0.75
  }}
]

REQUIREMENTS (STRICT):
- ONLY return answers for questions with STRONG evidence (confidence >= 0.7)
- DO NOT force answers - it's EXPECTED that many questions will be skipped
- Include question_id for each answer (must match exactly)
- Answer ONLY with direct evidence or strong indirect inference
- Minimum confidence threshold: 0.7 (STRICT - do not lower this)
- MUST include specific quotes from transcript in notes when available
- When using inference, MUST explain the logical connection clearly
- It's EXPECTED and GOOD to skip 30-50% of questions if evidence is insufficient
- All JSON must be valid and parseable
- Be HONEST in choice selection - reflect what transcript actually shows
- If you answer more than 70% of questions, you're likely being too aggressive - review your confidence scores

Your response must start with [ and end with ]. No other text."""

            response = self.bedrock_runtime.invoke_model(
                modelId=self.model_id,
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 4000,
                    "temperature": 0.2,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ]
                }),
                contentType="application/json",
                accept="application/json"
            )
            
            response_body = json.loads(response['body'].read())
            content = response_body.get('content', [])
            if content:
                text = content[0].get('text', '')
                
                # Robust JSON parsing with multiple fallback strategies
                answers = self._parse_claude_json_response(text)
                
                if answers and isinstance(answers, list) and len(answers) > 0:
                    logger.info(f"    Batch answered {len(answers)}/{len(questions)} questions for {pillar_name}")
                    
                    # Ensure we have answers for all questions
                    answer_map = {a.get('question_id'): a for a in answers if a.get('question_id')}
                    result = []
                    unanswered_questions = []
                    
                    for q_item in questions:
                        question_id = q_item['question_id']
                        if question_id in answer_map:
                            answer = answer_map[question_id]
                            selected_ids = answer.get('selected_choice_ids', [])
                            confidence = answer.get('confidence', 0.0)
                            
                            # If answer has low confidence or is empty, try to improve it (STRICT threshold)
                            if not selected_ids or confidence < 0.7:
                                # Store for second pass
                                unanswered_questions.append((q_item, answer))
                            
                            result.append({
                                'question_id': question_id,
                                'selected_choice_ids': selected_ids,
                                'notes': answer.get('notes', ''),
                                'confidence': confidence,
                                'reasoning_type': answer.get('reasoning_type', 'unknown')
                            })
                        else:
                            # No answer at all - store for second pass
                            unanswered_questions.append((q_item, None))
                            result.append({
                                'question_id': question_id,
                                'selected_choice_ids': [],
                                'notes': '',
                                'confidence': 0.0,
                                'reasoning_type': 'none'
                            })
                    
                    # SECOND PASS: Try to answer unanswered questions with more aggressive approach
                    if unanswered_questions and len(unanswered_questions) > 0:
                        logger.info(f"    Second pass: Attempting to answer {len(unanswered_questions)} unanswered questions with aggressive inference...")
                        second_pass_answers = self._answer_unanswered_questions_aggressive(
                            unanswered_questions,
                            transcript,
                            preprocessed_facts,
                            pillar_name
                        )
                        
                        # Update results with second pass answers
                        for second_answer in second_pass_answers:
                            question_id = second_answer.get('question_id')
                            for i, res in enumerate(result):
                                if res['question_id'] == question_id:
                                    # Only update if we got a better answer
                                    if second_answer.get('selected_choice_ids') and len(second_answer.get('selected_choice_ids', [])) > 0:
                                        result[i] = {
                                            'question_id': question_id,
                                            'selected_choice_ids': second_answer.get('selected_choice_ids', []),
                                            'notes': second_answer.get('notes', ''),
                                            'confidence': second_answer.get('confidence', 0.6),
                                            'reasoning_type': 'aggressive_inference'
                                        }
                                        logger.debug(f"      Second pass answered: {question_id}")
                                    break
                    
                    return result
                else:
                    logger.warning(f"    Could not parse batch answers for {pillar_name}")
                    logger.debug(f"    Response preview: {text[:500]}")
            
            # Fallback: Try individual question answering for any remaining questions
            logger.warning(f"    Batch processing failed for {pillar_name}, trying individual questions...")
            result = []
            for q_item in questions:
                try:
                    # Try individual question with aggressive approach
                    question = q_item['question']
                    choices = q_item['choices']
                    question_id = q_item['question_id']
                    
                    # Use full transcript context for individual questions
                    transcript_context = f"{transcript[:5000]}\n\nRelevant Facts:\n{preprocessed_facts.get('operational_practices', [])[:10]}"
                    
                    selected_ids, notes = self._answer_question_with_claude_sonnet(
                        question=question,
                        choices=choices,
                        transcript=transcript,
                        transcript_context=transcript_context,
                        pillar_id=pillar_id,
                        pillar_name=pillar_name
                    )
                    
                    result.append({
                        'question_id': question_id,
                        'selected_choice_ids': selected_ids,
                        'notes': notes,
                        'confidence': 0.5 if selected_ids else 0.0,
                        'reasoning_type': 'individual_fallback'
                    })
                except Exception as e:
                    logger.warning(f"    Individual question {q_item.get('question_id', 'unknown')} failed: {str(e)}")
                    result.append({
                        'question_id': q_item['question_id'],
                        'selected_choice_ids': [],
                        'notes': '',
                        'confidence': 0.0,
                        'reasoning_type': 'failed'
                    })
            
            return result
            
        except Exception as e:
            logger.warning(f"Error in batch answer: {str(e)}")
            return [
                {
                    'question_id': q_item['question_id'],
                    'selected_choice_ids': [],
                    'notes': '',
                    'confidence': 0.0
                }
                for q_item in questions
            ]
    
    def _answer_unanswered_questions_aggressive(
        self,
        unanswered_questions: List[tuple],
        transcript: str,
        preprocessed_facts: Dict,
        pillar_name: str
    ) -> List[Dict]:
        """
        Second pass: Aggressively try to answer questions that were skipped.
        Uses more aggressive inference and best practices.
        
        Args:
            unanswered_questions: List of (question_item, previous_answer) tuples
            transcript: Full transcript
            preprocessed_facts: Pre-extracted facts
            pillar_name: Pillar name
            
        Returns:
            List of answer dicts
        """
        if not unanswered_questions:
            return []
        
        try:
            # Build aggressive prompt for unanswered questions
            questions_text = []
            for q_item, prev_answer in unanswered_questions:
                question = q_item['question']
                choices = q_item['choices']
                question_id = q_item['question_id']
                
                choices_text = "\n".join([
                    f"  - {c.get('ChoiceId', '')}: {c.get('Title', '')}"
                    for c in choices
                ])
                
                questions_text.append(f"""
Question ID: {question_id}
Title: {question.get('QuestionTitle', '')}
Description: {question.get('QuestionDescription', '')[:200]}
Choices:
{choices_text}
""")
            
            # Get all relevant facts
            all_facts = []
            for key, facts_list in preprocessed_facts.items():
                all_facts.extend(facts_list[:10])
            
            facts_text = "\n".join([f"- {fact}" for fact in all_facts[:30]])
            
            prompt = f"""You are an AWS Well-Architected Framework expert. These questions were NOT answered in the first pass. Answer them if you have reasonable evidence or can make reasonable inferences.

PILLAR: {pillar_name}

TRANSCRIPT EXCERPT:
{transcript[:5000]}

RELEVANT FACTS:
{facts_text}

UNANSWERED QUESTIONS:
{''.join(questions_text)}

CRITICAL CHOICE SELECTION STRATEGY (BE HONEST):
1. ANALYZE CHOICES: For each question, identify which choices indicate GOOD PRACTICES (positive) vs PROBLEMS/RISKS (negative)
   - POSITIVE choices: "Yes", "Implemented", "Configured", "Enabled", "Using", "Established", "Active"
   - NEGATIVE choices: "No", "Not", "Missing", "None", "High Risk", "Not Implemented", "Absent"
   
2. MATCH TO TRANSCRIPT (REFLECT REALITY):
   - If transcript shows GOOD PRACTICES → Select POSITIVE choices
   - If transcript shows PROBLEMS → Select NEGATIVE choices - DO NOT hide problems!
   - If UNCLEAR → Use optimistic default (positive) ONLY when truly no evidence either way
   
3. HONESTY PRINCIPLE:
   - Reflect what the transcript ACTUALLY shows - don't artificially reduce HRIs
   - If transcript mentions problems, gaps, or missing implementations → Select NEGATIVE choices
   - Only use optimistic defaults when transcript is truly neutral/empty with no evidence
   - HRIs are valid and should be reported if they exist in the transcript

CRITICAL: DO NOT FORCE ANSWERS. These questions were skipped in the first pass for good reasons.

TASK: Review these {len(unanswered_questions)} questions. Most should remain UNANSWERED.

STRICT RULES:
1. ONLY answer if you find STRONG evidence that was missed in first pass
2. DO NOT use "best practices" or "domain knowledge" to force answers
3. DO NOT infer from general AWS patterns
4. Minimum confidence: 0.7 (STRICT - same as first pass)
5. EXPECT that 80-90% of these will remain unanswered

STRATEGY:
- Look for STRONG evidence that was missed
- If no strong evidence → SKIP (do not answer)
- DO NOT apply AWS best practices to fill gaps
- DO NOT use domain knowledge about typical implementations
- It's EXPECTED and GOOD to skip most of these questions
- When selecting choices: Be HONEST - reflect what transcript actually shows

Return ONLY a JSON array:
[
  {{
    "question_id": "question_id_1",
    "selected_choice_ids": ["choice_id"],
    "notes": "Answer based on STRONG evidence found: [explain reasoning]. State why you selected positive vs negative choices.",
    "confidence": 0.75,
    "reasoning_type": "strong_evidence"
  }}
]

CRITICAL: 
- ONLY answer questions where you have STRONG evidence (confidence >= 0.7)
- It's EXPECTED that most questions will remain unanswered
- DO NOT force answers - better to skip than to hallucinate
- Be HONEST in choice selection - reflect what transcript actually shows
- Don't hide problems - if transcript shows issues, select NEGATIVE choices"""

            response = self.bedrock_runtime.invoke_model(
                modelId=self.model_id,
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 3000,
                    "temperature": 0.3,  # Slightly higher for more creative inference
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ]
                }),
                contentType="application/json",
                accept="application/json"
            )
            
            response_body = json.loads(response['body'].read())
            content = response_body.get('content', [])
            if content:
                text = content[0].get('text', '')
                answers = self._parse_claude_json_response(text)
                
                if answers and isinstance(answers, list):
                    logger.info(f"    Second pass answered {len(answers)}/{len(unanswered_questions)} questions")
                    return answers
            
            return []
            
        except Exception as e:
            logger.warning(f"Error in aggressive second pass: {str(e)}")
            return []
    
    def _parse_claude_json_response(self, text: str) -> Optional[List[Dict]]:
        """
        Robust JSON parsing with multiple fallback strategies.
        Handles malformed JSON, markdown code blocks, and mixed text.
        """
        if not text:
            return None
        
        # Strategy 1: Try to find and parse JSON array directly
        try:
            # Remove markdown code blocks if present
            cleaned = re.sub(r'```json\s*', '', text)
            cleaned = re.sub(r'```\s*', '', cleaned)
            cleaned = cleaned.strip()
            
            # Try direct parse
            if cleaned.startswith('[') and cleaned.endswith(']'):
                return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
        
        # Strategy 2: Find JSON array using bracket matching
        try:
            start_idx = text.find('[')
            if start_idx != -1:
                bracket_count = 0
                end_idx = start_idx
                for i in range(start_idx, len(text)):
                    if text[i] == '[':
                        bracket_count += 1
                    elif text[i] == ']':
                        bracket_count -= 1
                        if bracket_count == 0:
                            end_idx = i + 1
                            break
                
                if end_idx > start_idx:
                    json_str = text[start_idx:end_idx]
                    # Clean common JSON issues
                    json_str = self._fix_json_common_issues(json_str)
                    return json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            pass
        
        # Strategy 3: Use regex to extract JSON array
        try:
            # Pattern to match JSON array
            pattern = r'\[\s*(?:\{[^}]*\}(?:\s*,\s*\{[^}]*\})*)?\s*\]'
            json_match = re.search(pattern, text, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                json_str = self._fix_json_common_issues(json_str)
                return json.loads(json_str)
        except json.JSONDecodeError:
            pass
        
        # Strategy 4: Try to extract individual JSON objects and combine
        try:
            # Find all JSON objects
            objects = re.findall(r'\{[^{}]*"question_id"[^{}]*\}', text, re.DOTALL)
            if objects:
                fixed_objects = []
                for obj_str in objects:
                    try:
                        obj_str = self._fix_json_common_issues(obj_str)
                        obj = json.loads(obj_str)
                        fixed_objects.append(obj)
                    except json.JSONDecodeError:
                        continue
                
                if fixed_objects:
                    return fixed_objects
        except (json.JSONDecodeError, ValueError, AttributeError) as e:
            logger.debug(f"JSON parsing strategy failed: {e}")
            # Continue to next strategy
        
        logger.warning(f"All JSON parsing strategies failed. Text preview: {text[:200]}")
        return None
    
    def _fix_json_common_issues(self, json_str: str) -> str:
        """Fix common JSON formatting issues."""
        # Remove trailing commas before ] or }
        json_str = re.sub(r',\s*]', ']', json_str)
        json_str = re.sub(r',\s*}', '}', json_str)
        
        # Fix unescaped quotes in strings (basic)
        # This is tricky, so we'll be conservative
        json_str = json_str.strip()
        
        # Remove any control characters that might break JSON
        json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', json_str)
        
        return json_str
    
    def _answer_question_with_claude_sonnet(
        self,
        question: Dict,
        choices: List[Dict],
        transcript: str,
        transcript_context: str,
        pillar_id: str = None,
        pillar_name: str = None
    ) -> tuple[List[str], str]:
        """
        Use Claude Sonnet to directly answer question from transcript.
        Claude Sonnet acts as the brain to analyze and answer.
        
        Args:
            question: Question dict with QuestionTitle, QuestionDescription
            choices: Available choices
            transcript: Full transcript text
            transcript_context: Formatted context
            pillar_id: Pillar ID
            pillar_name: Pillar name
            
        Returns:
            (selected_choice_ids, notes)
        """
        from wafr.agents.cost_optimizer import ResponseCache, hash_question_context, hash_transcript_segment
        
        try:
            question_title = question.get('QuestionTitle', '')
            question_desc = question.get('QuestionDescription', '')
            question_id = question.get('QuestionId', '')
            
            # Format choices (limit description length for efficiency)
            choices_text = "\n".join([
                f"{i+1}. ID: {c.get('ChoiceId', '')}\n   Title: {c.get('Title', '')}\n   Description: {c.get('Description', '')[:100]}"
                for i, c in enumerate(choices)
            ])
            
            # Analyze choices to identify positive vs negative indicators
            positive_keywords = ['yes', 'implemented', 'configured', 'enabled', 'have', 'using', 'established', 'active', 'available', 'deployed']
            negative_keywords = ['no', 'not', 'missing', 'none', 'lack', 'absent', 'disabled', 'unavailable', 'high', 'risk']
            
            prompt = f"""You are an AWS Well-Architected Framework expert analyzing a client transcript to answer questions. Your goal is to answer as many questions as possible using Claude's reasoning combined with transcript context.

PILLAR: {pillar_name or pillar_id or 'Unknown'}

QUESTION:
{question_title}

{question_desc}

AVAILABLE CHOICES:
{choices_text}

TRANSCRIPT CONTEXT:
{transcript_context}

CRITICAL CHOICE SELECTION STRATEGY:
1. ANALYZE CHOICES FIRST: Identify which choices indicate GOOD PRACTICES (positive) vs PROBLEMS/RISKS (negative)
   - POSITIVE choices: Usually contain words like "Yes", "Implemented", "Configured", "Enabled", "Using", "Established"
   - NEGATIVE choices: Usually contain words like "No", "Not", "Missing", "None", "High Risk", "Not Implemented"
   
2. MATCH TRANSCRIPT TO CHOICES (BE HONEST):
   - If transcript shows GOOD PRACTICES → Select POSITIVE choices (indicates compliance, good architecture)
   - If transcript shows PROBLEMS/ISSUES → Select NEGATIVE choices (indicates gaps, risks) - DO NOT hide problems!
   - If transcript is UNCLEAR/NEUTRAL → Use optimistic default (prefer positive choices) ONLY when truly no evidence
   
3. HONESTY PRINCIPLE:
   - Reflect what the transcript ACTUALLY shows - don't artificially reduce HRIs
   - If transcript mentions problems, gaps, or missing implementations → Select NEGATIVE choices
   - Only use optimistic defaults when transcript is truly neutral/empty with no evidence either way
   - HRIs are valid and should be reported if they exist in the transcript

TASK: Analyze the transcript context and use your AWS expertise to determine the best answer. Answer questions when you have reasonable evidence or can make reasonable inferences.

INSTRUCTIONS:
1. FIRST: Look for direct evidence in transcript that explicitly addresses this question
2. SECOND: If no direct evidence, look for related information and use logical inference
3. THIRD: If still unclear, use transcript context + AWS best practices + your domain knowledge to make an educated answer
4. ONLY answer if you have reasonable confidence (>= 0.6) or can make a reasonable inference
5. It's OKAY to leave questions unanswered if there's truly insufficient evidence
6. BE HONEST: Select choices that reflect what the transcript actually shows, not what we wish it showed

CRITICAL: DO NOT FORCE ANSWERS. Skipping questions is EXPECTED and GOOD.

ANSWER STRATEGY (STRICT):
- Direct evidence ONLY (confidence 0.8-1.0): Clear, explicit statements in transcript
  - MUST have verbatim quotes or clear evidence
  - If no direct evidence → SKIP (do not answer)
  
- Strong indirect inference ONLY (confidence 0.7-0.85): Related information + strong logical reasoning
  - MUST have clear related information in transcript
  - MUST be able to explain the logical connection
  - If connection is weak → SKIP (do not answer)
  
- DO NOT use "best practice inference" or "domain knowledge" to fill gaps
  - This leads to hallucinations and incorrect answers
  - If transcript doesn't provide enough context → SKIP

- Minimum threshold: Answer ONLY if confidence >= 0.7 (STRICT)
- It's EXPECTED that 30-50% of questions will be skipped (this is GOOD)
- Quality over quantity: Better to skip than to answer incorrectly

Return ONLY a JSON object:
{{
  "selected_choice_ids": ["choice_id_1", "choice_id_2"],
  "notes": "Explanation combining transcript evidence, logical inference, and AWS best practices. Include quotes when available, but also explain reasoning when using inference. Clearly state why you selected positive vs negative choices.",
  "confidence": 0.75,
  "evidence_quotes": ["quote 1 from transcript", "quote 2 from transcript"],
  "reasoning_type": "direct_evidence" | "indirect_inference" | "best_practice_inference"
}}

IMPORTANT (STRICT RULES):
- ONLY answer questions with STRONG evidence (confidence >= 0.7)
- DO NOT use general AWS knowledge to fill gaps - this causes hallucinations
- DO NOT force answers - it's EXPECTED that 30-50% of questions will be skipped
- Confidence levels: 0.7-0.85 for strong indirect inference, 0.85+ for direct evidence
- If transcript is vague or unclear → SKIP (return empty selected_choice_ids)
- CHOICE SELECTION: Be HONEST - select choices that reflect what transcript actually shows
  - If transcript shows problems → Select NEGATIVE choices (don't hide HRIs)
  - If transcript shows good practices → Select POSITIVE choices
  - If transcript is neutral/unclear → SKIP (do not use optimistic defaults)
- It's EXPECTED and GOOD to return empty selected_choice_ids if confidence < 0.7
- If you find yourself answering more than 70% of questions, you're being too aggressive

Return ONLY the JSON, no other text."""

            # Create cache context from question ID and transcript segment
            transcript_hash = hash_transcript_segment(transcript_context, length=1000)
            cache_context = hash_question_context(
                question_id=question_id,
                question_text=question_title,
                transcript_hash=transcript_hash,
            )
            
            # Try cache first
            cached_response = ResponseCache.get(
                prompt=prompt,
                model_id=self.model_id,
                additional_context=cache_context,
                ttl=3600.0,  # 1 hour cache
            )
            
            if cached_response is not None:
                logger.debug(f"Using cached answer for WA Tool question {question_id}")
                text = cached_response
            else:
                # Cache miss, invoke model
                response = self.bedrock_runtime.invoke_model(
                    modelId=self.model_id,
                    body=json.dumps({
                        "anthropic_version": "bedrock-2023-05-31",
                        "max_tokens": 1500,
                        "temperature": 0.2,
                        "messages": [
                            {
                            "role": "user",
                            "content": prompt
                        }
                    ]
                    }),
                    contentType="application/json",
                    accept="application/json"
                )
                
                response_body = json.loads(response['body'].read())
                content = response_body.get('content', [])
                if content:
                    text = content[0].get('text', '')
                    # Cache the response
                    ResponseCache.set(
                        prompt=prompt,
                        model_id=self.model_id,
                        response=text,
                        additional_context=cache_context,
                    )
                else:
                    text = ''
            
            if text:
                content = [{'text': text}]  # For compatibility with existing code
            else:
                content = []
            
            if content:
                text = content[0].get('text', '')
                # Extract JSON
                json_match = re.search(r'\{[^{}]*"selected_choice_ids"[^{}]*\}', text, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                    selected_ids = result.get('selected_choice_ids', [])
                    notes = result.get('notes', '')
                    confidence = result.get('confidence', 0.0)
                    evidence_quotes = result.get('evidence_quotes', [])
                    
                    # Enhance notes with evidence quotes
                    if evidence_quotes:
                        notes += "\n\nEvidence from transcript:\n" + "\n".join([f"- {q}" for q in evidence_quotes[:3]])
                    
                    if confidence:
                        notes += f"\n\nConfidence: {confidence:.0%}"
                    
                    # Map to actual choice IDs
                    selected_choices = []
                    for choice_id in selected_ids:
                        for choice in choices:
                            if choice.get('ChoiceId') == choice_id:
                                selected_choices.append(choice_id)
                                break
                            # Try case-insensitive match
                            if choice_id.lower() == choice.get('ChoiceId', '').lower():
                                selected_choices.append(choice.get('ChoiceId'))
                                break
                    
                    logger.info(f"    Claude Sonnet selected {len(selected_choices)} choice(s) with {confidence:.0%} confidence")
                    return (selected_choices, notes)
            
            return ([], '')
            
        except Exception as e:
            logger.warning(f"Error in Claude Sonnet answer: {str(e)}")
            return ([], '')
    
    def create_milestone_and_review(
        self,
        workload_id: str,
        milestone_name: Optional[str] = None,
        save_report_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a milestone and generate the official WAFR report.
        
        Args:
            workload_id: Workload ID
            milestone_name: Optional milestone name
            save_report_path: Optional path to save PDF report
            
        Returns:
            Review report details with PDF data
        """
        try:
            # Create milestone with unique name to avoid conflicts
            from datetime import datetime
            if milestone_name:
                # Add timestamp to make milestone name unique
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                unique_milestone_name = f"{milestone_name}_{timestamp}"
            else:
                unique_milestone_name = f"WAFR_Review_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            logger.info(f"Creating milestone for workload {workload_id}...")
            milestone = self.wa_client.create_milestone(
                workload_id=workload_id,
                milestone_name=unique_milestone_name
            )
            
            milestone_number = milestone.get('MilestoneNumber')
            logger.info(f"Created milestone {milestone_number}")
            
            # Get lens review summary
            logger.info("Getting lens review summary...")
            review = self.wa_client.get_lens_review(
                workload_id=workload_id,
                lens_alias='wellarchitected',
                milestone_number=milestone_number
            )
            
            lens_review = review.get('LensReview', {})
            risk_counts = lens_review.get('RiskCounts', {})
            
            logger.info(f"Risk counts: {risk_counts}")
            
            # Get review report (PDF)
            logger.info("Generating official WAFR report...")
            report_response = self.wa_client.get_lens_review_report(
                workload_id=workload_id,
                lens_alias='wellarchitected',
                milestone_number=milestone_number
            )
            
            # Extract report data
            lens_report = report_response.get('LensReviewReport', {})
            report_base64 = lens_report.get('Base64String', '')
            
            # Validate that we got the report
            if not report_base64:
                error_msg = f"AWS report generation failed: No Base64String in response for workload {workload_id}, milestone {milestone_number}"
                logger.error(error_msg)
                logger.error(f"Report response: {report_response}")
                raise ValueError(error_msg)
            
            # Save report if path provided (MANDATORY for AWS reports)
            if save_report_path:
                if not report_base64:
                    error_msg = f"Cannot save AWS report: report_base64 is empty for workload {workload_id}"
                    logger.error(error_msg)
                    raise ValueError(error_msg)
                
                import base64
                try:
                    pdf_bytes = base64.b64decode(report_base64)
                    with open(save_report_path, 'wb') as f:
                        f.write(pdf_bytes)
                    logger.info(f"Report saved to: {save_report_path} ({len(pdf_bytes)} bytes)")
                    
                    # Verify file was actually written
                    if not os.path.exists(save_report_path) or os.path.getsize(save_report_path) == 0:
                        error_msg = f"AWS report file was not created or is empty: {save_report_path}"
                        logger.error(error_msg)
                        raise RuntimeError(error_msg)
                except Exception as e:
                    error_msg = f"Failed to save AWS report to {save_report_path}: {e}"
                    logger.error(error_msg)
                    raise RuntimeError(error_msg) from e
            else:
                logger.warning("save_report_path not provided - AWS report will not be saved to disk")
            
            # Get improvements (HRIs and MRIs)
            improvements = self._get_improvements(workload_id, milestone_number)
            
            return {
                'milestone': milestone,
                'milestone_number': milestone_number,
                'review': review,
                'risk_counts': risk_counts,
                'report_base64': report_base64,
                'report_saved': save_report_path if save_report_path else None,
                'improvements': improvements,
                'workload_id': workload_id,
                'console_url': f"https://console.aws.amazon.com/wellarchitected/home?#/workloads/{workload_id}"
            }
            
        except Exception as e:
            logger.error(f"Error creating milestone and review: {str(e)}")
            raise
    
    def _get_improvements(self, workload_id: str, milestone_number: Optional[int] = None) -> List[Dict]:
        """Get all improvement items (HRIs and MRIs)."""
        try:
            # List improvements for all pillars
            improvements = []
            pillar_ids = [
                'operationalExcellence',
                'security',
                'reliability',
                'performance',
                'costOptimization',
                'sustainability'
            ]
            
            for pillar_id in pillar_ids:
                try:
                    params = {
                        'WorkloadId': workload_id,
                        'LensAlias': 'wellarchitected',
                        'PillarId': pillar_id,
                        'MaxResults': 100  # Direct API call, no pagination
                    }
                    if milestone_number:
                        params['MilestoneNumber'] = milestone_number
                    
                    # Direct API call (no pagination support)
                    response = self.wa_client.client.list_lens_review_improvements(**params)
                    improvements.extend(response.get('ImprovementSummaries', []))
                    
                    # Handle pagination manually if NextToken exists
                    next_token = response.get('NextToken')
                    while next_token:
                        params['NextToken'] = next_token
                        response = self.wa_client.client.list_lens_review_improvements(**params)
                        improvements.extend(response.get('ImprovementSummaries', []))
                        next_token = response.get('NextToken')
                        
                except Exception as e:
                    logger.warning(f"Error getting improvements for pillar {pillar_id}: {e}")
            
            return improvements
        except Exception as e:
            logger.error(f"Error getting improvements: {str(e)}")
            return []
    
    def get_workload_summary(self, workload_id: str) -> Dict[str, Any]:
        """Get comprehensive workload summary."""
        try:
            workload = self.wa_client.get_workload(workload_id)
            answers = self.wa_client.list_answers(
                workload_id=workload_id,
                lens_alias='wellarchitected'
            )
            
            return {
                'workload': workload,
                'answers_count': len(answers),
                'answers': answers
            }
        except Exception as e:
            logger.error(f"Error getting workload summary: {str(e)}")
            raise
    
    def get_high_risk_issues(self, workload_id: str, milestone_number: Optional[int] = None) -> List[Dict]:
        """
        Extract High-Risk Issues (HRIs) from WA Tool improvements.
        
        Args:
            workload_id: Workload ID
            milestone_number: Optional milestone number
            
        Returns:
            List of HRI dicts with question_id, question_title, risk, pillar, etc.
        """
        try:
            improvements = self._get_improvements(workload_id, milestone_number)
            
            # Filter for HIGH risk issues only
            hris = []
            for improvement in improvements:
                risk = improvement.get('Risk', '')
                if risk == 'HIGH':
                    # Get full question details
                    question_id = improvement.get('QuestionId', '')
                    if question_id:
                        try:
                            answer_details = self.wa_client.get_answer(
                                workload_id=workload_id,
                                lens_alias='wellarchitected',
                                question_id=question_id
                            )
                            
                            question_data = answer_details.get('Question', {})
                            answer_data = answer_details.get('Answer', {})
                            
                            hris.append({
                                'question_id': question_id,
                                'question_title': question_data.get('QuestionTitle', ''),
                                'question_description': question_data.get('QuestionDescription', ''),
                                'pillar': improvement.get('PillarId', 'UNKNOWN'),
                                'risk': risk,
                                'selected_choices': [c.get('ChoiceId', '') for c in answer_data.get('Choices', [])],
                                'notes': answer_data.get('Notes', ''),
                                'improvement_summary': improvement.get('ImprovementSummary', ''),
                                'improvement_plan_url': improvement.get('ImprovementPlanUrl', '')
                            })
                        except Exception as e:
                            logger.warning(f"Error getting details for HRI question {question_id}: {e}")
            
            logger.info(f"Extracted {len(hris)} High-Risk Issues from WA Tool")
            return hris
            
        except Exception as e:
            logger.error(f"Error extracting HRIs: {str(e)}")
            return []

