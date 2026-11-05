"""Regression tests; run with Forge's venv Python and unittest discover -s tests.

Load the affected definitions without booting Forge or opening the user's DB.
Gradio itself is real so event registration and dependency chaining are checked.
"""
import ast
import contextlib
import inspect
import logging
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from uuid import uuid4
from typing import Dict, List, Union

import gradio as gr
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def definitions(path, names, namespace):
    tree = ast.parse((ROOT / path).read_text())
    tree.body = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    exec(compile(tree, str(path), "exec"), namespace)
    return namespace


def script_namespace():
    ns = dict(gr=gr, List=List, uuid4=uuid4, log=logging.getLogger("test"),
              scripts=SimpleNamespace(Script=object),
              checkpoint_current="Current Checkpoint", checkpoint_runtime="Runtime Checkpoint",
              queue_with_every_checkpoints="$$_queue_with_all_checkpoints_$$",
              select_checkpoint=lambda: SimpleNamespace(title="current.safetensors"),
              list_checkpoint_tiles=lambda: ["current.safetensors"])
    ns.update(definitions("agent_scheduler/helpers.py", {
        "_extract_target_id", "get_default_config_dependencies", "get_components_by_ids",
        "compare_components_with_ids"}, dict(gr=gr, List=List, Block=gr.blocks.Block,
                                             BlockContext=gr.blocks.BlockContext)))
    return definitions("scripts/task_scheduler.py", {"Script"}, ns)


