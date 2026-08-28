'use client'

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { AlertTriangle, ArrowDownRight, ArrowUpRight, ChevronRight, Clock3, Code, Loader2, MessageSquare, RefreshCw } from 'lucide-react'

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
    evidence: row.evidence_ids || row.evidence_id ? [{ interview_id: row.interview_id, evidence_id: row.evidence_id, evidence_ids: row.evidence_ids }] : [],
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
  if (explicit) return String(explicit)
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

function EvidencePanel({ evidence }: { evidence: Record<string, any>[] }) {
  if (!evidence.length) return null
  return <div className='mt-4 rounded-xl border border-primary/20 bg-primary/[0.035] p-4'>
    <div className='mb-3 flex items-center justify-between gap-3'><p className='text-sm font-semibold text-foreground'>Evidence combined from reports</p><span className='text-xs text-muted-foreground'>{evidence.length} item{evidence.length === 1 ? '' : 's'}</span></div>
    <div className='divide-y divide-border/50'>
      {evidence.slice(0, 12).map((item, index) => <div key={`${item.response_id || item.round_id || item.question || item.problem || index}`} className='flex flex-wrap items-center gap-x-4 gap-y-2 py-2.5 first:pt-0 last:pb-0'>
        <div className='min-w-0 flex-1'>
          <p className='text-sm font-medium text-foreground'>{item.source_label || item.question || item.problem || 'Recorded report evidence'}</p>
          {item.detail ? <p className='mt-1 text-sm leading-6 text-muted-foreground'>{item.detail}</p> : null}
          {item.what_happened && item.what_happened !== item.detail ? <p className='mt-1 text-xs leading-5 text-muted-foreground'><span className='font-medium text-foreground'>What happened:</span> {item.what_happened}</p> : null}
          <p className='mt-1 text-xs text-muted-foreground'>{formatShortDate(item.date)}{item.role ? ` · ${item.role}` : ''}{item.issue ? ` · ${item.issue}` : item.result ? ` · ${item.result}` : ''}</p>
        </div>
        {numericScore(item.score) !== null ? <span className='text-sm font-semibold text-foreground'>{formatScore(item.score)}</span> : null}
      </div>)}
    </div>
  </div>
}

function DiagnosisList({ rows, mode, kind, countLabel }: { rows: Record<string, any>[]; mode: PerformanceMode; kind: 'weak' | 'strong' | 'pattern' | 'problem'; countLabel: string }) {
  const [selected, setSelected] = useState<string | null>(null)
  return <div className='divide-y divide-border/50 border-y border-border/60'>
    {rows.map((row, index) => {
      const key = `${row.label || 'signal'}-${index}`
      const evidence = Array.isArray(row.evidence) ? row.evidence : []
      const expanded = selected === key
      const count = rowCount(row, mode) || numericScore(row.count) || 0
      const rounds = numericScore(row.round_count)
      const average = numericScore(row.average_score ?? row.score)
      const multiReportPrefix = kind === 'strong' ? 'Seen across ' : 'Recurring across '
      const meta = [count > 0 ? `${formatNumber(count)} ${countLabel}` : null, rounds !== null && rounds > 0 ? `${rounds >= MIN_REPEATED_ROUNDS ? multiReportPrefix : ''}${formatNumber(rounds)} report${rounds === 1 ? '' : 's'}` : null, average !== null && kind !== 'pattern' ? `${formatScore(average)} average` : null].filter(Boolean).join(' · ')
      return <div key={key} className='py-4 first:pt-0 last:pb-0'>
        <button type='button' className='flex w-full items-start gap-3 text-left' onClick={() => evidence.length && setSelected(expanded ? null : key)} disabled={!evidence.length} aria-expanded={evidence.length ? expanded : undefined}>
          <div className='min-w-0 flex-1'><p className='text-sm font-semibold leading-6 text-foreground'>{row.label}</p><p className='mt-1 text-sm leading-6 text-muted-foreground'>{rowExplanation(row, mode, kind)}</p>{row.why_it_matters ? <p className='mt-1 text-sm leading-6 text-muted-foreground'><span className='font-medium text-foreground'>Why it matters:</span> {row.why_it_matters}</p> : null}{meta ? <p className='mt-2 text-xs font-medium text-muted-foreground'>{meta}</p> : null}</div>
          {evidence.length ? <ChevronRight className={`mt-1 h-4 w-4 shrink-0 text-primary transition-transform ${expanded ? 'rotate-90' : ''}`} /> : null}
        </button>
        {expanded ? <EvidencePanel evidence={evidence} /> : null}
      </div>
    })}
  </div>
}

