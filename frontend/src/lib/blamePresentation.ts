import { formatError, type BlameResult, type Span, type TraceDetail } from './api';

function findSpan(spans: Span[] | undefined, spanId: string | null | undefined): Span | null {
  if (!spans || !spanId) return null;
  return spans.find((span) => span.span_id === spanId) ?? null;
}

function hasNullLikeOutput(span: Span | null): boolean {
  return Boolean(span && (span.output == null || span.output === ''));
}

function hasNullLikeInput(span: Span | null): boolean {
  return Boolean(span && (span.input == null || span.input === ''));
}

function classifyConfidence(score: number | null | undefined, label: string | null | undefined): string {
  if (label) return label;
  if (score == null) return 'not available';
  if (score >= 0.8) return 'high';
  if (score >= 0.5) return 'medium';
  return 'low';
}

export interface BlameExplanation {
  rootCause: string;
  failurePoint: string;
  executionPath: string;
  impact: string;
  summary: string;
  suggestedFixes: string[];
  confidence: string;
  replayGuidance: string;
}

export function buildBlameExplanation(
  blame: BlameResult | null,
  trace?: TraceDetail | null,
  spansArg?: Span[] | null,
): BlameExplanation | null {
  if (!blame || blame.originators.length === 0) return null;

  const rootCause = blame.originators[0];
  const failurePoint = blame.failure_points[0] ?? null;
  const spans = spansArg ?? trace?.spans;
  const rootSpan = findSpan(spans, rootCause.span_id);
  const failureSpan = findSpan(spans, failurePoint?.span_id);
  const chain = blame.full_chain.map((span) => {
    if (span.span_id === rootCause.span_id) return `${span.name} ❌`;
    if (failurePoint && span.span_id === failurePoint.span_id) return `${span.name} ⚠️`;
    return span.name;
  });

  const executionPath =
    chain.length > 0 ? chain.join(' → ') : `${rootCause.span_name} ❌`;

  const rootCauseText = `❌ ${rootCause.span_name} is the most likely root cause${rootCause.reason ? `: ${rootCause.reason}` : '.'}`;

  let failurePointText = '⚠️ Failure point not available.';
  if (failurePoint) {
    const visibleIssue = failureSpan?.error
      ? formatError(failureSpan.error)
      : hasNullLikeInput(failureSpan)
        ? 'received null or empty input from upstream'
        : hasNullLikeOutput(failureSpan)
          ? 'returned null or empty output downstream'
          : failurePoint.reason || 'propagated the upstream failure';

    failurePointText = `❌ ${failurePoint.span_name} is where the failure became visible downstream: ${visibleIssue}.`;
  }

  let impact = 'Impact is not available.';
  if (failureSpan?.error) {
    impact = `The failure caused a downstream exception in ${failurePoint?.span_name ?? 'the affected span'}.`;
  } else if (hasNullLikeInput(failureSpan)) {
    impact = `The failure propagated as null or empty input into ${failurePoint?.span_name ?? 'a downstream step'}.`;
  } else if (hasNullLikeOutput(rootSpan)) {
    impact = `The root-cause step produced null or empty output, which degraded downstream execution.`;
  } else if (rootSpan?.error) {
    impact = `The root-cause step threw an exception and interrupted downstream processing.`;
  } else if (trace?.status === 'error') {
    impact = 'The trace ended in an error state after the failure propagated downstream.';
  }

  const summary = failurePoint
    ? `${rootCause.span_name} introduced the failure, and ${failurePoint.span_name} is where it became visible downstream.`
    : `${rootCause.span_name} is the most likely root cause, and it impacted downstream execution.`;

  const suggestedFixes: string[] = [];
  if (rootSpan?.error || failureSpan?.error) {
    suggestedFixes.push('Add explicit exception handling and clear error propagation around the failing span.');
  }
  if (hasNullLikeOutput(rootSpan) || hasNullLikeInput(failureSpan)) {
    suggestedFixes.push('Validate null or empty inputs and outputs before passing data to downstream spans.');
  }
  if (rootSpan?.latency_ms != null && rootSpan.latency_ms > 2000) {
    suggestedFixes.push('Review timeout and retry settings for the slow span to prevent timeout-related failures.');
  }
  if (rootSpan?.span_type === 'tool' || rootSpan?.span_type === 'retrieval') {
    suggestedFixes.push(`Add fallback behavior for ${rootSpan.span_type} failures so downstream steps can continue safely.`);
  }
  if (suggestedFixes.length === 0) {
    suggestedFixes.push('Replay the failing span with validated inputs to confirm whether the issue is deterministic.');
    suggestedFixes.push('Add input and output guards around the affected spans to stop bad data from propagating.');
  }

  const confidenceScore = rootCause.blame_score ?? null;
  const confidenceLabel = classifyConfidence(confidenceScore, blame.confidence);
  const confidence = confidenceScore != null
    ? `${confidenceScore.toFixed(2)} (${confidenceLabel})`
    : 'Not available';

  let replayGuidance = 'Not available';
  if (hasNullLikeOutput(rootSpan)) {
    replayGuidance = `Replay ${rootCause.span_name} with stricter output validation or a fallback response when output is null.`;
  } else if (hasNullLikeInput(failureSpan)) {
    replayGuidance = `Replay ${failurePoint?.span_name ?? rootCause.span_name} with a validated upstream payload to confirm the null-input path.`;
  } else if (rootSpan?.latency_ms != null && rootSpan.latency_ms > 2000) {
    replayGuidance = `Replay ${rootCause.span_name} with a smaller input or adjusted timeout settings to verify whether latency caused the failure.`;
  } else if (rootSpan?.error) {
    replayGuidance = `Replay ${rootCause.span_name} with the same input after adding defensive validation around the failing operation.`;
  }

  return {
    rootCause: rootCauseText,
    failurePoint: failurePointText,
    executionPath,
    impact,
    summary,
    suggestedFixes: suggestedFixes.slice(0, 4),
    confidence,
    replayGuidance,
  };
}
