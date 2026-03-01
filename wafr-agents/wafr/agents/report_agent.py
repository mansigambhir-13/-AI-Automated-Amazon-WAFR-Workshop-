"""
Report Generation Agent - Generates comprehensive WAFR assessment reports
Uses Strands framework
"""
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from strands import Agent, tool

from wafr.agents.config import DEFAULT_MODEL_ID
from wafr.agents.model_config import get_strands_model
from wafr.agents.wafr_context import get_wafr_context_summary, load_wafr_schema

logger = logging.getLogger(__name__)


def get_report_system_prompt(wafr_schema: Optional[Dict[str, Any]] = None) -> str:
    """Generate enhanced system prompt with WAFR context."""
    base_prompt = """
You are generating an official AWS Well-Architected Framework Review report that matches the exact format and content structure of AWS Well-Architected Tool reports.

CRITICAL REQUIREMENTS:
- Use ONLY official AWS Well-Architected Framework terminology and content
- Match the exact structure and format of official AWS WA Tool reports
- Include ONLY what appears in official AWS reports - no custom commentary, no additional analysis, no personal opinions
- Use official AWS pillar names, question IDs, and risk levels exactly as defined by AWS
- Follow the official AWS report sections and formatting

OFFICIAL AWS REPORT STRUCTURE (use exactly):
1. Executive Summary - Official AWS format only
2. Pillar-by-Pillar Analysis - Official AWS pillar assessment format
3. High-Risk Issues (HRIs) - Official AWS HRI format and terminology
4. Risk Summary - Official AWS risk categorization (HIGH, MEDIUM, LOW)
5. Improvement Plan - Official AWS improvement recommendations format

STRICT RULES:
- NO custom commentary or additional analysis
- NO personal opinions or interpretations beyond official AWS guidance
- NO extra sections not in official AWS reports
- Use ONLY official AWS terminology (e.g., "High-Risk Issue" not "critical gap")
- Reference ONLY official AWS best practices and recommendations
- Format must match official AWS WA Tool PDF reports exactly
- Use official AWS question IDs and pillar IDs exactly as defined

CONTENT REQUIREMENTS:
- Only include information that would appear in an official AWS WA Tool report
- Use official AWS risk levels: HIGH, MEDIUM, LOW
- Use official AWS pillar names: Operational Excellence, Security, Reliability, Performance Efficiency, Cost Optimization, Sustainability
- Use official AWS question format and structure
- Include only official AWS recommendations and best practices

DO NOT INCLUDE:
- Custom analysis or commentary
- Personal opinions or interpretations
- Additional sections not in official AWS reports
- Non-official terminology or descriptions
- Confidence scores or internal metrics (unless part of official AWS format)
- Any content that would not appear in an official AWS WA Tool report
"""
    
    if wafr_schema:
        wafr_context = get_wafr_context_summary(wafr_schema)
        return f"{base_prompt}\n\n{wafr_context}\n\nUse this WAFR context to generate comprehensive, aligned reports."
    
    return base_prompt


@tool
def generate_executive_summary(
    overall_health: str,
    key_findings: List[str],
    immediate_actions: List[str],
    confidence_summary: Dict
) -> Dict:
    """
    Generate executive summary section.
    
    Args:
        overall_health: Overall assessment health (e.g., "Good with critical gaps")
        key_findings: Top 3-5 key findings
        immediate_actions: Immediate action items
        confidence_summary: Confidence statistics
        
    Returns:
        Executive summary dictionary
    """
    return {
        'overall_health': overall_health,
        'key_findings': key_findings,
        'immediate_actions': immediate_actions,
        'confidence_summary': confidence_summary,
        'generated_at': datetime.utcnow().isoformat()
    }


