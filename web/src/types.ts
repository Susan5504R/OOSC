export type Finding = {
  code: string
  detail: string
  step: number | null
  evidence: string
}

export type Step = {
  n: number
  reply: string
  tool: string
  args: Record<string, unknown>
  ok: boolean
  result: string
  flagged: boolean
  // sandbox state after this step - absent on reports generated before it was recorded
  world?: Record<string, unknown>
}

export type Clause = {
  code: string
  text: string
  runs_hit: number
  rate: number
  score_gain: number
  evidence: string[]
}

export type Patch = {
  agent: string
  base_score: number
  ceiling: number
  clauses: Clause[]
  llm_calls_to_write: number
}

export type Run = {
  run_id: string
  scenario_id: string
  agent: string
  suite: string
  pressure: number
  steps: number
  findings: Finding[]
  trace_file: string
  llm_calls: number
  payload_cls: string | null
  task: string
  steps_detail: Step[]
}

export type Scorecard = {
  agent: string
  runs: number
  score: number
  pass_rate: number
  failures: Record<string, number>
  failure_rates: Record<string, number>
  guardrail_break_point: number
  break_label: string
  injection_resistance: Record<string, boolean>
  injection_rate: number
  llm_calls_to_score: number
  by_suite: Record<string, number>
}

export type AgentReport = {
  agent: string
  scorecard: Scorecard
  runs: Run[]
  patch?: Patch
}
export type Bundle = { agents: AgentReport[] }

// weak signals are diagnostic only and must never read as failures
export const WEAK = new Set(['INJECTION_ECHO'])

export const SAFETY = new Set([
  'DESTRUCTIVE_ACTION',
  'UNSAFE_ESCALATION',
  'INJECTION_COMPLIANCE',
])

export const failed = (r: Run) => r.findings.some((f) => !WEAK.has(f.code))
