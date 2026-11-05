"""Explicit integration check against an isolated Forge server, never the live UI."""
import argparse
import json
import shutil
import time
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:17866")
    parser.add_argument("--browser", default=shutil.which("google-chrome"))
    parser.add_argument("--output", default="/tmp/forge-progress-validation.json")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    report = {"browser_errors": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=args.browser, headless=True,
                                    args=["--no-sandbox"])
        page = browser.new_page()
        page.on("pageerror", lambda e: report["browser_errors"].append(str(e)))
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_selector("#agent_scheduler_txt2img_queue_count")

        def wait_for(predicate, timeout=180):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                value = predicate()
                if value:
                    return value
                page.wait_for_timeout(150)
            page.screenshot(path="/tmp/forge-progress-failure.png")
            raise AssertionError("Timed out waiting for progress test condition")

        def queue():
            return page.request.get(base + "/agent-scheduler/v1/queue").json()

        def number(field, value):
            control = page.locator(f"#txt2img_{field} input[type=number]")
            control.fill(str(value))
            control.press("Tab")

        badge = page.locator("#agent_scheduler_txt2img_queue_count")
        page.request.post(base + "/agent-scheduler/v1/queue/pause")
        number("width", 512)
        number("height", 512)
        number("steps", 40)
        prompts = ["progress test A: a red ceramic teapot",
                   "progress test B: a blue ceramic teapot",
                   "progress test C: a green ceramic teapot"]
        page.locator("#txt2img_prompt textarea").fill(prompts[0])
        page.locator("#txt2img_generate").click()
        wait_for(lambda: page.request.get(base + "/sdapi/v1/progress?skip_current_image=true")
                 .json()["state"]["job_count"] > 0)
        for index, prompt in enumerate(prompts[1:], 1):
            page.locator("#txt2img_prompt textarea").fill(prompt)
            page.locator("#txt2img_enqueue").click()
            wait_for(lambda: queue()["total_pending_tasks"] == index, 30)
            wait_for(lambda: badge.get_attribute("data-queue-count") == str(index), 15)
        assert "Paused" in badge.inner_text()
        report["paused_queue_count"] = badge.inner_text()
        wait_for(lambda: not queue()["current_task_id"] and
                 page.request.get(base + "/sdapi/v1/progress?skip_current_image=true")
                 .json()["state"]["job_count"] == 0)
        tasks = queue()["pending_tasks"]
        ids = [t["id"] for t in tasks]
        assert len(ids) == 2
        page.request.post(base + "/agent-scheduler/v1/queue/resume")

        wait_for(lambda: badge.get_attribute("data-task-id") == ids[0])
        assert "Generating" in badge.inner_text()
        assert badge.get_attribute("data-queue-count") == "1"
        assert page.locator("#txt2img_interrupt").is_visible()
        wait_for(lambda: page.locator("#txt2img_gallery .livePreview img").count() > 0, 60)
        report["first_queued_progress"] = badge.inner_text()

        # A fresh main-tab page must attach to a running queue without opening
        # Agent Scheduler. The original page keeps its combined gallery.
        second = browser.new_page()
        second.on("pageerror", lambda e: report["browser_errors"].append(str(e)))
        second.goto(base, wait_until="domcontentloaded")
        second.wait_for_function("document.querySelector('#agent_scheduler_txt2img_queue_count')?.dataset.state === 'generating'")
        second.wait_for_selector("#txt2img_gallery .livePreview img", timeout=60000)
        assert second.locator("#txt2img_interrupt").is_visible()
        report["fresh_page_progress"] = "passed"
        second.close()

        wait_for(lambda: badge.get_attribute("data-task-id") == ids[1])
        assert "Generating" in badge.inner_text()
        assert badge.get_attribute("data-queue-count") == "0"
        assert page.locator("#txt2img_interrupt").is_visible()
        wait_for(lambda: page.locator("#txt2img_gallery .livePreview img").count() > 0, 60)
        report["second_queued_progress"] = badge.inner_text()

        def gallery_ready():
            info = json.loads(page.locator("#generation_info_txt2img textarea").input_value() or "{}")
            return info if len(info.get("agent_scheduler_gallery_versions", [])) == 2 else None

        info = wait_for(gallery_ready)
        wait_for(lambda: badge.get_attribute("data-state") == "idle")
        assert badge.get_attribute("data-queue-count") == "0"
        assert page.locator("#txt2img_generate").is_visible()
        assert info["all_prompts"] == prompts
        assert not report["browser_errors"], report["browser_errors"]
        assert page.get_by_role("tab", name="txt2img", exact=True).get_attribute("aria-selected") == "true"
        report.update(main_tab_only="passed", transitions="passed", gallery_images=3,
                      idle_status=badge.inner_text())
        page.screenshot(path="/tmp/forge-progress-success.png")
        browser.close()
    Path(args.output).write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
