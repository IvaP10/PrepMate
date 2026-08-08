'use client'

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { useRouter } from 'next/navigation'
import { AlertTriangle, ArrowDownRight, ArrowUpRight, ChevronRight, Clock3, Code, ExternalLink, Loader2, MessageSquare, RefreshCw } from 'lucide-react'

import { SlidingSegmentControl } from '@/components/sliding-segment-control'
import { Button } from '@/components/ui/button'
import { fetchPerformance, reconcilePerformance, type DynamicPerformancePayload, type PerformanceAnalytics, type PerformanceData } from '@/lib/api'
import { chooseInitialPerformanceTab, hasPerformanceModeData } from '@/lib/performance-state'
import { safeStorageSet } from '@/lib/safe-storage'

type PracticeTab = 'interview' | 'coding'
type PerformanceMode = 'interview' | 'technical'

const MIN_REPEATED_ROUNDS = 2
const WEAK_SCORE_THRESHOLD = 70
const STRONG_SCORE_THRESHOLD = 80

function numericScore(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const numeric = Number(value.replace('%', '').trim())
    return Number.isFinite(numeric) ? numeric : null
  }
  return null
}

function formatScore(value: unknown, suffix = '%') {
  const numeric = numericScore(value)
  return numeric === null ? '' : `${Math.round(Math.max(0, Math.min(100, numeric)))}${suffix}`
}

function formatNumber(value: unknown, suffix = '') {
  const numeric = numericScore(value)
  if (numeric === null) return ''
  return `${Number.isInteger(numeric) ? numeric : numeric.toFixed(1)}${suffix}`
}