function DiagnosisSection({ title, rows, mode, kind, countLabel, testId }: { title: string; rows: Record<string, any>[]; mode: PerformanceMode; kind: 'weak' | 'strong' | 'pattern' | 'problem'; countLabel: string; testId?: string }) {
  if (!rows.length) return null
  return <Section title={title} testId={testId}><DiagnosisList rows={rows} mode={mode} kind={kind} countLabel={countLabel} /></Section>
}

function ChangeSection({ title, rows }: { title: string; rows: Record<string, any>[] }) {
  const meaningful = rows.filter((row) => numericScore(row.delta) !== null && Number(row.delta) !== 0)
  if (!meaningful.length) return null
  return <Section title={title}><div className='divide-y divide-border/50 border-y border-border/60'>{meaningful.map((row, index) => <div key={`${row.label}-${index}`} className='flex flex-wrap items-center justify-between gap-3 py-3'><div className='min-w-0'><p className='text-sm font-semibold text-foreground'>{row.label}</p><p className='mt-1 text-xs text-muted-foreground'>{formatDelta(row.delta)}{numericScore(row.round_count) !== null ? ` · ${formatNumber(row.round_count)} rounds` : ''}</p></div><span className='inline-flex items-center gap-1 text-sm font-semibold text-foreground'><TrendIcon direction={title.includes('Worse') ? 'Declining' : 'Improving'} />{numericScore(row.baseline) !== null && numericScore(row.recent) !== null ? `${formatScore(row.baseline)} → ${formatScore(row.recent)}` : ''}</span></div>)}</div></Section>
}

function FollowUpProblems({ followUp }: { followUp?: Record<string, any> }) {
  const evidence = Array.isArray(followUp?.shallow_followups) ? followUp.shallow_followups : []
  const rounds = new Set(evidence.map((item: Record<string, any>) => item.interview_id).filter(Boolean)).size
  if (evidence.length < MIN_REPEATED_ROUNDS || rounds < MIN_REPEATED_ROUNDS) return null
  return <DiagnosisSection title='Follow-up Problems' mode='interview' kind='problem' countLabel='follow-ups' rows={[{ label: 'Deeper follow-ups lose technical depth after a stronger initial answer', count: evidence.length, round_count: rounds, evidence, explanation: 'The follow-up score falls below the paired initial answer in repeated reports.' }]} />
}

function isBehaviorPattern(row: Record<string, any>) {
  const label = String(row.label || '').toLowerCase()
  return !label.includes('follow-up') && ['answer', 'unanswered', 'vague', 'directly answer', 'missing example', 'evidence', 'ownership'].some((token) => label.includes(token))
}

function AnswerBehavior({ analytics }: { analytics: PerformanceAnalytics }) {
  const metrics = (analytics.behavior || []).filter((item) => /partial|not answered|unanswered|skipped/i.test(String(item.label || '')) && numericScore(item.value) !== null && Number(item.value) > 0).map((item) => ({ label: item.label, count: Number(item.value), round_count: analytics.summary?.total_rounds, explanation: item.display || String(item.value) }))
  const rows = [...(analytics.patterns || []).filter(isBehaviorPattern), ...metrics]
  return <DiagnosisSection title='Answer Behavior' mode='interview' kind='problem' countLabel='signals' rows={rows} />
}

