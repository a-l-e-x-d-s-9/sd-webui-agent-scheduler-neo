import { ProgressResponse } from './types';

export type QueueSnapshot = {
  current_task_id: string | null;
  current_task_type: 'txt2img' | 'img2img' | null;
  pending_tasks: number;
  paused: boolean;
};

declare global {
  function showSubmitButtons(mode: string, show: boolean): void;
}

type Mode = 'txt2img' | 'img2img';
let active: { id: string; mode: Mode; progress?: ProgressResponse } | undefined;
let snapshot: QueueSnapshot | undefined;

function badge(mode: Mode) {
  const id = `agent_scheduler_${mode}_queue_count`;
  let element = gradioApp().querySelector<HTMLElement>(`#${id}`);
  if (element == null) {
    const button = gradioApp().querySelector(`#${mode}_enqueue`);
    if (button == null) return null;
    element = document.createElement('span');
    element.id = id;
    element.className = 'agent-scheduler-queue-count';
    element.setAttribute('role', 'status');
    element.setAttribute('aria-live', 'polite');
    button.insertAdjacentElement('afterend', element);
  }
  return element;
}

function render() {
  if (snapshot == null) return;
  for (const mode of ['txt2img', 'img2img'] as const) {
    const element = badge(mode);
    if (element == null) continue;
    let text = `${snapshot.pending_tasks} queued`;
    let state = snapshot.paused ? 'paused' : 'idle';
    if (active?.mode === mode) {
      const progress = active.progress;
      const percent = progress?.progress ? ` ${Math.round(progress.progress * 100)}%` : '';
      const eta = progress?.eta ? ` · ETA ${Math.ceil(progress.eta)}s` : '';
      text = `Generating${percent}${eta} · ${text}`;
      state = 'generating';
    } else if (snapshot.paused) {
      text = `Paused · ${text}`;
    } else if (snapshot.pending_tasks > 0 && snapshot.current_task_id == null) {
      text = `Waiting · ${text}`;
      state = 'waiting';
    }
    element.textContent = text;
    element.dataset.queueCount = String(snapshot.pending_tasks);
    element.dataset.state = state;
    element.dataset.taskId = active?.mode === mode ? active.id : '';
  }
}

function refresh() {
  window.dispatchEvent(new Event('agent-scheduler-refresh'));
}

function track(id: string, mode: Mode) {
  active = { id, mode };
  render();
  const app = gradioApp();
  const container = app.querySelector<HTMLElement>(`#${mode}_gallery_container`);
  const gallery = app.querySelector<HTMLElement>(`#${mode}_gallery`);
  if (container == null || gallery == null) return;
  showSubmitButtons(mode, false);
  requestProgress(id, container, gallery, () => {
    // An older job finishing must not hide the next job's Interrupt/progress UI.
    if (active?.id === id) {
      active = undefined;
      showSubmitButtons(mode, true);
      render();
    }
    refresh();
  }, progress => {
    if (active?.id === id) {
      active.progress = progress;
      render();
    }
  });
  const scheduler = app.querySelector<HTMLElement>('#agent_scheduler_current_task_images');
  if (scheduler != null) requestProgress(id, scheduler, scheduler, () => {});
}

export function updateMainQueueStatus(value: QueueSnapshot) {
  snapshot = value;
  const { current_task_id: id, current_task_type: mode } = value;
  if (id != null && mode != null) {
    if (active?.id !== id) {
      if (active != null && active.mode !== mode) showSubmitButtons(active.mode, true);
      track(id, mode);
    }
  } else if (active != null) {
    const previous = active;
    active = undefined;
    // Leave a normal Generate job's own controls to Forge.
    if (id == null) showSubmitButtons(previous.mode, true);
  }
  render();
}

export function showQueueConnectionError() {
  for (const mode of ['txt2img', 'img2img'] as const) {
    const element = badge(mode);
    if (element != null) element.textContent = 'Queue status reconnecting…';
  }
}
