import ast
import importlib.util
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from typing import Optional

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gallery_helpers", ROOT / "agent_scheduler/gallery.py")
gallery_helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gallery_helpers)


class MainGalleryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.paths = [str(Path(self.temp.name) / f"image{i}.png") for i in range(4)]
        for path in self.paths:
            Image.new("RGB", (4, 4)).save(path)

    def result(self, paths, prompt, seeds):
        return {"images": paths, "geninfo": {
            "prompt": prompt, "negative_prompt": "negative " + prompt,
            "seed": seeds[0], "all_seeds": seeds,
            "all_prompts": [prompt] * len(seeds),
            "all_negative_prompts": ["negative " + prompt] * len(seeds),
            "infotexts": [f"{prompt}, seed {seed}" for seed in seeds],
            "index_of_first_image": 0,
        }}

    def test_append_preserves_existing_images_and_metadata(self):
        first = self.result([self.paths[0]], "first", [11])
        second = self.result(self.paths[1:3], "second", [22, 23])
        images, info, selected = gallery_helpers.merge_gallery_results(
            [self.paths[0]], first["geninfo"], [("second:v1", second)])
        self.assertEqual(images, self.paths[:3])
        self.assertEqual(selected, 1)
        self.assertEqual(info["all_seeds"], [11, 22, 23])
        self.assertEqual(info["all_prompts"], ["first", "second", "second"])
        self.assertEqual(info["infotexts"], ["first, seed 11", "second, seed 22", "second, seed 23"])
        self.assertNotIn("agent_scheduler_gallery_versions", first["geninfo"])

    def test_repeated_poll_does_not_duplicate_images(self):
        result = self.result(self.paths[:1], "queued", [11])
        images, info, _ = gallery_helpers.merge_gallery_results([], {}, [("v1", result)])
        self.assertIsNone(gallery_helpers.merge_gallery_results(images, info, [("v1", result)]))
        images, info, _ = gallery_helpers.merge_gallery_results(images, info, [("v1", result), ("v2", result)])
        self.assertEqual(len(images), 2)
        self.assertEqual(info["agent_scheduler_gallery_versions"], ["v1", "v2"])

    def test_missing_files_do_not_shift_image_metadata(self):
        result = self.result([self.paths[0], "/nonexistent/queue-test.png", self.paths[2]], "test", [1, 2, 3])
        images, info, _ = gallery_helpers.merge_gallery_results([], {}, [("v1", result)])
        self.assertEqual(images, [self.paths[0], self.paths[2]])
        self.assertEqual(info["all_seeds"], [1, 3])
        self.assertEqual(info["infotexts"], ["test, seed 1", "test, seed 3"])

    def test_grid_and_sample_seed_indices_stay_aligned(self):
        result = self.result(self.paths[:3], "grid test", [7, 8])
        result["geninfo"].update(index_of_first_image=1,
                                 infotexts=["grid", "sample7", "sample8"])
        _, info, _ = gallery_helpers.merge_gallery_results([], {}, [("v1", result)])
        self.assertEqual(info["all_seeds"], [7, 7, 8])
        self.assertEqual(info["index_of_first_image"], 0)
        self.assertEqual(info["infotexts"], ["grid", "sample7", "sample8"])

    def test_no_available_images_leaves_gallery_unchanged(self):
        result = self.result(["/nonexistent/queue-test.png"], "test", [1])
        self.assertIsNone(gallery_helpers.merge_gallery_results([], {}, [("v1", result)]))

    def test_completion_query_is_inclusive_and_excludes_pending_tasks(self):
        from enum import Enum
        from sqlalchemy import create_engine, Column, String, Integer, DateTime, text
        from sqlalchemy.orm import declarative_base, Session
        base = declarative_base()
        class TaskTable(base):
            __tablename__ = "task"
            id = Column(String, primary_key=True)
            type = Column(String)
            updated_at = Column(DateTime(timezone=True))
            priority = Column(Integer)
            status = Column(String)
        class TaskStatus(str, Enum):
            DONE = "done"
        engine = create_engine("sqlite://")
        base.metadata.create_all(engine)
        when = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)
        with Session(engine) as s:
            for id, delta, status in [("old", -2, "done"), ("done", 0, "done"), ("pending", 0, "pending")]:
                s.add(TaskTable(id=id, type="txt2img", updated_at=when+timedelta(seconds=delta),
                                priority=1, status=status))
            s.commit()
            # SQLite's datetime('now') default stores seconds without .000000.
            s.execute(text("INSERT INTO task VALUES (:id, :type, :updated, :priority, :status)"),
                      dict(id="raw", type="txt2img", updated=when.strftime("%Y-%m-%d %H:%M:%S"),
                           priority=2, status="done"))
            s.commit()
        tree = ast.parse((ROOT / "agent_scheduler/db/task.py").read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "TaskManager")
        fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "get_gallery_updates")
        ns = dict(datetime=datetime, timedelta=timedelta, Session=Session, TaskTable=TaskTable, TaskStatus=TaskStatus)
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "completion query", "exec"), ns)
        updates = ns["get_gallery_updates"](SimpleNamespace(engine=engine), when)
        self.assertCountEqual([u["id"] for u in updates], ["done", "raw"])

    def test_queue_count_excludes_the_running_job(self):
        from enum import Enum
        from sqlalchemy import create_engine, Column, String, func
        from sqlalchemy.orm import declarative_base, Session
        base = declarative_base()
        class TaskTable(base):
            __tablename__ = "task"
            id = Column(String, primary_key=True)
            type = Column(String)
            status = Column(String)
        class TaskStatus(str, Enum):
            PENDING = "pending"
        engine = create_engine("sqlite://")
        base.metadata.create_all(engine)
        with Session(engine) as s:
            s.add_all([TaskTable(id="active", type="txt2img", status="pending"),
                       TaskTable(id="waiting", type="img2img", status="pending"),
                       TaskTable(id="old", type="txt2img", status="done")])
            s.commit()
        tree = ast.parse((ROOT / "agent_scheduler/db/task.py").read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "TaskManager")
        fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "get_queue_snapshot")
        ns = dict(Session=Session, TaskTable=TaskTable, TaskStatus=TaskStatus, func=func)
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "queue snapshot", "exec"), ns)
        snapshot = ns["get_queue_snapshot"]
        manager = SimpleNamespace(engine=engine)
        active = snapshot(manager, "active")
        self.assertEqual(active["pending_tasks"], 1)
        self.assertEqual(active["current_task_type"], "txt2img")
        native = snapshot(manager, "normal-generate")
        self.assertEqual(native["pending_tasks"], 2)
        self.assertIsNone(native["current_task_type"])
        paused = snapshot(manager, None, True)
        self.assertEqual(paused["pending_tasks"], 2)
        self.assertTrue(paused["paused"])


if __name__ == "__main__":
    unittest.main()