function InterviewDashboard({ analytics }: { analytics: PerformanceAnalytics }) {
  const patterns = (analytics.patterns || []).filter((row) => !isBehaviorPattern(row) && !String(row.label || '').toLowerCase().includes('follow-up'))
  const recurringPatterns = (analytics.report_findings?.issues || []).length ? [] : patterns.filter((row) => Number(row.count || 0) >= MIN_REPEATED_ROUNDS && Number(row.round_count || 0) >= MIN_REPEATED_ROUNDS)
  const topics = analytics.topics || []
  const types = analytics.question_types || []
  const weakTopics = topics.filter((row) => repeatedEvidence(row, 'interview') && (numericScore(row.average_score ?? row.score) ?? 101) <= WEAK_SCORE_THRESHOLD)
  const strongTopics = topics.filter((row) => repeatedEvidence(row, 'interview') && (numericScore(row.average_score ?? row.score) ?? 0) >= STRONG_SCORE_THRESHOLD)
  const questionTypeProblems = types.filter((row) => repeatedEvidence(row, 'interview') && (numericScore(row.average_score ?? row.score) ?? 101) <= WEAK_SCORE_THRESHOLD)
  const improvement = analytics.improvement || {}
  return <div className='space-y-5' data-testid='performance-interview-diagnosis'><DiagnosisSection title='Recurring Issues Across Reports' rows={recurringPatterns} mode='interview' kind='pattern' countLabel='occurrences' /><DiagnosisSection title='Weak Topics' rows={weakTopics} mode='interview' kind='weak' countLabel='answers' /><DiagnosisSection title='Strong Topics' rows={strongTopics} mode='interview' kind='strong' countLabel='answers' /><ChangeSection title='What Is Improving' rows={improvement.improving || []} /><ChangeSection title='What Is Getting Worse' rows={improvement.declining || []} /><DiagnosisSection title='Question Type Problems' rows={questionTypeProblems} mode='interview' kind='problem' countLabel='questions' /><FollowUpProblems followUp={analytics.follow_up} /><AnswerBehavior analytics={{ ...analytics, patterns: (analytics.patterns || []).filter(isBehaviorPattern) }} /></div>
}

function TechnicalSubmissionProblems({ submission }: { submission?: Record<string, any> }) {
  if (!submission) return null
  const rawProblems = Array.isArray(submission.problems) ? submission.problems : []
  const groupedProblems = new Map<string, Record<string, any> & { _reportKeys: Set<string> }>()
  rawProblems.forEach((item: Record<string, any>, index: number) => {
    const label = String(item.problem || 'Problem without final submission').trim()
    const groupKey = label.toLowerCase()
    const reportKey = String(item.interview_id || item.round_id || `${groupKey}-${index}`)
    const existing = groupedProblems.get(groupKey)
    if (!existing) {
      groupedProblems.set(groupKey, { ...item, problem: label, _reportKeys: new Set([reportKey]), evidence: Array.isArray(item.evidence) ? item.evidence : [] })
      return
    }
    existing._reportKeys.add(reportKey)
    existing.run_count = Math.max(Number(existing.run_count || 0), Number(item.run_count || 0))
    existing.time_used_seconds = Math.max(Number(existing.time_used_seconds || 0), Number(item.time_used_seconds || 0))
    const seenEvidence = new Set((existing.evidence || []).map((entry: Record<string, any>) => `${entry.interview_id || ''}:${entry.round_id || ''}:${entry.problem || ''}`))
    for (const entry of Array.isArray(item.evidence) ? item.evidence : []) {
      const key = `${entry.interview_id || ''}:${entry.round_id || ''}:${entry.problem || ''}`
      if (!seenEvidence.has(key)) {
        existing.evidence.push(entry)
        seenEvidence.add(key)
      }
    }
  })
  const problems = Array.from(groupedProblems.values()).map(({ _reportKeys, ...item }) => ({ ...item, count: _reportKeys.size, round_count: Math.max(_reportKeys.size, Number(item.round_count || 0)) }))
  const fallbackCount = numericScore(submission.coded_not_submitted) || 0
  if (!problems.length && !fallbackCount) return null
  const rows = problems.length ? problems.map((item: Record<string, any>) => ({ ...item, label: item.problem || 'Problem without final submission', explanation: `${item.run_count ? `${formatNumber(item.run_count)} runs recorded` : 'Code evidence recorded'}${Number(item.time_used_seconds || 0) > 0 ? ` · ${formatDuration(item.time_used_seconds)}` : ''} without a final submit.` })) : [{ label: 'Coded problems without a final submission', count: fallbackCount, explanation: `${formatNumber(fallbackCount)} attempted problems have code evidence but no final submission.` }]
  return <DiagnosisSection title='Submission Problems' rows={rows} mode='technical' kind='problem' countLabel='problems' />
}

function isTechnicalConceptWeakness(row: Record<string, any>) {
  if (String(row.issue_kind || '').toLowerCase() === 'concept') return true
  const issue = String(row.common_issue || row.main_issue || row.explanation || '').toLowerCase()
  if (!issue) return false
  const executionOnly = /incomplete|not submitted|no final|compil|runtime|test failure|edge case|no evidence/.test(issue)
  const conceptual = /wrong approach|incorrect approach|algorithm choice|pattern recognition|data structure|complexity|concept|reasoning|logic/.test(issue)
  return conceptual && !executionOnly
}

