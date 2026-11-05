import { QueueSnapshot, showQueueConnectionError, updateMainQueueStatus } from './main-status';

type Completion = { id: string; type: 'txt2img' | 'img2img'; version: string };
type Updates = { cursor: number; tasks: Completion[]; queue?: QueueSnapshot };

// Existing Forge processes keep their imported Python modules until restart.
// This fallback lets the frontend update without stopping a running batch.
function legacyQueueReader() {
  let knownId: string | null = null;
  let active: { type: string; status: string } | null = null;
  return async (): Promise<QueueSnapshot> => {
    const response = await fetch('./agent-scheduler/v1/queue');
    if (!response.ok) throw new Error(`Queue status: HTTP ${response.status}`);
    const queue = await response.json() as {
      current_task_id: string | null; total_pending_tasks: number; paused: boolean;
      pending_tasks: { id: string; type: string; status: string }[];
    };
    if (knownId !== queue.current_task_id) {
      knownId = queue.current_task_id;
      active = null;
      if (knownId != null) {
        const task = await fetch(`./agent-scheduler/v1/task/${encodeURIComponent(knownId)}`);
        if (task.ok) {
          const data = await task.json();
          active = data.success ? data.data : null;
        }
      }
    }
    const listed = queue.pending_tasks.find(t => t.id === queue.current_task_id);
    const type = listed?.type ?? active?.type;
    const runningPending = listed != null || active?.status === 'pending';
    return { current_task_id: queue.current_task_id,
      current_task_type: type === 'txt2img' || type === 'img2img' ? type : null,
      pending_tasks: Math.max(0, queue.total_pending_tasks - (runningPending ? 1 : 0)),
      paused: queue.paused };
  };
}

// Gradio owns the gallery and its metadata. Change a hidden native input instead
// of inserting thumbnails into the DOM, so Save and Send-to keep working.
export function startMainGallerySync() {
  let cursor: number | undefined;
  const tasks = new Map<string, Completion>();
  let timer: number | undefined;
  let polling = false;
  let refreshRequested = false;
  const readLegacyQueue = legacyQueueReader();

  const poll = async () => {
    if (polling) {
      refreshRequested = true;
      return;
    }
    polling = true;
    window.clearTimeout(timer);
    try {
      const query = cursor == null ? '' : `?since=${cursor}`;
      const response = await fetch(`./agent-scheduler/v1/gallery-updates${query}`);
      if (!response.ok) throw new Error(`Gallery updates: HTTP ${response.status}`);
      const updates = (await response.json()) as Updates;
      updateMainQueueStatus(updates.queue ?? await readLegacyQueue());
      const changed = new Set<Completion['type']>();
      for (const task of updates.tasks) {
        if (!tasks.has(task.version)) {
          tasks.set(task.version, task);
          changed.add(task.type);
        }
      }
      for (const mode of changed) {
        const input = gradioApp().querySelector<HTMLTextAreaElement>(
          `#agent_scheduler_${mode}_gallery_updates textarea`
        );
        if (input == null) continue;
        input.value = JSON.stringify([...tasks.values()].filter(t => t.type === mode));
        input.dispatchEvent(new Event('input', { bubbles: true }));
      }
      cursor = updates.cursor;
    } catch (error) {
      console.warn('[AgentScheduler] Main gallery sync will retry', error);
      showQueueConnectionError();
    } finally {
      polling = false;
      timer = window.setTimeout(poll, refreshRequested ? 0 : 1000);
      refreshRequested = false;
    }
  };
  window.addEventListener('agent-scheduler-refresh', () => { void poll(); });
  void poll();
}
