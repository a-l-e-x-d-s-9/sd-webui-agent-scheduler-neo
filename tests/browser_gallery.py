"""Run explicitly with Playwright against the isolated Forge server on port 17866."""
import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:17866"


def main():
    report = {"browser_errors": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/opt/google/chrome/chrome",
                                    headless=True, args=["--no-sandbox"])
        page = browser.new_page()
        page.on("pageerror", lambda error: report["browser_errors"].append(str(error)))
        page.goto(BASE, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_function("typeof window.submit_enqueue === 'function'")
        page.wait_for_timeout(1500)  # establish the completion-feed baseline

        def number(field, value):
            control = page.locator(f"#txt2img_{field} input[type=number]")
            control.fill(str(value))
            control.press("Tab")

        def wait_for(predicate, timeout=150):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                value = predicate()
                if value:
                    return value
                page.wait_for_timeout(250)
            page.screenshot(path="/tmp/forge-gallery-failure.png")
            raise AssertionError("Timed out waiting for gallery test condition")

        prompts = ["gallery validation A: a red ceramic teapot",
                   "gallery validation B: a blue ceramic teapot",
                   "gallery validation C: a green ceramic teapot"]
        number("width", 512)
        number("height", 512)
        number("steps", 40)
        page.locator("#txt2img_prompt textarea").fill(prompts[0])
        page.locator("#txt2img_generate").click()
        wait_for(lambda: page.request.get(BASE + "/sdapi/v1/progress?skip_current_image=true").json()["state"]["job_count"] > 0)
        for prompt, steps in zip(prompts[1:], [6, 5]):
            number("steps", steps)
            page.locator("#txt2img_prompt textarea").fill(prompt)
            page.locator("#txt2img_enqueue").click()
            wait_for(lambda: any(t["params"]["prompt"] == prompt for t in
                     page.request.get(BASE + "/agent-scheduler/v1/queue").json()["pending_tasks"]), 30)

        def gallery_ready():
            text = page.locator("#generation_info_txt2img textarea").input_value()
            info = json.loads(text or "{}")
            if report.get("last_gallery_versions") != info.get("agent_scheduler_gallery_versions", []):
                report["last_gallery_versions"] = info.get("agent_scheduler_gallery_versions", [])
                print("Gallery completion versions:", report["last_gallery_versions"], flush=True)
            return info if len(info.get("agent_scheduler_gallery_versions", [])) == 2 else None

        info = wait_for(gallery_ready)
        assert info["all_prompts"] == prompts, info
        assert len(info["infotexts"]) == len(info["all_seeds"]) == 3
        assert all(prompt in infotext for prompt, infotext in zip(prompts, info["infotexts"]))
        # Gradio renders both its preview strip and a separate grid thumbnail set.
        thumbnails = page.locator("#txt2img_gallery .thumbnail-item.thumbnail-small")
        wait_for(lambda: thumbnails.count() == 3, 20)
        for index, prompt in enumerate(prompts):
            thumbnails.nth(index).click()
            wait_for(lambda: prompt in page.locator("#html_info_txt2img").inner_text(), 15)
        # More feed polls must not append the same jobs twice.
        page.wait_for_timeout(2500)
        assert thumbnails.count() == 3
        assert not report["browser_errors"], report["browser_errors"]
        report.update(prompts=info["all_prompts"], seeds=info["all_seeds"],
                      gallery_images=3, queue_versions=info["agent_scheduler_gallery_versions"],
                      selection_metadata="passed", duplicate_poll="passed")
        page.screenshot(path="/tmp/forge-gallery-success.png")
        browser.close()
    target = Path(__file__).resolve().parents[1] / "gallery-browser-validation.json"
    target.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