function TechnicalDashboard({ analytics }: { analytics: PerformanceAnalytics }) {
  const topics = analytics.topics || []
  const recurringPatterns = (analytics.report_findings?.issues || []).length ? [] : (analytics.patterns || []).filter((row) => Number(row.count || 0) >= MIN_REPEATED_ROUNDS && Number(row.round_count || 0) >= MIN_REPEATED_ROUNDS)
  const weakTopics = topics.filter((row) => repeatedEvidence(row, 'technical') && isTechnicalConceptWeakness(row) && ((numericScore(row.average_score ?? row.score) ?? 101) <= WEAK_SCORE_THRESHOLD || (numericScore(row.problems_solved) !== null && Number(row.problems_solved) < rowCount(row, 'technical'))))
  const strongTopics = topics.filter((row) => repeatedEvidence(row, 'technical') && ((numericScore(row.average_score ?? row.score) ?? 0) >= STRONG_SCORE_THRESHOLD || (numericScore(row.problems_solved) !== null && Number(row.problems_solved) === rowCount(row, 'technical'))))
  const testPatterns = analytics.test_patterns || []
  const timePatterns: Record<string, any>[] = (analytics.time_patterns || analytics.time || []).map((row: Record<string, any>) => ({ ...row, explanation: row.explanation || row.display }))
  const improvement = analytics.improvement || {}
  return <div className='space-y-5' data-testid='performance-technical-diagnosis'><DiagnosisSection title='Recurring Issues Across Reports' rows={recurringPatterns} mode='technical' kind='pattern' countLabel='occurrences' /><DiagnosisSection title='Weak Topics' rows={weakTopics} mode='technical' kind='weak' countLabel='problems' /><DiagnosisSection title='Strong Topics' rows={strongTopics} mode='technical' kind='strong' countLabel='problems' /><TechnicalSubmissionProblems submission={analytics.submission} /><DiagnosisSection title='Test Failure Patterns' rows={testPatterns.filter((row) => Number(row.count || 0) >= MIN_REPEATED_ROUNDS && (!row.round_count || Number(row.round_count) >= MIN_REPEATED_ROUNDS))} mode='technical' kind='problem' countLabel='failures' /><DiagnosisSection title='Time Problems' rows={timePatterns.filter((row) => numericScore(row.value) !== null || row.display)} mode='technical' kind='problem' countLabel='observations' /><ChangeSection title='What Is Improving' rows={improvement.improving || []} /><ChangeSection title='What Is Getting Worse' rows={improvement.declining || []} /></div>
}