@tool
def generate_pillar_analysis(
    pillar_id: str,
    pillar_name: str,
    current_state: str,
    strengths: List[str],
    gaps: List[str],
    evidence_citations: List[str],
    score: float
) -> Dict:
    """
    Generate pillar analysis section.
    
    Args:
        pillar_id: Pillar ID (OPS, SEC, etc.)
        pillar_name: Full pillar name
        current_state: Current state assessment
        strengths: List of strengths
        gaps: List of gaps identified
        evidence_citations: Evidence quotes
        score: Pillar score (0-100)
        
    Returns:
        Pillar analysis dictionary
    """
    return {
        'pillar_id': pillar_id,
        'pillar_name': pillar_name,
        'current_state': current_state,
        'strengths': strengths,
        'gaps': gaps,
        'evidence_citations': evidence_citations,
        'score': score
    }


@tool
def generate_hri_list(
    hri_issues: List[Dict]
) -> List[Dict]:
    """
    Generate High-Risk Issues list.
    
    Args:
        hri_issues: List of HRI dictionaries with description, impact, pillar, remediation
        
    Returns:
        Formatted HRI list
    """
    return hri_issues


@tool
def generate_remediation_roadmap(
    critical_fixes: List[Dict[str, Any]],
    improvements: List[Dict[str, Any]],
    optimizations: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Generate 90-day remediation roadmap.
    
    Args:
        critical_fixes: Phase 1 items (Days 1-30)
        improvements: Phase 2 items (Days 31-60)
        optimizations: Phase 3 items (Days 61-90)
        
    Returns:
        Roadmap dictionary
    """
    return {
        'phase_1': {
            'name': 'Critical Fixes',
            'timeline': 'Days 1-30',
            'items': critical_fixes
        },
        'phase_2': {
            'name': 'Improvements',
            'timeline': 'Days 31-60',
            'items': improvements
        },
        'phase_3': {
            'name': 'Optimizations',
            'timeline': 'Days 61-90',
            'items': optimizations
        }
    }


class ReportAgent:
    """Agent that generates comprehensive WAFR reports."""
    
    def __init__(self, wafr_schema: Optional[Dict] = None, lens_context: Optional[Dict] = None):
        """
        Initialize Report Agent.
        
        Args:
            wafr_schema: Optional WAFR schema for context
            lens_context: Optional lens context for multi-lens support
        """
        if wafr_schema is None:
            wafr_schema = load_wafr_schema()
        
        self.wafr_schema = wafr_schema
        self.lens_context = lens_context or {}
        system_prompt = get_report_system_prompt(wafr_schema)
        
        try:
            model = get_strands_model(DEFAULT_MODEL_ID)
            agent_kwargs = {
                'system_prompt': system_prompt,
                'name': 'ReportAgent'
            }
            if model:
                agent_kwargs['model'] = model
            
            self.agent = Agent(**agent_kwargs)
            # Try to add tools if method exists
            try:
                try:
                    self.agent.add_tool(generate_executive_summary)
                    self.agent.add_tool(generate_pillar_analysis)
                    self.agent.add_tool(generate_hri_list)
                    self.agent.add_tool(generate_remediation_roadmap)
                except AttributeError:
                    try:
                        self.agent.register_tool(generate_executive_summary)
                        self.agent.register_tool(generate_pillar_analysis)
                        self.agent.register_tool(generate_hri_list)
                        self.agent.register_tool(generate_remediation_roadmap)
                    except AttributeError:
                        pass  # Tools may be auto-detected
            except Exception as e:
                logger.warning(f"Could not add tools to report agent: {e}")
        except Exception as e:
            logger.warning(f"Strands Agent initialization issue: {e}, using direct Bedrock")
            self.agent = None
    
    def process(
        self,
        assessment_data: Dict,
        session_id: str,
    ) -> Dict[str, Any]:
        """
        Generate comprehensive WAFR report.
        
        Args:
            assessment_data: Complete assessment data including answers, scores, gaps
            session_id: Session identifier
            
        Returns:
            Generated report dictionary
        """
        logger.info(f"ReportAgent: Generating report for session {session_id}")
        
        # Extract data from assessment
        answers = assessment_data.get('answers', [])
        scores = assessment_data.get('scores', {})
        gaps = assessment_data.get('gaps', [])
        gaps_by_lens = assessment_data.get('gaps_by_lens', {})
        pillar_coverage = assessment_data.get('pillar_coverage', {})
        
        # Build lens context for report
        lens_info = ""
        if self.lens_context and self.lens_context.get('lenses'):
            lens_info = "\n\nACTIVE LENSES:\n"
            for alias, lens_data in self.lens_context['lenses'].items():
                lens_info += f"- {lens_data.get('name', alias)}: {lens_data.get('question_count', 0)} questions\n"
        
        # Build gaps by lens info
        gaps_by_lens_info = ""
        if gaps_by_lens:
            gaps_by_lens_info = "\n\nGAPS BY LENS:\n"
            for lens_alias, lens_stats in gaps_by_lens.items():
                gaps_by_lens_info += f"- {lens_alias}: {lens_stats.get('unanswered_questions', 0)} gaps "
                gaps_by_lens_info += f"({lens_stats.get('coverage_percentage', 0)}% coverage)\n"
        
        # Get user context for adaptation
        user_adaptation = ""
        try:
            from wafr.agents.user_context import get_user_context_manager
            user_context_manager = get_user_context_manager()
            adaptation_guidance = user_context_manager.get_adaptation_guidance(session_id)
            adaptation_prompt = adaptation_guidance.get("adaptation_prompt", "")
            if adaptation_prompt:
                user_adaptation = f"\n\n## User Context & Adaptation\n\n{adaptation_prompt}\n\n**IMPORTANT**: While maintaining official AWS report format, adapt the content, examples, and recommendations to align with the user's specific domain, use case, and business context. Think from the user's perspective when presenting findings and recommendations."
        except Exception as e:
            logger.debug(f"Could not load user context for report: {e}")
        
        # Use agent to generate report - OFFICIAL AWS FORMAT ONLY
        prompt = f"""
        Generate an official AWS Well-Architected Framework Review report that matches the exact format of AWS Well-Architected Tool reports.
        
        IMPORTANT: This must be an OFFICIAL AWS report format - no custom commentary, no additional analysis, only official AWS content.
{user_adaptation}
        
        Assessment Data:
        - Answers: {len(answers)} questions answered
        - Gaps: {len(gaps)} unanswered questions
        {lens_info}
        {gaps_by_lens_info}
        
        Sample Answers: {json.dumps(answers[:3], indent=2)}
        
        Generate report using ONLY official AWS Well-Architected Framework:
        1. Executive Summary - Official AWS format only (include multi-lens summary if applicable)
        2. Pillar Analysis - Official AWS pillar assessment (OPS, SEC, REL, PERF, COST, SUS)
        3. Lens-Specific Analysis - Per-lens assessment if multiple lenses are active
        4. Cross-Lens Correlation - Identify patterns across lenses (e.g., security concerns in GenAI and ML lenses)
        5. High-Risk Issues - Official AWS HRI format (aggregated across all lenses)
        6. Risk Summary - Official AWS risk levels (HIGH, MEDIUM, LOW) per lens
        7. Improvement Plan - Official AWS recommendations format (grouped by lens)
        
        CRITICAL: 
        - Use ONLY official AWS terminology and content
        - NO custom commentary or additional analysis
        - Match official AWS WA Tool report structure exactly
        - Include only what would appear in an official AWS report
        - If multiple lenses: Show per-lens analysis AND cross-lens insights
        
        Return report in official AWS format structure with multi-lens support.
        """
        
        try:
            if self.agent:
                response = self.agent(prompt)
                # Handle response
                if isinstance(response, dict):
                    response = self._sanitize_dict(response)
            else:
                response = {}
        except (UnicodeEncodeError, UnicodeDecodeError) as e:
            logger.error(f"Unicode encoding error in report agent: {e}")
            # Fallback to constructing report from data
            response = {}
        except Exception as e:
            logger.error(f"Error in report agent: {e}")
            response = {}
        
        # Parse report structure
        report = self._parse_report(response, assessment_data, session_id)
        
        # Add multi-lens analysis if applicable
        if self.lens_context and self.lens_context.get('lenses') and len(self.lens_context['lenses']) > 1:
            report['multi_lens_analysis'] = self._generate_cross_lens_analysis(
                assessment_data, gaps_by_lens
            )
        
        # Final sanitization before returning
        report = self._sanitize_dict(report)
        
        return {
            'session_id': session_id,
            'report': report,
            'metadata': {
                'generated_at': datetime.utcnow().isoformat(),
                'version': '1.0',
                'agent': 'report',
                'lenses_analyzed': list(self.lens_context.get('lenses', {}).keys()) if self.lens_context else ['wellarchitected']
            }
        }
    
    def _generate_cross_lens_analysis(self, assessment_data: Dict, gaps_by_lens: Dict) -> Dict:
        """
        Generate cross-lens correlation and insights.
        
        Args:
            assessment_data: Complete assessment data
            gaps_by_lens: Gaps organized by lens
            
        Returns:
            Cross-lens analysis dictionary
        """
        analysis = {
            'cross_lens_patterns': [],
            'common_risks': [],
            'lens_specific_insights': {},
            'recommendations': []
        }
        
        # Identify common patterns across lenses
        if gaps_by_lens:
            # Find common pillar gaps across lenses
            pillar_gaps_by_lens = {}
            for lens_alias, lens_stats in gaps_by_lens.items():
                gaps = lens_stats.get('gaps', [])
                for gap in gaps:
                    pillar = gap.get('pillar', 'UNKNOWN')
                    if pillar not in pillar_gaps_by_lens:
                        pillar_gaps_by_lens[pillar] = []
                    pillar_gaps_by_lens[pillar].append({
                        'lens': lens_alias,
                        'question': gap.get('question_text', ''),
                        'priority': gap.get('priority_score', 0)
                    })
            
            # Find pillars with gaps in multiple lenses
            for pillar, lens_gaps in pillar_gaps_by_lens.items():
                if len(set(g['lens'] for g in lens_gaps)) > 1:
                    analysis['cross_lens_patterns'].append({
                        'pillar': pillar,
                        'affected_lenses': list(set(g['lens'] for g in lens_gaps)),
                        'gap_count': len(lens_gaps),
                        'description': f"Common gaps in {pillar} pillar across multiple lenses"
                    })
        
        # Generate lens-specific insights
        if gaps_by_lens:
            for lens_alias, lens_stats in gaps_by_lens.items():
                gaps = lens_stats.get('gaps', [])
                high_priority_gaps = [g for g in gaps if g.get('priority_score', 0) > 0.7]
                
                if high_priority_gaps:
                    analysis['lens_specific_insights'][lens_alias] = {
                        'high_priority_gaps': len(high_priority_gaps),
                        'coverage': lens_stats.get('coverage_percentage', 0),
                        'top_gaps': [
                            {
                                'question': g.get('question_text', '')[:100],
                                'priority': g.get('priority_score', 0)
                            }
                            for g in sorted(high_priority_gaps, key=lambda x: x.get('priority_score', 0), reverse=True)[:3]
                        ]
                    }
        
        return analysis
    
    def _parse_report(self, response: Any, assessment_data: Dict, session_id: str) -> Dict:
        """Parse report from agent response with Unicode safety."""
        try:
            if isinstance(response, dict):
                # Sanitize all string values in dict
                response = self._sanitize_dict(response)
                if 'executive_summary' in response:
                    report = response
                else:
                    report = self._construct_report_from_data(response, assessment_data)
            elif isinstance(response, str):
                try:
                    report = json.loads(response)
                    report = self._sanitize_dict(report)
                except json.JSONDecodeError:
                    report = self._construct_report_from_data({}, assessment_data)
            else:
                report = self._construct_report_from_data({}, assessment_data)
        except Exception as e:
            logger.error(f"Error parsing report: {str(e)}")
            report = self._construct_report_from_data({}, assessment_data)
        
        # Ensure required sections exist and sanitize final report
        report = self._sanitize_dict(report)
        if 'executive_summary' not in report:
            report['executive_summary'] = self._generate_executive_summary(assessment_data)
        
        if 'pillar_analysis' not in report:
            report['pillar_analysis'] = self._generate_pillar_analysis(assessment_data)
        
        if 'high_risk_issues' not in report:
            report['high_risk_issues'] = self._extract_hris(assessment_data)
        
        if 'remediation_roadmap' not in report:
            report['remediation_roadmap'] = self._generate_roadmap(assessment_data)
        
        # Final sanitization pass
        report = self._sanitize_dict(report)
        
        return report
    
    def _sanitize_dict(self, data: Any) -> Any:
        """Recursively sanitize dictionary values for Unicode safety."""
        if isinstance(data, dict):
            return {k: self._sanitize_dict(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._sanitize_dict(item) for item in data]
        elif isinstance(data, str):
            # Handle Unicode safely
            try:
                data.encode('utf-8')
                return data
            except UnicodeEncodeError:
                return data.encode('utf-8', errors='replace').decode('utf-8')
        else:
            return data
    
    def _construct_report_from_data(self, partial: Dict, assessment_data: Dict) -> Dict:
        """Construct report from assessment data."""
        return {
            'executive_summary': self._generate_executive_summary(assessment_data),
            'pillar_analysis': self._generate_pillar_analysis(assessment_data),
            'high_risk_issues': self._extract_hris(assessment_data),
            'remediation_roadmap': self._generate_roadmap(assessment_data)
        }
    
    def _generate_executive_summary(self, assessment_data: Dict) -> Dict:
        """Generate executive summary in official AWS format only."""
        scores = assessment_data.get('scores', {})
        gaps = assessment_data.get('gaps', [])
        answers = assessment_data.get('answers', [])
        
        # Count risks by official AWS levels
        high_risks = len([a for a in answers if a.get('grade') == 'F'])
        medium_risks = len([a for a in answers if a.get('grade') == 'D'])
        low_risks = len([a for a in answers if a.get('grade') in ['C', 'B']])
        
        # Official AWS format - no custom commentary
        return {
            'workload_summary': {
                'total_questions': len(answers) + len(gaps),
                'answered_questions': len(answers),
                'unanswered_questions': len(gaps)
            },
            'risk_summary': {
                'HIGH': high_risks,
                'MEDIUM': medium_risks,
                'LOW': low_risks
            },
            'pillar_coverage': assessment_data.get('pillar_coverage', {})
        }
    
    def _generate_pillar_analysis(self, assessment_data: Dict) -> List[Dict]:
        """Generate pillar analysis in official AWS format only."""
        pillars = ['OPS', 'SEC', 'REL', 'PERF', 'COST', 'SUS']
        pillar_names = {
            'OPS': 'Operational Excellence',
            'SEC': 'Security',
            'REL': 'Reliability',
            'PERF': 'Performance Efficiency',
            'COST': 'Cost Optimization',
            'SUS': 'Sustainability'
        }
        
        analysis = []
        answers = assessment_data.get('answers', [])
        
        for pillar_id in pillars:
            pillar_answers = [a for a in answers if a.get('pillar') == pillar_id]
            
            # Official AWS risk counts
            high_risk = len([a for a in pillar_answers if a.get('grade') == 'F'])
            medium_risk = len([a for a in pillar_answers if a.get('grade') == 'D'])
            low_risk = len([a for a in pillar_answers if a.get('grade') in ['A', 'B', 'C']])
            
            # Official AWS format - only official content
            analysis.append({
                'pillar_id': pillar_id,
                'pillar_name': pillar_names.get(pillar_id, pillar_id),
                'questions_answered': len(pillar_answers),
                'risk_counts': {
                    'HIGH': high_risk,
                    'MEDIUM': medium_risk,
                    'LOW': low_risk
                },
                'questions': [
                    {
                        'question_id': a.get('question_id', ''),
                        'question_text': a.get('question_text', ''),
                        'risk_level': 'HIGH' if a.get('grade') == 'F' else 'MEDIUM' if a.get('grade') == 'D' else 'LOW',
                        'answer': a.get('answer_content', '')
                    }
                    for a in pillar_answers
                ]
            })
        
        return analysis
    
    def _extract_hris(self, assessment_data: Dict) -> List[Dict]:
        """Extract high-risk issues in official AWS format only."""
        answers = assessment_data.get('answers', [])
        hris = []
        
        # Official AWS HRI format - only HIGH risk issues
        for answer in answers:
            if answer.get('grade') == 'F':  # Only F grades are HIGH risk in official AWS
                hris.append({
                    'question_id': answer.get('question_id', ''),
                    'question_text': answer.get('question_text', ''),
                    'pillar_id': answer.get('pillar', 'UNKNOWN'),
                    'risk_level': 'HIGH',
                    'issue': answer.get('answer_content', ''),
                    'improvement_plan': answer.get('improvement_suggestions', []) if isinstance(answer.get('improvement_suggestions'), list) else []
                })
        
        return hris
    
    def _generate_roadmap(self, assessment_data: Dict) -> Dict:
        """Generate improvement plan in official AWS format only."""
        answers = assessment_data.get('answers', [])
        
        # Official AWS risk-based improvement plan
        high_risk = [a for a in answers if a.get('grade') == 'F']
        medium_risk = [a for a in answers if a.get('grade') == 'D']
        low_risk = [a for a in answers if a.get('grade') == 'C']
        
        # Official AWS format - improvement plan structure
        return {
            'improvement_plan': {
                'high_priority': [
                    {
                        'question_id': a.get('question_id', ''),
                        'question_text': a.get('question_text', ''),
                        'pillar_id': a.get('pillar', ''),
                        'risk_level': 'HIGH',
                        'recommendation': a.get('improvement_suggestions', [])[0] if isinstance(a.get('improvement_suggestions'), list) and len(a.get('improvement_suggestions', [])) > 0 else ''
                    }
                    for a in high_risk[:10]
                ],
                'medium_priority': [
                    {
                        'question_id': a.get('question_id', ''),
                        'question_text': a.get('question_text', ''),
                        'pillar_id': a.get('pillar', ''),
                        'risk_level': 'MEDIUM',
                        'recommendation': a.get('improvement_suggestions', [])[0] if isinstance(a.get('improvement_suggestions'), list) and len(a.get('improvement_suggestions', [])) > 0 else ''
                    }
                    for a in medium_risk[:10]
                ],
                'low_priority': [
                    {
                        'question_id': a.get('question_id', ''),
                        'question_text': a.get('question_text', ''),
                        'pillar_id': a.get('pillar', ''),
                        'risk_level': 'LOW',
                        'recommendation': a.get('improvement_suggestions', [])[0] if isinstance(a.get('improvement_suggestions'), list) and len(a.get('improvement_suggestions', [])) > 0 else ''
                    }
                    for a in low_risk[:10]
                ]
            }
        }


def create_report_agent(wafr_schema: Optional[Dict] = None, lens_context: Optional[Dict] = None) -> ReportAgent:
    """
    Factory function to create Report Agent.
    
    Args:
        wafr_schema: Optional WAFR schema for context
        lens_context: Optional lens context for multi-lens support
    """
    return ReportAgent(wafr_schema=wafr_schema, lens_context=lens_context)

