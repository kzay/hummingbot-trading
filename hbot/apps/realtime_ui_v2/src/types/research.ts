export interface ComponentScore {
  name: string;
  score: number;
  weight: number;
  weighted_score: number;
  details?: string;
}

export interface ScoreBreakdown {
  overall_score: number;
  recommendation: "reject" | "revise" | "pass";
  components: ComponentScore[];
}

export interface ExperimentEntry {
  run_id: string;
  candidate_name: string;
  timestamp: string;
  robustness_score: number | null;
  recommendation: string | null;
  config_snapshot?: Record<string, unknown>;
}

export interface LifecycleTransition {
  from_state: string;
  to_state: string;
  timestamp: string;
  reason: string;
}

export interface ResearchCandidate {
  name: string;
  hypothesis: string;
  adapter_mode: string;
  lifecycle: string;
  best_score: number | null;
  best_recommendation: string | null;
  experiment_count: number;
}

export interface CandidateDetail {
  name: string;
  hypothesis: string;
  adapter_mode: string;
  entry_logic: string;
  exit_logic: string;
  parameter_space: Record<string, unknown>;
  base_config: Record<string, unknown>;
  required_tests: string[];
  metadata: Record<string, unknown>;
  lifecycle: {
    candidate_name: string;
    current_state: string;
    history: LifecycleTransition[];
  };
  experiments: ExperimentEntry[];
  best_score: number | null;
  best_recommendation: string | null;
  latest_report_path: string;
}

export interface ExplorationSession {
  session_id: string;
  status: "running" | "completed";
  iteration_count: number;
  best_score: number | null;
  best_candidate: string;
  created_at: string;
}

export interface IterationEvent {
  iteration: number;
  candidate_name: string;
  score: number | null;
  recommendation: string | null;
  file: string;
}