function formatShortDate(value?: string | null, fallback = 'Recorded round') {
  if (!value) return fallback
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? fallback : parsed.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function formatDuration(seconds: unknown) {
  const numeric = numericScore(seconds)
  if (numeric === null || numeric < 0) return ''
  const minutes = Math.floor(numeric / 60)
  const remaining = Math.round(numeric % 60)
  if (!minutes) return `${remaining}s`
  return `${minutes}m${remaining ? ` ${remaining}s` : ''}`
}

function formatDelta(value: unknown) {
  const numeric = numericScore(value)
  if (numeric === null) return ''
  return `${numeric > 0 ? '+' : ''}${Number.isInteger(numeric) ? numeric : numeric.toFixed(1)} pts`
}

function sectionRows(payload: DynamicPerformancePayload | null | undefined, id: string) {
  const section = payload?.sections?.find((item) => item.id === id)
  return section?.rows || section?.items || []
}

function sectionMetrics(payload: DynamicPerformancePayload | null | undefined, id: string) {
  return payload?.sections?.find((item) => item.id === id)?.metrics || []
}

function fallbackAnalytics(payload: DynamicPerformancePayload | null | undefined, mode: PerformanceMode): PerformanceAnalytics {
  const dimensions = sectionRows(payload, 'dimension_scores')
  const skills = dimensions.map((row) => ({
    label: String(row.dimension || row.metric || row.label || '').trim(),
    average_score: numericScore(row.score),
    evaluated_questions: Number(row.attempts || 0),
    round_count: Number(row.session_count || row.round_count || 0),
    evidence: row.evidence_ids || row.evidence_id ? [{ evidence_id: row.evidence_id, evidence_ids: row.evidence_ids }] : [],
  })).filter((row) => row.label && row.average_score !== null)
  const topics = sectionRows(payload, 'topic_performance').map((row) => ({
    label: String(row.topic || row.label || row.dimension || '').trim(),
    average_score: numericScore(row.score),
    question_count: Number(row.attempts || row.questions || 0),
    problems_attempted: Number(row.attempts || 0),
    problems_solved: Number(row.solved || 0),
    round_count: Number(row.session_count || row.round_count || 0),
    common_issue: row.main_issue || row.common_issue || '',
    evidence: [],
  })).filter((row) => row.label && (row.average_score !== null || row.problems_attempted))
  const questionTypes = sectionRows(payload, 'question_type_performance').map((row) => ({
    label: String(row.label || row.type || '').trim(),
    average_score: numericScore(row.score),
    question_count: Number(String(row.detail || '').match(/[0-9]+/)?.[0] || row.count || 0),
    round_count: Number(row.session_count || row.round_count || 0),
    common_issue: row.main_issue || row.common_issue || '',
    evidence: [],
  })).filter((row) => row.label && row.average_score !== null)
  const patterns = sectionRows(payload, mode === 'technical' ? 'repeated_coding_patterns' : 'repeated_mistakes').map((row) => ({
    label: String(row.pattern || row.mistake || row.label || '').trim(),
    count: Number(row.count || 0),
    round_count: Number(row.session_count || row.round_count || 0),
    evidence: row.example ? [{ question: row.example }] : [],
  })).filter((row) => row.label && row.count >= MIN_REPEATED_ROUNDS)
  const testPatterns = sectionRows(payload, 'hidden_test_failures').map((row) => ({
    label: String(row.failure || row.pattern || row.label || '').trim(),
    count: Number(row.count || 0),
    round_count: Number(row.session_count || row.round_count || 0),
    evidence: [],
  })).filter((row) => row.label && row.count >= MIN_REPEATED_ROUNDS)
  const followupMetrics = sectionRows(payload, 'followup_handling')
  const followUp = followupMetrics.length ? {
    initial_average: numericScore(followupMetrics.find((item) => String(item.label).toLowerCase().includes('main'))?.raw_value),
    followup_average: numericScore(followupMetrics.find((item) => String(item.label).toLowerCase().includes('follow'))?.raw_value),
  } : undefined
  const technicalSummary: Record<string, any> = {}
  sectionRows(payload, 'technical_summary').forEach((item) => {
    technicalSummary[String(item.label).toLowerCase()] = item.raw_value ?? numericScore(item.value) ?? item.value
  })
  const topicAttempts = topics.reduce((total, row) => total + Number(row.problems_attempted || 0), 0)
  const topicSolved = topics.reduce((total, row) => total + Number(row.problems_solved || 0), 0)
  const timeProblems = sectionMetrics(payload, 'coding_progress').flatMap((item) => {
    const label = String(item.label || '').toLowerCase()
    const value = numericScore(item.raw_value ?? item.value)
    if (!label.includes('average runs') || value === null || value >= 2) return []
    return [{ label: 'Runs code too few times before submitting', value, display: `${formatNumber(value)} runs/problem`, explanation: 'The saved coding evidence shows fewer than two validation runs per attempted problem on average.' }]
  })
  return {
    summary: { total_rounds: 0, latest_score: numericScore(payload?.overall_score) },
    skills,
    topics,
    question_types: questionTypes,
    patterns,
    test_patterns: testPatterns,
    follow_up: followUp,
    submission: mode === 'technical' ? {
      problems_attempted: Number(technicalSummary['problems attempted'] || topicAttempts || technicalSummary['prepared rounds'] || 0),
      problems_solved: Number(technicalSummary['problems solved'] ?? topicSolved),
      problems_total: Number(technicalSummary['prepared rounds'] || topicAttempts || 0),
      coded_not_submitted: Number(technicalSummary['coded but not submitted'] || 0),
    } : undefined,
    time: timeProblems,
  }
}

function getAnalytics(payload: DynamicPerformancePayload | null | undefined, mode: PerformanceMode) {
  return payload?.analytics || fallbackAnalytics(payload, mode)
}

function TrendIcon({ direction, className = 'h-4 w-4' }: { direction?: string | null; className?: string }) {
  if (direction === 'up' || direction === 'Improving') return <ArrowUpRight className={`${className} text-emerald-600`} />
  if (direction === 'down' || direction === 'Declining') return <ArrowDownRight className={`${className} text-rose-600`} />
  return null
}

function Section({ title, children, testId }: { title: string; children: ReactNode; testId?: string }) {
  return <section className='dashboard-card' data-testid={testId}><h2 className='mb-5 text-lg font-semibold tracking-tight text-foreground'>{title}</h2>{children}</section>
}

function rowCount(row: Record<string, any>, mode: PerformanceMode) {
  const keys = mode === 'technical' ? ['problems_attempted', 'evidence_count', 'question_count', 'count', 'attempts'] : ['evaluated_questions', 'question_count', 'evidence_count', 'count', 'attempts']
  return keys.map((key) => numericScore(row[key])).find((value): value is number => value !== null) ?? 0
}

function repeatedEvidence(row: Record<string, any>, mode: PerformanceMode) {
  return Number(row.round_count || 0) >= MIN_REPEATED_ROUNDS && rowCount(row, mode) >= MIN_REPEATED_ROUNDS
}

function rowExplanation(row: Record<string, any>, mode: PerformanceMode, kind: 'weak' | 'strong' | 'pattern' | 'problem') {
  const explicit = row.explanation || row.common_issue || row.main_issue || row.description
  if (explicit && kind !== 'strong') return String(explicit)
  const count = rowCount(row, mode)
  const rounds = Number(row.round_count || 0)
  const average = numericScore(row.average_score ?? row.score)
  if (kind === 'strong') {
    const solved = numericScore(row.problems_solved ?? row.success_count)
    if (mode === 'technical' && solved !== null) return `${formatNumber(solved)} of ${formatNumber(count)} attempted problems were solved across ${formatNumber(rounds)} rounds.`
    return `Scored ${formatScore(average)} across ${formatNumber(count)} evaluated answers in ${formatNumber(rounds)} rounds.`
  }
  if (kind === 'pattern') return `Seen ${formatNumber(row.count)} times across ${formatNumber(rounds)} rounds.`
  if (mode === 'technical' && numericScore(row.problems_solved) !== null) return `${formatNumber(row.problems_solved)} of ${formatNumber(count)} attempted problems were solved; the remaining evidence needs review.`
  return average === null ? 'Recorded evidence is available for review.' : `Average ${formatScore(average)} across ${formatNumber(count)} pieces of evidence in ${formatNumber(rounds)} rounds.`
}

function EvidencePanel({ evidence, onOpenReport }: { evidence: Record<string, any>[]; onOpenReport: (item: Record<string, any>) => void }) {
  if (!evidence.length) return null
  return <div className='mt-4 rounded-xl border border-primary/20 bg-primary/[0.04] p-4'><div className='mb-3 flex items-center justify-between gap-3'><p className='text-sm font-semibold text-foreground'>Questions and rounds contributing to this signal</p><span className='text-xs text-muted-foreground'>{evidence.length} item{evidence.length === 1 ? '' : 's'}</span></div><div className='divide-y divide-border/50'>{evidence.slice(0, 12).map((item, index) => <div key={`${item.response_id || item.round_id || item.question || item.problem || index}`} className='flex flex-wrap items-center gap-x-4 gap-y-2 py-2.5 first:pt-0 last:pb-0'><div className='min-w-0 flex-1'><p className='truncate text-sm text-foreground'>{item.question || item.problem || 'Recorded evidence'}</p><p className='mt-0.5 text-xs text-muted-foreground'>{formatShortDate(item.date)}{item.issue ? ` · ${item.issue}` : item.result ? ` · ${item.result}` : ''}{item.round_id ? ` · ${item.round_id}` : ''}</p></div>{numericScore(item.score) !== null ? <span className='text-sm font-semibold text-foreground'>{formatScore(item.score)}</span> : null}{item.interview_id ? <button type='button' onClick={() => onOpenReport(item)} className='inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline'>Report <ExternalLink className='h-3 w-3' /></button> : null}</div>)}</div></div>
}

function DiagnosisList({ rows, mode, kind, countLabel, onOpenReport }: { rows: Record<string, any>[]; mode: PerformanceMode; kind: 'weak' | 'strong' | 'pattern' | 'problem'; countLabel: string; onOpenReport: (item: Record<string, any>) => void }) {
  const [selected, setSelected] = useState<string | null>(null)
  return <div className='divide-y divide-border/50 border-y border-border/60'>{rows.map((row, index) => { const key = `${row.label || 'signal'}-${index}`; const evidence = Array.isArray(row.evidence) ? row.evidence : []; const expanded = selected === key; const count = rowCount(row, mode) || numericScore(row.count) || 0; const rounds = numericScore(row.round_count); const average = numericScore(row.average_score ?? row.score); const meta = [count > 0 ? `${formatNumber(count)} ${countLabel}` : null, rounds !== null && rounds > 0 ? `${formatNumber(rounds)} rounds` : null, average !== null && kind !== 'pattern' ? `${formatScore(average)} average` : null].filter(Boolean).join(' · '); return <div key={key} className='py-4 first:pt-0 last:pb-0'><button type='button' className='flex w-full items-start gap-3 text-left' onClick={() => evidence.length && setSelected(expanded ? null : key)} disabled={!evidence.length} aria-expanded={evidence.length ? expanded : undefined}><div className='min-w-0 flex-1'><p className='text-sm font-semibold leading-6 text-foreground'>{row.label}</p><p className='mt-1 text-sm leading-6 text-muted-foreground'>{rowExplanation(row, mode, kind)}</p>{meta ? <p className='mt-2 text-xs font-medium text-muted-foreground'>{meta}</p> : null}</div>{evidence.length ? <ChevronRight className={`mt-1 h-4 w-4 shrink-0 text-primary transition-transform ${expanded ? 'rotate-90' : ''}`} /> : null}</button>{expanded ? <EvidencePanel evidence={evidence} onOpenReport={onOpenReport} /> : null}</div> })}</div>
}

function DiagnosisSection({ title, rows, mode, kind, countLabel, onOpenReport, testId }: { title: string; rows: Record<string, any>[]; mode: PerformanceMode; kind: 'weak' | 'strong' | 'pattern' | 'problem'; countLabel: string; onOpenReport: (item: Record<string, any>) => void; testId?: string }) {
  if (!rows.length) return null
  return <Section title={title} testId={testId}><DiagnosisList rows={rows} mode={mode} kind={kind} countLabel={countLabel} onOpenReport={onOpenReport} /></Section>
}

function ChangeSection({ title, rows }: { title: string; rows: Record<string, any>[] }) {
  const meaningful = rows.filter((row) => numericScore(row.delta) !== null && Number(row.delta) !== 0)
  if (!meaningful.length) return null
  return <Section title={title}><div className='divide-y divide-border/50 border-y border-border/60'>{meaningful.map((row, index) => <div key={`${row.label}-${index}`} className='flex flex-wrap items-center justify-between gap-3 py-3'><div className='min-w-0'><p className='text-sm font-semibold text-foreground'>{row.label}</p><p className='mt-1 text-xs text-muted-foreground'>{formatDelta(row.delta)}{numericScore(row.round_count) !== null ? ` · ${formatNumber(row.round_count)} rounds` : ''}</p></div><span className='inline-flex items-center gap-1 text-sm font-semibold text-foreground'><TrendIcon direction={title.includes('Worse') ? 'Declining' : 'Improving'} />{numericScore(row.baseline) !== null && numericScore(row.recent) !== null ? `${formatScore(row.baseline)} → ${formatScore(row.recent)}` : ''}</span></div>)}</div></Section>
}

function FollowUpProblems({ followUp, onOpenReport }: { followUp?: Record<string, any>; onOpenReport: (item: Record<string, any>) => void }) {
  const evidence = Array.isArray(followUp?.shallow_followups) ? followUp.shallow_followups : []
  const rounds = new Set(evidence.map((item: Record<string, any>) => item.interview_id).filter(Boolean)).size
  if (evidence.length < MIN_REPEATED_ROUNDS || rounds < MIN_REPEATED_ROUNDS) return null
  return <DiagnosisSection title='Follow-up Problems' mode='interview' kind='problem' countLabel='follow-ups' onOpenReport={onOpenReport} rows={[{ label: 'Deeper follow-ups lose technical depth after a stronger initial answer', count: evidence.length, round_count: rounds, evidence, explanation: 'The follow-up score falls below the paired initial answer in repeated rounds.' }]} />
}

function isBehaviorPattern(row: Record<string, any>) {
  const label = String(row.label || '').toLowerCase()
  return !label.includes('follow-up') && ['answer', 'unanswered', 'vague', 'directly answer', 'missing example', 'evidence', 'ownership'].some((token) => label.includes(token))
}

function AnswerBehavior({ analytics, onOpenReport }: { analytics: PerformanceAnalytics; onOpenReport: (item: Record<string, any>) => void }) {
  const metrics = (analytics.behavior || []).filter((item) => /partial|not answered|unanswered|skipped/i.test(String(item.label || '')) && numericScore(item.value) !== null && Number(item.value) > 0).map((item) => ({ label: item.label, count: Number(item.value), round_count: analytics.summary?.total_rounds, explanation: item.display || String(item.value) }))
  const rows = [...(analytics.patterns || []).filter(isBehaviorPattern), ...metrics]
  return <DiagnosisSection title='Answer Behavior' mode='interview' kind='problem' countLabel='signals' onOpenReport={onOpenReport} rows={rows} />
}

function InterviewDashboard({ analytics, onOpenReport }: { analytics: PerformanceAnalytics; onOpenReport: (item: Record<string, any>) => void }) {
  const patterns = (analytics.patterns || []).filter((row) => !isBehaviorPattern(row) && !String(row.label || '').toLowerCase().includes('follow-up'))
  const topics = analytics.topics || []
  const types = analytics.question_types || []
  const weakTopics = topics.filter((row) => repeatedEvidence(row, 'interview') && (numericScore(row.average_score ?? row.score) ?? 101) <= WEAK_SCORE_THRESHOLD)
  const strongTopics = topics.filter((row) => repeatedEvidence(row, 'interview') && (numericScore(row.average_score ?? row.score) ?? 0) >= STRONG_SCORE_THRESHOLD)
  const questionTypeProblems = types.filter((row) => repeatedEvidence(row, 'interview') && (numericScore(row.average_score ?? row.score) ?? 101) <= WEAK_SCORE_THRESHOLD)
  const improvement = analytics.improvement || {}
  return <div className='space-y-5' data-testid='performance-interview-diagnosis'><DiagnosisSection title='Repeated Mistakes' rows={patterns.filter((row) => Number(row.count || 0) >= MIN_REPEATED_ROUNDS && Number(row.round_count || 0) >= MIN_REPEATED_ROUNDS)} mode='interview' kind='pattern' countLabel='occurrences' onOpenReport={onOpenReport} /><DiagnosisSection title='Weak Topics' rows={weakTopics} mode='interview' kind='weak' countLabel='answers' onOpenReport={onOpenReport} /><DiagnosisSection title='Strong Topics' rows={strongTopics} mode='interview' kind='strong' countLabel='answers' onOpenReport={onOpenReport} /><ChangeSection title='What Is Improving' rows={improvement.improving || []} /><ChangeSection title='What Is Getting Worse' rows={improvement.declining || []} /><DiagnosisSection title='Question Type Problems' rows={questionTypeProblems} mode='interview' kind='problem' countLabel='questions' onOpenReport={onOpenReport} /><FollowUpProblems followUp={analytics.follow_up} onOpenReport={onOpenReport} /><AnswerBehavior analytics={{ ...analytics, patterns: (analytics.patterns || []).filter(isBehaviorPattern) }} onOpenReport={onOpenReport} /></div>
}

function TechnicalSubmissionProblems({ submission, onOpenReport }: { submission?: Record<string, any>; onOpenReport: (item: Record<string, any>) => void }) {
  if (!submission) return null
  const problems = Array.isArray(submission.problems) ? submission.problems : []
  const fallbackCount = numericScore(submission.coded_not_submitted) || 0
  if (!problems.length && !fallbackCount) return null
  const rows = problems.length ? problems.map((item: Record<string, any>) => ({ ...item, label: item.problem || 'Problem without final submission', count: 1, round_count: Number(item.round_count || 1), explanation: `${item.run_count ? `${formatNumber(item.run_count)} runs recorded` : 'Code evidence recorded'}${numericScore(item.time_used_seconds) !== null ? ` · ${formatDuration(item.time_used_seconds)}` : ''} without a final submit.` })) : [{ label: 'Coded problems without a final submission', count: fallbackCount, explanation: `${formatNumber(fallbackCount)} attempted problems have code evidence but no final submission.` }]
  return <DiagnosisSection title='Submission Problems' rows={rows} mode='technical' kind='problem' countLabel='problems' onOpenReport={onOpenReport} />
}

function TechnicalDashboard({ analytics, onOpenReport }: { analytics: PerformanceAnalytics; onOpenReport: (item: Record<string, any>) => void }) {
  const topics = analytics.topics || []
  const weakTopics = topics.filter((row) => repeatedEvidence(row, 'technical') && ((numericScore(row.average_score ?? row.score) ?? 101) <= WEAK_SCORE_THRESHOLD || (numericScore(row.problems_solved) !== null && Number(row.problems_solved) < rowCount(row, 'technical'))))
  const strongTopics = topics.filter((row) => repeatedEvidence(row, 'technical') && ((numericScore(row.average_score ?? row.score) ?? 0) >= STRONG_SCORE_THRESHOLD || (numericScore(row.problems_solved) !== null && Number(row.problems_solved) === rowCount(row, 'technical'))))
  const testPatterns = analytics.test_patterns || []
  const timePatterns: Record<string, any>[] = (analytics.time_patterns || analytics.time || []).map((row: Record<string, any>) => ({ ...row, explanation: row.explanation || row.display }))
  const improvement = analytics.improvement || {}
  return <div className='space-y-5' data-testid='performance-technical-diagnosis'><DiagnosisSection title='Repeated Mistakes' rows={(analytics.patterns || []).filter((row) => Number(row.count || 0) >= MIN_REPEATED_ROUNDS && Number(row.round_count || 0) >= MIN_REPEATED_ROUNDS)} mode='technical' kind='pattern' countLabel='occurrences' onOpenReport={onOpenReport} /><DiagnosisSection title='Weak Topics' rows={weakTopics} mode='technical' kind='weak' countLabel='problems' onOpenReport={onOpenReport} /><DiagnosisSection title='Strong Topics' rows={strongTopics} mode='technical' kind='strong' countLabel='problems' onOpenReport={onOpenReport} /><TechnicalSubmissionProblems submission={analytics.submission} onOpenReport={onOpenReport} /><DiagnosisSection title='Test Failure Patterns' rows={testPatterns.filter((row) => Number(row.count || 0) >= MIN_REPEATED_ROUNDS && (!row.round_count || Number(row.round_count) >= MIN_REPEATED_ROUNDS))} mode='technical' kind='problem' countLabel='failures' onOpenReport={onOpenReport} /><DiagnosisSection title='Time Problems' rows={timePatterns.filter((row) => numericScore(row.value) !== null || row.display)} mode='technical' kind='problem' countLabel='observations' onOpenReport={onOpenReport} /><ChangeSection title='What Is Improving' rows={improvement.improving || []} /><ChangeSection title='What Is Getting Worse' rows={improvement.declining || []} /></div>
}

function hasUsefulAnalytics(analytics: PerformanceAnalytics, mode: PerformanceMode) {
  const improvement = analytics.improvement || {}
  if ((improvement.improving || []).some((row) => numericScore(row.delta) !== null && Number(row.delta) !== 0) || (improvement.declining || []).some((row) => numericScore(row.delta) !== null && Number(row.delta) !== 0)) return true
  if (mode === 'interview') {
    return (analytics.patterns || []).some((row) => Number(row.count || 0) >= MIN_REPEATED_ROUNDS && Number(row.round_count || 0) >= MIN_REPEATED_ROUNDS)
      || (analytics.topics || []).some((row) => repeatedEvidence(row, mode) && numericScore(row.average_score ?? row.score) !== null)
      || (analytics.question_types || []).some((row) => repeatedEvidence(row, mode) && numericScore(row.average_score ?? row.score) !== null)
      || Boolean((analytics.follow_up?.shallow_followups || []).length >= MIN_REPEATED_ROUNDS)
      || (analytics.patterns || []).some(isBehaviorPattern)
  }
  return (analytics.patterns || []).some((row) => Number(row.count || 0) >= MIN_REPEATED_ROUNDS && Number(row.round_count || 0) >= MIN_REPEATED_ROUNDS)
    || (analytics.topics || []).some((row) => repeatedEvidence(row, mode))
    || Boolean(Number(analytics.submission?.coded_not_submitted || 0))
    || (analytics.test_patterns || []).some((row) => Number(row.count || 0) >= MIN_REPEATED_ROUNDS)
    || (analytics.time || []).length > 0
}

function NoPerformanceData({ onOpenPractice, mode, message }: { onOpenPractice: (tab: PracticeTab) => void; mode: PracticeTab; message?: string }) {
  const isInterview = mode === 'interview'
  return <div className='dashboard-card flex min-h-[300px] flex-col items-center justify-center gap-4 text-center'><h3 className='text-base font-semibold text-foreground'>{message || (isInterview ? 'No completed Interview Round yet' : 'No completed Technical Round yet')}</h3><p className='max-w-md text-sm leading-6 text-muted-foreground'>Complete a round to create the evidence-backed diagnosis used by Performance.</p><div className='flex flex-wrap justify-center gap-3'>{isInterview ? <Button className='gap-2' onClick={() => onOpenPractice('interview')}><MessageSquare className='h-4 w-4' /> Take an Interview</Button> : <Button className='gap-2' onClick={() => onOpenPractice('coding')}><Code className='h-4 w-4' /> Start Technical Round</Button>}</div></div>
}

function PerformancePreparingState({ mode, scoreState }: { mode: PerformanceMode; scoreState?: string | null }) {
  const draftOnly = mode === 'technical' && scoreState === 'run_only'
  const insufficient = mode === 'technical' && scoreState === 'insufficient'
  const title = draftOnly
    ? 'No gradable Technical evidence yet'
    : insufficient
    ? 'Not enough Technical evidence yet'
    : 'Performance is being prepared'
  const message = draftOnly
    ? 'Saved code is visible in the round report, but a final submission is required before score-based Technical analytics can be calculated.'
    : insufficient
    ? 'Saved Technical evidence is not enough to calculate a reliable diagnosis yet.'
    : 'Saved round evidence will appear here once repeated, evidence-backed signals are available.'
  return <div className='dashboard-card flex min-h-[220px] flex-col items-center justify-center gap-3 text-center'><Clock3 className='h-7 w-7 text-primary' /><h2 className='text-base font-semibold text-foreground'>{title}</h2><p className='max-w-md text-sm leading-6 text-muted-foreground'>{message}</p></div>
}

function PerformancePage({ data, onOpenPractice }: { data: PerformanceData; onOpenPractice: (tab: PracticeTab) => void }) {
  const router = useRouter()
  const [activeTab, setActiveTab] = useState<PracticeTab>(() => chooseInitialPerformanceTab(data.interview, data.technical, data.history?.legacy || []))
  const mode: PerformanceMode = activeTab === 'coding' ? 'technical' : 'interview'
  const payload = mode === 'technical' ? data.technical : data.interview
  const analytics = getAnalytics(payload, mode)
  const openReport = useCallback((item: Record<string, any>) => {
    if (item.interview_id) router.push(`/interview/${item.interview_id}/report`)
  }, [router])
  const activeHasData = hasPerformanceModeData(payload) || Boolean(payload?.analytics || payload?.has_evidence || payload?.round_history?.length || payload?.sections?.length)
  const useful = hasUsefulAnalytics(analytics, mode)
  return <div className='space-y-5' data-testid='performance-page' data-performance-mode={activeTab} data-performance-state={payload?.score_state || 'unknown'}><SlidingSegmentControl ariaLabel='Performance round type' options={[{ value: 'interview' as const, label: 'Interview Round', icon: <MessageSquare className='h-4 w-4' /> }, { value: 'coding' as const, label: 'Technical Round', icon: <Code className='h-4 w-4' /> }]} value={activeTab} onValueChange={setActiveTab} className='dashboard-segment-tabs w-fit max-w-full gap-1 rounded-full border-0 bg-card p-1.5 shadow-[0_14px_36px_rgba(15,23,42,0.06)] dark:shadow-[0_16px_38px_rgba(0,0,0,0.2)]' buttonClassName='h-10 px-4' shape='pill' />{!activeHasData ? <NoPerformanceData onOpenPractice={onOpenPractice} mode={activeTab} /> : !useful ? <PerformancePreparingState mode={mode} scoreState={payload?.score_state} /> : mode === 'interview' ? <InterviewDashboard analytics={analytics} onOpenReport={openReport} /> : <TechnicalDashboard analytics={analytics} onOpenReport={openReport} />}</div>
}

function isNotFoundPerformanceError(message: string) {
  const lower = message.toLowerCase()
  return lower.includes('not found') || lower.includes('404')
}

export function PerformanceContent({ onOpenPractice }: { onOpenPractice?: (tab: PracticeTab) => void }) {
  const [data, setData] = useState<PerformanceData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [reconcileError, setReconcileError] = useState('')
  const [reconciling, setReconciling] = useState(false)
  const reconcileAttemptedRef = useRef(false)
  const pollingStartedAtRef = useRef(0)

  const loadPerformance = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true)
    setError('')
    try {
      setData(await fetchPerformance())
    } catch (err: any) {
      setError(err?.message || 'Failed to load performance.')
    } finally {
      if (showLoading) setLoading(false)
    }
  }, [])

  const runReconciliation = useCallback(async () => {
    if (reconciling) return
    setReconciling(true)
    setReconcileError('')
    reconcileAttemptedRef.current = true
    pollingStartedAtRef.current = Date.now()
    try {
      let cursor: string | null | undefined = null
      let pageCount = 0
      let exhausted = 0
      do {
        const result = await reconcilePerformance(cursor)
        exhausted += Number(result.retry_exhausted_count || 0)
        cursor = result.next_cursor
        pageCount += 1
      } while (cursor && pageCount < 20)
      if (exhausted) setReconcileError(`${exhausted} analysis job${exhausted === 1 ? '' : 's'} reached the retry limit.`)
      await loadPerformance(false)
    } catch (err: any) {
      reconcileAttemptedRef.current = false
      setReconcileError(err?.message || 'Could not prepare performance analysis.')
    } finally {
      setReconciling(false)
    }
  }, [loadPerformance, reconciling])

  useEffect(() => { void loadPerformance() }, [loadPerformance])

  useEffect(() => {
    const missing = Number(data?.availability?.missing_canonical_count || 0)
    const pending = Number(data?.availability?.pending_count || 0)
    if (!missing && !pending) {
      reconcileAttemptedRef.current = false
      pollingStartedAtRef.current = 0
      return
    }
    if (missing && !reconcileAttemptedRef.current) {
      void runReconciliation()
      return
    }
    if (!pollingStartedAtRef.current) pollingStartedAtRef.current = Date.now()
    const elapsed = Date.now() - pollingStartedAtRef.current
    if (elapsed >= 15 * 60 * 1000) return
    const timer = window.setTimeout(() => { void loadPerformance(false) }, elapsed < 15_000 ? 3_000 : 15_000)
    return () => window.clearTimeout(timer)
  }, [data?.availability?.missing_canonical_count, data?.availability?.pending_count, loadPerformance, runReconciliation])

  const openPractice = (tab: PracticeTab) => {
    if (onOpenPractice) {
      onOpenPractice(tab)
      return
    }
    safeStorageSet('session', 'dashboard_tab', tab)
    window.location.assign(`/?tab=${tab}`)
  }

  const hasAnyData = Boolean(data?.interview?.has_data || data?.technical?.has_data || data?.round_history?.length || data?.history?.legacy?.length)
  const shouldShowNoData = (!data && isNotFoundPerformanceError(error)) || Boolean(data && !hasAnyData)
  const shouldShowError = Boolean(error && !isNotFoundPerformanceError(error))
  const availability = data?.availability
  const stateMessage = availability?.blocked_count
    ? 'Analysis is queued, but the analysis worker is not currently available.'
    : availability?.pending_count || availability?.missing_canonical_count
      ? 'Completed rounds are being converted into evidence-backed Performance. This page refreshes automatically.'
      : availability?.failed_count
        ? 'One or more completed rounds could not be analyzed.'
        : reconcileError
          ? reconcileError
          : ''
  const noDataMessage = availability?.completed_count
    ? availability.blocked_count ? 'Analysis is waiting for the worker service' : availability.pending_count || availability.missing_canonical_count ? 'Performance will appear after analysis finishes' : availability.failed_count ? 'Score analysis failed' : 'No scored rounds'
    : undefined

  return <div className='flex-1 overflow-y-auto p-5 font-sans md:p-6' data-testid='performance-content'>{loading ? <div className='dashboard-card flex min-h-[300px] flex-col items-center justify-center gap-3 text-center'><Loader2 className='h-6 w-6 animate-spin text-primary' /><p className='text-sm text-muted-foreground'>Loading performance...</p></div> : shouldShowError ? <div className='dashboard-card flex min-h-[300px] flex-col items-center justify-center gap-4 text-center'><AlertTriangle className='h-7 w-7 text-amber-500' /><p className='max-w-sm text-sm text-muted-foreground'>{error || 'Unable to load performance.'}</p><Button variant='outline' className='rounded-lg' onClick={() => void loadPerformance(true)}><RefreshCw className='mr-2 h-4 w-4' />Try Again</Button></div> : <div className='space-y-4'>{stateMessage ? <div className='dashboard-card flex flex-wrap items-center justify-between gap-3 border-amber-500/25 bg-amber-500/5'><div className='flex min-w-0 items-start gap-3'>{reconciling || availability?.pending_count ? <Loader2 className='mt-0.5 h-4 w-4 shrink-0 animate-spin text-amber-600' /> : <AlertTriangle className='mt-0.5 h-4 w-4 shrink-0 text-amber-600' />}<p className='text-sm leading-6 text-foreground'>{stateMessage}</p></div>{availability?.failed_count || availability?.blocked_count || reconcileError ? <Button variant='outline' size='sm' disabled={reconciling} onClick={() => { reconcileAttemptedRef.current = false; void runReconciliation() }}>{reconciling ? 'Retrying…' : 'Retry analysis'}</Button> : null}</div> : null}{shouldShowNoData ? <NoPerformanceData onOpenPractice={openPractice} mode='interview' message={noDataMessage} /> : data ? <PerformancePage data={data} onOpenPractice={openPractice} /> : null}</div>}</div>
}
