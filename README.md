# Agent Scheduler Neo

Queue prompts and settings while Forge Neo is generating, follow queued jobs from
the main tab, and keep their completed images together in the main gallery.

This fork builds on [cataclisma's Neo port](https://github.com/cataclisma/sd-webui-agent-scheduler-neo),
[supersonic13's Forge support](https://github.com/supersonic13/sd-webui-agent-scheduler),
and the original [Agent Scheduler](https://github.com/SipherAGI/sd-webui-agent-scheduler).

## Features

- Enqueue a complete snapshot of prompts, generation settings and extension states
  without waiting for the current GPU job to finish.
- See native progress, live previews and Interrupt controls on the main generation
  tab for each queued job, without opening Agent Scheduler first.
- See the number of waiting tasks beside Enqueue, with generating and paused states.
  The count excludes the task currently running.
- Append completed txt2img/img2img results to their main galleries, preserving
  per-image prompts, seeds and infotext when selecting or saving images.
- Keep Agent Scheduler's queue editing, history, bookmarks and API functionality.

## Compatibility

Tested with **Forge Neo 2.31** and **Gradio 4.40.0**. The extension handles Neo's
five-output generation results, current img2img image layers, and ControlNet and
ADetailer state capture. Compatibility with other Forge versions and every
third-party extension is not guaranteed.

## Install

In Forge's **Extensions → Install from URL**, use:

```text
https://github.com/a-l-e-x-d-s-9/sd-webui-agent-scheduler-neo.git
```

Or clone from the Forge directory:

```sh
git clone https://github.com/a-l-e-x-d-s-9/sd-webui-agent-scheduler-neo.git extensions/sd-webui-agent-scheduler-neo
```

Install only one Agent Scheduler extension. When replacing another version, back
up its directory and `task_scheduler.sqlite3` first, move the old extension outside
`extensions`, and copy the database to the replacement if retaining its history.
Alternatively, retain a custom `--agent-scheduler-sqlite-file` location.

Restart Forge when it is idle, then refresh the browser. Old queued tasks created
before a Forge or extension update may contain obsolete script-argument layouts;
recreate those tasks if they fail.

## Use

Start a generation normally. Edit the next prompt and settings, then click
**Enqueue**. The badge shows how many jobs are waiting. Queued generation progress
and previews appear automatically on the matching main tab, including when you
open the page while a queued job is already running.

Completed images append to the current main gallery while the page is open. A
fresh page watches new completions; older results remain in Agent Scheduler's
history. Global queue counts appear beside both Enqueue buttons.

## Development and testing

Run backend regression tests with Forge's Python environment:

```sh
python -m unittest discover -s tests -v
```

Build the checked-in frontend assets with Node.js 20.19 or newer:

```sh
cd ui
npm ci
npx tsc --noEmit
npm run build:extension
```

The explicit Playwright checks in `tests/browser_gallery.py` and
`tests/browser_progress.py` require an isolated Forge server and a browser. They
generate test images; do not point them at a live queue. The progress test verifies
main-tab previews and controls across consecutive jobs, queue-count changes, paused
state, and attaching a fresh page to an already-running queue.

## License

Apache License 2.0. Upstream attribution and bundled third-party notices are retained.