function hasUsefulAnalytics(analytics: PerformanceAnalytics, mode: PerformanceMode) {
  const reportFindings = analytics.report_findings
  if (Number(reportFindings?.summary?.total_reports || analytics.summary?.total_reports || analytics.summary?.total_rounds || 0) > 0 || (reportFindings?.issues || []).length > 0 || (reportFindings?.strengths || []).length > 0) return true
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

function CombinedOverview({ analytics, mode }: { analytics: PerformanceAnalytics; mode: PerformanceMode }) {
  const findings = analytics.report_findings
  const summary = findings?.summary || {}
  const totalReports = Number(summary.total_reports ?? analytics.summary?.total_reports ?? analytics.summary?.total_rounds ?? 0)
  if (!totalReports) return null
  const comparableReports = Number(analytics.summary?.total_rounds || 0)
  const evidenceCount = Number(summary.issue_count || 0) + Number(summary.strength_count || 0)
  const label = mode === 'technical' ? 'Technical Round' : 'Interview Round'
  const reportDerived = Boolean(findings)
  return <Section title='Combined Performance' testId='performance-combined-overview'>
    <p className='max-w-3xl text-sm leading-6 text-foreground'>{findings?.takeaway || `Saved evidence from ${totalReports} ${label} round${totalReports === 1 ? '' : 's'} is visible while the combined report analysis is prepared.`}</p>
    <p className='mt-2 max-w-3xl text-xs leading-5 text-muted-foreground'>Open an individual report from the {label} tab. Performance stays combined and does not replace the report history.</p>
    <div className='mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4'>
      <div className='rounded-lg border border-border/70 bg-muted/20 p-3'><p className='text-xs text-muted-foreground'>{reportDerived ? 'Reports combined' : 'Rounds with saved evidence'}</p><p className='mt-1 text-lg font-semibold text-foreground'>{totalReports}</p></div>
      {Number(summary.reports_with_findings || 0) > 0 ? <div className='rounded-lg border border-border/70 bg-muted/20 p-3'><p className='text-xs text-muted-foreground'>Reports with findings</p><p className='mt-1 text-lg font-semibold text-foreground'>{summary.reports_with_findings}</p></div> : null}
      {evidenceCount > 0 ? <div className='rounded-lg border border-border/70 bg-muted/20 p-3'><p className='text-xs text-muted-foreground'>Grounded findings</p><p className='mt-1 text-lg font-semibold text-foreground'>{evidenceCount}</p></div> : null}
      {comparableReports > 0 && comparableReports !== totalReports ? <div className='rounded-lg border border-border/70 bg-muted/20 p-3'><p className='text-xs text-muted-foreground'>Reports in score trend</p><p className='mt-1 text-lg font-semibold text-foreground'>{comparableReports}</p></div> : null}
      {numericScore(analytics.summary?.recent_change) !== null ? <div className='rounded-lg border border-border/70 bg-muted/20 p-3'><p className='text-xs text-muted-foreground'>Recent official change</p><p className='mt-1 inline-flex items-center gap-1 text-lg font-semibold text-foreground'><TrendIcon direction={Number(analytics.summary?.recent_change) > 0 ? 'Improving' : Number(analytics.summary?.recent_change) < 0 ? 'Declining' : 'Stable'} />{formatDelta(analytics.summary?.recent_change)}</p></div> : null}
    </div>
  </Section>
}

function CombinedReportFindings({ analytics, mode }: { analytics: PerformanceAnalytics; mode: PerformanceMode }) {
  const issues = analytics.report_findings?.issues || []
  const strengths = analytics.report_findings?.strengths || []
  if (!issues.length && !strengths.length) return null
  return <div className='space-y-5' data-testid='performance-combined-findings'>
    <DiagnosisSection title='Where You Need Work' rows={issues} mode={mode} kind='problem' countLabel='findings' testId='performance-combined-issues' />
    <DiagnosisSection title='What Is Going Well' rows={strengths} mode={mode} kind='strong' countLabel='findings' testId='performance-combined-strengths' />
  </div>
}

function PerformancePage({ data, onOpenPractice }: { data: PerformanceData; onOpenPractice: (tab: PracticeTab) => void }) {
  const [activeTab, setActiveTab] = useState<PracticeTab>(() => chooseInitialPerformanceTab(data.interview, data.technical, data.history?.legacy || []))
  const mode: PerformanceMode = activeTab === 'coding' ? 'technical' : 'interview'
  const payload = mode === 'technical' ? data.technical : data.interview
  const analytics = getAnalytics(payload, mode)
  const activeHasData = hasPerformanceModeData(payload) || Boolean(payload?.analytics || payload?.has_evidence || payload?.round_history?.length || payload?.sections?.length)
  const useful = hasUsefulAnalytics(analytics, mode)
  return <div className='space-y-5' data-testid='performance-page' data-performance-mode={activeTab} data-performance-state={payload?.score_state || 'unknown'}>
    <SlidingSegmentControl ariaLabel='Performance round type' options={[{ value: 'interview' as const, label: 'Interview Round', icon: <MessageSquare className='h-4 w-4' /> }, { value: 'coding' as const, label: 'Technical Round', icon: <Code className='h-4 w-4' /> }]} value={activeTab} onValueChange={setActiveTab} className='dashboard-segment-tabs w-fit max-w-full gap-1 rounded-full border-0 bg-card p-1.5 shadow-[0_14px_36px_rgba(15,23,42,0.06)] dark:shadow-[0_16px_38px_rgba(0,0,0,0.2)]' buttonClassName='h-10 px-4' shape='pill' />
    {!activeHasData ? <NoPerformanceData onOpenPractice={onOpenPractice} mode={activeTab} /> : useful ? <><CombinedOverview analytics={analytics} mode={mode} /><CombinedReportFindings analytics={analytics} mode={mode} />{mode === 'interview' ? <InterviewDashboard analytics={analytics} /> : <TechnicalDashboard analytics={analytics} />}</> : null}
  </div>
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
      do {
        const result = await reconcilePerformance(cursor)
        cursor = result.next_cursor
        pageCount += 1
      } while (cursor && pageCount < 20)
      await loadPerformance(false)
    } catch (err: any) {
      reconcileAttemptedRef.current = false
      setReconcileError(err?.message || 'Could not prepare the saved report evidence for Performance.')
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
    const pollingWindowMs = Math.max(1, Number(data?.availability?.processing_sla_minutes || 60)) * 60 * 1000
    if (elapsed >= pollingWindowMs) return
    const timer = window.setTimeout(() => { void loadPerformance(false) }, elapsed < 15_000 ? 3_000 : 15_000)
    return () => window.clearTimeout(timer)
  }, [data?.availability?.missing_canonical_count, data?.availability?.pending_count, data?.availability?.processing_sla_minutes, loadPerformance, runReconciliation])

  const openPractice = (tab: PracticeTab) => {
    if (onOpenPractice) {
      onOpenPractice(tab)
      return
    }
    safeStorageSet('session', 'dashboard_tab', tab)
    window.location.assign(`/?tab=${tab}`)
  }

  const hasAnyData = Boolean(data?.interview?.has_data || data?.technical?.has_data || data?.round_history?.length || data?.history?.legacy?.length)
  const availability = data?.availability
  const waitingForAnalysis = Boolean(availability?.completed_count && (availability?.pending_count || availability?.missing_canonical_count || availability?.blocked_count))
  const waitingWithoutData = Boolean(waitingForAnalysis && !hasAnyData)
  const shouldShowNoData = (!data && isNotFoundPerformanceError(error)) || Boolean(data && !hasAnyData && !waitingForAnalysis)
  const shouldShowError = Boolean(error && !isNotFoundPerformanceError(error))
  const stateMessage = availability?.blocked_count
    ? 'Saved report evidence is waiting for the analysis worker. Existing findings remain unchanged until it resumes.'
    : availability?.pending_count || availability?.missing_canonical_count
      ? 'One or more completed reports are still being analyzed. Existing report-backed findings remain visible and refresh automatically.'
      : availability?.failed_count
        ? 'One or more completed reports could not be analyzed from their saved evidence.'
        : reconcileError
          ? reconcileError
          : ''
  const noDataMessage = availability?.completed_count
    ? 'No scored rounds yet'
    : undefined

  return <div className='flex-1 overflow-y-auto p-5 font-sans md:p-6' data-testid='performance-content'>{loading ? <div className='dashboard-card flex min-h-[300px] flex-col items-center justify-center gap-3 text-center'><Loader2 className='h-6 w-6 animate-spin text-primary' /><p className='text-sm text-muted-foreground'>Loading performance...</p></div> : shouldShowError ? <div className='dashboard-card flex min-h-[300px] flex-col items-center justify-center gap-4 text-center'><AlertTriangle className='h-7 w-7 text-amber-500' /><p className='max-w-sm text-sm text-muted-foreground'>{error || 'Unable to load performance.'}</p><Button variant='outline' className='rounded-lg' onClick={() => void loadPerformance(true)}><RefreshCw className='mr-2 h-4 w-4' />Try Again</Button></div> : <div className='space-y-4'>
    {stateMessage ? <div className='dashboard-card flex flex-wrap items-center justify-between gap-3 border-amber-500/25 bg-amber-500/5'><div className='flex min-w-0 items-start gap-3'>{reconciling || availability?.pending_count ? <Loader2 className='mt-0.5 h-4 w-4 shrink-0 animate-spin text-amber-600' /> : <AlertTriangle className='mt-0.5 h-4 w-4 shrink-0 text-amber-600' />}<p className='text-sm leading-6 text-foreground'>{stateMessage}</p></div>{availability?.failed_count || availability?.blocked_count || reconcileError ? <Button variant='outline' size='sm' disabled={reconciling} onClick={() => { reconcileAttemptedRef.current = false; void runReconciliation() }}>{reconciling ? 'Retrying…' : 'Retry analysis'}</Button> : null}</div> : null}
    {waitingWithoutData ? <div className='dashboard-card flex min-h-[240px] flex-col items-center justify-center gap-3 text-center'><Clock3 className='h-7 w-7 text-primary' /><h2 className='text-base font-semibold text-foreground'>Building Performance from your saved reports</h2><p className='max-w-md text-sm leading-6 text-muted-foreground'>Your round evidence is saved. Performance will appear when its canonical report analysis is ready.</p></div> : shouldShowNoData ? <NoPerformanceData onOpenPractice={openPractice} mode='interview' message={noDataMessage} /> : data ? <PerformancePage data={data} onOpenPractice={openPractice} /> : null}
  </div>}</div>
}
