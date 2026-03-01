// All WAFR frontend data types

export interface Session {
  id: string;
  name: string;
  status: 'completed' | 'in-progress' | 'pending' | 'failed';
  created_at: string;
}

export interface PillarMetrics {
  [key: string]: string | number;
}

export interface PillarDetails {
  strengths: string[];
  improvements: string[];
  metrics: PillarMetrics;
}

export interface Pillar {
  name: string;
  score: number;
  description: string;
  details: PillarDetails;
}

export interface Insight {
  id: string;
  title: string;
  severity: 'High' | 'Medium' | 'Low';
  pillar: string;
  category: string;
  description: string;
  recommendation: string;
  impact: string;
  effort: string;
  cost_impact: string;
  affected_resources: string[];
  implementation_steps: string[];
  references: string[];
}

export interface Question {
  id: string;
  pillar: string;
  category: string;
  text: string;
  status: 'Answered' | 'Pending';
  answer: string | null;
  best_practice: string;
  notes: string;
  risk_level: 'High' | 'Medium' | 'Low';
  improvement_plan: string | null;
}

export interface Gap {
  id: string;
  title: string;
  pillar: string;
  risk_level: 'High' | 'Medium' | 'Low';
  category: string;
  description: string;
  mitigation: string;
  business_impact: string;
  current_state: string;
  target_state: string;
  timeline: string;
  priority: number;
  affected_services: string[];
  remediation_steps: string[];
  estimated_cost: string;
}

export interface ReviewItem {
  id: string;
  type: string;
  content: string;
  description: string;
  status: 'pending' | 'approved' | 'rejected';
  pillar: string;
  severity: 'High' | 'Medium' | 'Low';
  affected_resources: string[];
  recommendation: string;
  estimated_effort: string;
  auto_remediable: boolean;
}

export interface ReviewSummary {
  total_items: number;
  approved_items: number;
  rejected_items: number;
  pending_items: number;
  high_risk_gaps: number;
  medium_risk_gaps: number;
  low_risk_gaps: number;
  auto_remediable_count: number;
  estimated_total_effort: string;
  potential_cost_savings: string;
  potential_cost_increase: string;
}

export interface ScoreHistoryEntry {
  date: string;
  overall_score: number;
  security: number;
  reliability: number;
  performance: number;
  cost: number;
  operational: number;
  sustainability: number;
}

export interface TrendData {
  score_history: ScoreHistoryEntry[];
  improvement_velocity: {
    monthly_improvement: number;
    projected_score_3months: number;
    projected_score_6months: number;
  };
  benchmark_comparison: {
    industry_average: number;
    top_quartile: number;
    your_score: number;
    percentile: number;
  };
}

export interface ExecutiveSummary {
  overview: string;
  key_strengths: string[];
  critical_actions: string[];
  quick_wins: string[];
  investment_required: {
    immediate: string;
    short_term: string;
    long_term: string;
  };
  expected_benefits: {
    cost_savings: string;
    risk_reduction: string;
    performance_improvement: string;
    availability_improvement: string;
  };
  timeline: {
    immediate_actions: string;
    short_term_improvements: string;
    long_term_transformation: string;
  };
}

export interface Reviewer {
  name: string;
  email: string;
  role: string;
}

export interface WorkloadDetails {
  industry: string;
  architecture_type: string;
  deployment_model: string;
  compliance_requirements: string[];
  monthly_cost: string;
  monthly_traffic: string;
  team_size: number;
  services_count: number;
}

export interface AssessmentScope {
  pillars_assessed: number;
  questions_total: number;
  questions_answered: number;
  resources_analyzed: number;
  accounts_scanned: number;
  regions_scanned: string[];
}

export interface RiskSummary {
  critical_risks: number;
  high_risks: number;
  medium_risks: number;
  low_risks: number;
  total_risks: number;
}

export interface ComplianceStatus {
  compliant_checks: number;
  non_compliant_checks: number;
  compliance_percentage: number;
}

export interface SessionMetadata {
  session_id: string;
  assessment_name: string;
  workload_name: string;
  workload_description: string;
  environment: string;
  aws_account_id: string;
  region: string;
  created_at: string;
  completed_at: string;
  duration_minutes: number;
  status: string;
  reviewer: Reviewer;
  workload_details: WorkloadDetails;
  assessment_scope: AssessmentScope;
  risk_summary: RiskSummary;
  compliance_status: ComplianceStatus;
}

// Backend-specific types (for SSE events)
export interface SSEEvent {
  type: string;
  data?: Record<string, unknown>;
  timestamp?: string;
}

export interface BackendSession {
  session_id: string;
  assessment_name: string;
  status: string;
  current_step: string;
  progress: number;
  overall_score: number;
  client_name?: string;
  workload_id?: string;
  report_file?: string;
  created_at: string;
  updated_at: string;
}

export interface BackendSessionsResponse {
  sessions: BackendSession[];
  count: number;
  metrics: {
    total_assessments: number;
    completed: number;
    in_progress: number;
    avg_score: number;
  };
}
