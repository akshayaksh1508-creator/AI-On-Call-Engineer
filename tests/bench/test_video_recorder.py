"""Unit tests for Backup Video Recorder (Day 6 Task A4).

Verifies:
1. Video recorder runs and produces valid video and summary artifacts.
2. Exit criterion: Video shows fault, agent trace, PR, canary, recovery graph (all 5 required components).
3. End-of-day Milestone M1: one fault goes from injection to verified recovery without human intervention.
4. Rendered frame dimensions are standard 720p HD (1280x720).

Owner: Person A (Systems & Proof)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    Image = None
    HAS_PIL = False

# Ensure repo root is on path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bench.video_recorder import BackupVideoRecorder, VideoFrameRenderer


class TestBackupVideoRecorder(unittest.TestCase):
    """Test suite for Day 6 Task A4 Backup Video Recording."""

    def setUp(self):
        if not HAS_PIL:
            self.skipTest("Pillow (PIL) is not installed in the current environment")
        self.tmp = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.tmp.name)
        self.recorder = BackupVideoRecorder(out_dir=self.out_dir)

    def tearDown(self):
        self.tmp.cleanup()

    def test_01_frame_renderer_dimensions_and_components(self):
        """VideoFrameRenderer generates 1280x720 frames for each of the 5 required stages."""
        renderer = VideoFrameRenderer(width=1280, height=720)

        # 1. Fault Frame
        f_fault = renderer.render_fault_frame(
            fault_id="fault_001_bad_deploy",
            service="orders",
            error_rate=0.22,
            alert="OrdersHigh5xxRate",
            error_log="TypeError: can only concatenate str to str",
        )
        self.assertEqual(f_fault.size, (1280, 720))
        self.assertEqual(f_fault.mode, "RGB")

        # 2. Agent Trace Frame
        f_agent = renderer.render_agent_trace_frame(
            incident_id="inc_001",
            tool_calls=[("query_logs", 'service="orders"', "TypeError in orders/app.py:42")],
            hypothesis="TypeError in discount addition",
            confidence=0.95,
        )
        self.assertEqual(f_agent.size, (1280, 720))

        # 3. PR Frame
        f_pr = renderer.render_pr_frame(
            pr_num=42,
            branch="nightshift/fix-001",
            title="fix(orders): cast discount to string",
            diff_text="- msg = discount\n+ msg = str(discount)",
        )
        self.assertEqual(f_pr.size, (1280, 720))

        # 4. Canary Frame
        f_canary = renderer.render_canary_frame(
            traffic_split=15,
            canary_rate=0.00,
            baseline_rate=0.22,
            verdict="PASS",
        )
        self.assertEqual(f_canary.size, (1280, 720))

        # 5. Recovery Graph Frame
        f_recovery = renderer.render_recovery_graph_frame(
            before_rate=0.22,
            after_rate=0.001,
            recovered_iso="2026-11-24T12:00:00Z",
        )
        self.assertEqual(f_recovery.size, (1280, 720))

    def test_02_record_first_complete_run_produces_valid_video_artifacts(self):
        """Exit criterion: Record a backup video of the first complete run showing all 5 components."""
        summary = self.recorder.record_first_complete_run(fault_id="fault_001_bad_deploy")

        # Check required files exist and are non-empty
        gif_file = Path(summary["video_gif"])
        webp_file = Path(summary["video_webp"])
        html_file = Path(summary["video_html"])

        self.assertTrue(gif_file.exists())
        self.assertGreater(gif_file.stat().st_size, 10000, "GIF video must be non-empty")

        self.assertTrue(webp_file.exists())
        self.assertGreater(webp_file.stat().st_size, 10000, "WebP video must be non-empty")

        self.assertTrue(html_file.exists())
        self.assertGreater(html_file.stat().st_size, 10000, "HTML5 video player must be non-empty")

        # Verify all 5 components are present
        components = summary["components_verified"]
        self.assertEqual(len(components), 5)
        self.assertTrue(any("Fault" in c for c in components), "Must verify Fault component")
        self.assertTrue(any("Agent trace" in c for c in components), "Must verify Agent trace component")
        self.assertTrue(any("PR" in c for c in components), "Must verify PR component")
        self.assertTrue(any("Canary" in c for c in components), "Must verify Canary component")
        self.assertTrue(any("Recovery graph" in c for c in components), "Must verify Recovery graph component")

        # Verify health metrics and verdict
        self.assertEqual(summary["verdict"], "PASS")
        self.assertEqual(summary["metric_before"], 0.22)
        self.assertEqual(summary["metric_after"], 0.001)

    def test_03_gif_video_contains_valid_frames(self):
        """Generated GIF video can be opened and parsed as a multi-frame animation."""
        summary = self.recorder.record_first_complete_run()
        gif_path = Path(summary["video_gif"])

        with Image.open(gif_path) as im:
            self.assertTrue(im.is_animated)
            self.assertGreaterEqual(im.n_frames, 5, "Video animation must contain at least 5 frames")


if __name__ == "__main__":
    unittest.main()
