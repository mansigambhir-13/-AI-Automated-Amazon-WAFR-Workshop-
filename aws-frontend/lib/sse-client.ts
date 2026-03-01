import { BACKEND_URL, authHeaders } from './api';

export interface SSECallbacks {
  onRunStarted?: (sessionId: string, runId: string) => void;
  onStepStarted?: (step: string) => void;
  onStepFinished?: (step: string, result?: Record<string, unknown>) => void;
  onStateSnapshot?: (state: Record<string, unknown>) => void;
  onStateDelta?: (patches: Array<{ op: string; path: string; value: unknown }>) => void;
  onProgress?: (step: string, percentage: number, message: string) => void;
  onTextMessage?: (text: string) => void;
  onRunFinished?: (sessionId: string) => void;
  onRunError?: (error: string, code?: string) => void;
}

export interface StartAssessmentParams {
  transcript: string;
  clientName: string;
  generateReport?: boolean;
  threadId?: string;
}

/**
 * Start a WAFR assessment via SSE streaming.
 *
 * POST /api/wafr/run returns a text/event-stream response.
 * Each event is `data: {...json...}\n\n`.
 */
export function startAssessment(
  params: StartAssessmentParams,
  callbacks: SSECallbacks,
): { abort: () => void } {
  const controller = new AbortController();

  const url = `${BACKEND_URL}/api/wafr/run`;
  const body = JSON.stringify({
    transcript: params.transcript,
    client_name: params.clientName,
    generate_report: params.generateReport ?? true,
    thread_id: params.threadId,
  });

  // Use fetch for SSE since we need POST (EventSource only supports GET)
  (async () => {
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
        body,
        signal: controller.signal,
      });

      if (!response.ok) {
        if (response.status === 401) {
          callbacks.onRunError?.('Session expired — please log in again');
          if (typeof window !== 'undefined') {
            window.location.href = '/';
          }
          return;
        }
        const errorText = await response.text().catch(() => '');
        callbacks.onRunError?.(`HTTP ${response.status}: ${errorText || response.statusText}`);
        return;
      }

      const reader = response.body?.getReader();
      if (!reader) {
        callbacks.onRunError?.('No response body');
        return;
      }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Parse SSE events from buffer
        const lines = buffer.split('\n');
        buffer = lines.pop() || ''; // Keep incomplete line in buffer

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed || trimmed.startsWith(':')) continue; // Skip empty lines and comments

          if (trimmed.startsWith('data: ')) {
            const jsonStr = trimmed.slice(6);
            try {
              const event = JSON.parse(jsonStr);
              handleSSEEvent(event, callbacks);
            } catch {
              // Not valid JSON, might be partial — skip
            }
          }
        }
      }
    } catch (err: unknown) {
      if ((err as Error).name === 'AbortError') return;
      callbacks.onRunError?.(err instanceof Error ? err.message : 'SSE connection failed');
    }
  })();

  return {
    abort: () => controller.abort(),
  };
}

function handleSSEEvent(
  event: Record<string, unknown>,
  callbacks: SSECallbacks,
): void {
  const type = event.type as string;

  switch (type) {
    case 'RUN_STARTED':
      callbacks.onRunStarted?.(
        event.threadId as string || event.thread_id as string || '',
        event.runId as string || event.run_id as string || '',
      );
      break;

    case 'STEP_STARTED':
      callbacks.onStepStarted?.(event.stepName as string || event.step as string || '');
      break;

    case 'STEP_FINISHED':
      callbacks.onStepFinished?.(
        event.stepName as string || event.step as string || '',
        event.result as Record<string, unknown> | undefined,
      );
      break;

    case 'STATE_SNAPSHOT':
      callbacks.onStateSnapshot?.(event.snapshot as Record<string, unknown> || event as Record<string, unknown>);
      break;

    case 'STATE_DELTA':
      callbacks.onStateDelta?.(event.delta as Array<{ op: string; path: string; value: unknown }> || []);
      break;

    case 'TEXT_MESSAGE_CONTENT':
      callbacks.onTextMessage?.(event.delta as string || event.text as string || '');
      break;

    case 'RUN_FINISHED':
      callbacks.onRunFinished?.(event.threadId as string || event.thread_id as string || '');
      break;

    case 'RUN_ERROR':
      callbacks.onRunError?.(
        event.message as string || event.error as string || 'Unknown error',
        event.code as string | undefined,
      );
      break;

    default:
      // Unknown event type — log for debugging
      if (typeof window !== 'undefined') {
        console.debug('[SSE] Unknown event type:', type, event);
      }
  }
}
