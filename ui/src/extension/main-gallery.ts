import { QueueSnapshot, showQueueConnectionError, updateMainQueueStatus } from './main-status';

type Completion = { id: string; type: 'txt2img' | 'img2img'; version: string };
type Updates = { cursor: number; tasks: Completion[]; queue: QueueSnapshot };

// Gradio owns the gallery and its metadata. Change a hidden native input instead
// of inserting thumbnails into the DOM, so Save and Send-to keep working.
export function startMainGallerySync() {
  let cursor: number | undefined;
  const tasks = new Map<string, Completion>();
  let timer: number | undefined;
  let polling = false;
  let refreshRequested = false;

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
      updateMainQueueStatus(updates.queue);
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