class EnqueueTests(unittest.TestCase):
    def test_real_gradio_captures_all_inputs_after_state_producers(self):
        ns = script_namespace()
        for is_img2img in (False, True):
            with self.subTest(is_img2img=is_img2img), gr.Blocks() as root:
                generate = gr.Button("Generate")
                enqueue = gr.Button("Enqueue")
                checkpoint, task_id, prompt = gr.Dropdown(["model"]), gr.Textbox(), gr.Textbox()
                setting = gr.Slider(value=3)
                state1, state2 = gr.State({}), gr.State({})
                outputs = [gr.Textbox() for _ in range(5)]
                generate.click(lambda s: {"value": s}, setting, state1, queue=False)
                generate.click(lambda p: {"prompt": p}, prompt, state2, queue=False)
                inputs = [task_id, prompt, setting, state1, state2]
                generate.click(lambda *a: ["result"] * 5, inputs, outputs)
                # A submit event on the same component must not become a click producer.
                s = ns["Script"]()
                s.generate_button, s.submit_button, s.checkpoint_dropdown = generate, enqueue, checkpoint
                s.is_img2img = is_img2img
                s.gallery_updates = gr.Textbox(visible=False)
            # Forge binds on app_started, after the UI Blocks context has closed.
            with self.subTest(is_img2img=is_img2img):
                s.bind_enqueue_button(root)
                events = root.get_config_file()["dependencies"]
                chain = [e for e in events if e["targets"] == [(enqueue._id, "click")]]
                self.assertEqual(len(chain), 1)
                first = chain[0]
                second = next(e for e in events if e["trigger_after"] == first["id"])
                final = next(e for e in events if e["trigger_after"] == second["id"])
                self.assertEqual(first["outputs"], [state1._id])
                self.assertEqual(second["outputs"], [state2._id])
                self.assertEqual(final["inputs"], [checkpoint._id] + [c._id for c in inputs])
                self.assertFalse(any(e["queue"] for e in (first, second, final)))
                self.assertIn("submit_enqueue_img2img" if is_img2img else "submit_enqueue", final["js"])
                gallery_event = next(e for e in events if e["api_name"].startswith("sync_main_gallery"))
                self.assertEqual(gallery_event["outputs"], [c._id for c in outputs])
                self.assertEqual(gallery_event["inputs"], [s.gallery_updates._id, outputs[0]._id, outputs[2]._id])
                self.assertEqual(gallery_event["trigger_mode"], "always_last")
                self.assertFalse(gallery_event["queue"])

    def test_named_tasks_keep_the_generation_task_id_and_checkpoint(self):
        ns = script_namespace()
        ns["task_runner"] = runner = Mock()
        s = ns["Script"]()
        s.is_img2img = False
        request = SimpleNamespace(username="test")
        s.wrap_register_ui_task()(request, "chosen.safetensors", "my task", "prompt", "negative")
        call = runner.register_ui_task.call_args
        self.assertEqual(call.args[2:], ("my task", "prompt", "negative"))
        self.assertEqual(call.kwargs["checkpoint"], "chosen.safetensors")
        self.assertEqual(call.kwargs["task_name"], "my task")

    def test_registration_failure_is_reported(self):
        ns = script_namespace()
        ns["task_runner"] = Mock()
        ns["task_runner"].register_ui_task.side_effect = ValueError("broken snapshot")
        s = ns["Script"]()
        s.is_img2img = False
        with self.assertLogs("test", level="ERROR"):
            with self.assertRaisesRegex(ValueError, "broken snapshot"):
                s.wrap_register_ui_task()(None, "Current Checkpoint", "task(test)", "prompt")

    def test_neo_and_legacy_result_layouts(self):
        ns = dict(gr=gr, BaseModel=object, Any=object, Callable=object, Union=Union,
                  Optional=__import__('typing').Optional, List=List, Dict=Dict,
                  Task=object, TaskStatus=object, ParsedTaskArgs=object)
        # Only the execution method is needed; avoid evaluating unrelated classes.
        tree = ast.parse((ROOT / "agent_scheduler/task_runner.py").read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "TaskRunner")
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__execute_ui_task")
        ns.update(queue_lock=contextlib.nullcontext(), shared=SimpleNamespace(state=Mock()),
                  progress=Mock(), img2img=Mock(), txt2img=Mock(), OutOfMemoryError=RuntimeError)
        exec(compile(ast.Module(body=[method], type_ignores=[]), "runner", "exec"), ns)
        for result in ([{}, None, '{"prompt":"neo"}', "info", "log"],
                       [{}, '{"prompt":"a1111"}', "info", "log"]):
            ns["wrap_gradio_call"] = lambda *a, **kw: lambda *args: result
            self.assertEqual(ns["__execute_ui_task"](None, "task(test)", False),
                             result[2] if len(result) == 5 else result[1])

    def test_factory_signature_keeps_prompts_separate_from_scripts(self):
        def wrapper(id_task, request, *args): pass
        def factory(id_task, request, prompt, negative_prompt, override_settings_texts, *args): pass
        ns = dict(inspect=inspect, List=List, Dict=Dict,
                  txt2img=SimpleNamespace(txt2img=wrapper, txt2img_create_processing=factory),
                  img2img=SimpleNamespace(img2img=wrapper, img2img_function=factory),
                  shared=SimpleNamespace(opts=SimpleNamespace()), sd_samplers=SimpleNamespace())
        definitions("agent_scheduler/task_helpers.py", {"get_ui_task_function",
                    "map_ui_task_args_list_to_named_args", "map_named_args_to_ui_task_args_list"}, ns)
        for mode in (False, True):
            named, script = ns["map_ui_task_args_list_to_named_args"](
                ["task(test)", "prompt", "negative", [], 0, "extension setting"], mode)
            self.assertEqual(named["prompt"], "prompt")
            self.assertEqual(script, [0, "extension setting"])
            self.assertEqual(ns["map_named_args_to_ui_task_args_list"](named, script, mode),
                             ["task(test)", None, "prompt", "negative", [], 0, "extension setting"])

    def test_img2img_layers_and_legacy_masks_round_trip(self):
        image = Image.new("RGBA", (4, 4), "red")
        ns = dict(Dict=Dict)
        tree = ast.parse((ROOT / "agent_scheduler/task_helpers.py").read_text())
        assignment = next(n for n in tree.body if isinstance(n, ast.AnnAssign)
                          and n.target.id == "img2img_image_args_by_mode")
        exec(compile(ast.Module(body=[assignment], type_ignores=[]), "images", "exec"), dict(ns, List=List), ns)
        # Use a small reversible codec to verify traversal and legacy/Neo shapes.
        ns.update(serialize_image=lambda im: {"cls": "Image", "value": im} if isinstance(im, Image.Image) else im,
                  deserialize_image=lambda im: im["value"] if isinstance(im, dict) and "cls" in im else im)
        definitions("agent_scheduler/task_helpers.py", {"serialize_img2img_image_args",
                    "deserialize_img2img_image_args"}, ns)
        for mode, key, foreground in [(0, "init_img", None), (1, "sketch", "sketch_fg"),
                                      (2, "init_img_with_mask", "init_img_with_mask_fg"),
                                      (3, "inpaint_color_sketch", "inpaint_color_sketch_fg")]:
            args = dict(mode=mode, **{key: image})
            if foreground: args[foreground] = image
            ns["serialize_img2img_image_args"](args)
            ns["deserialize_img2img_image_args"](args)
            self.assertIs(args[key], image)
            if foreground: self.assertIs(args[foreground], image)
        args = dict(mode=2, init_img_with_mask=dict(image=image, mask=image))
        ns["serialize_img2img_image_args"](args)
        ns["deserialize_img2img_image_args"](args)
        self.assertIs(args["init_img_with_mask"]["image"], image)
        self.assertIs(args["init_img_with_mask"]["mask"], image)


if __name__ == "__main__":
    unittest.main()
