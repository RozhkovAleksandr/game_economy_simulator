"""Run: python -m unittest -v"""

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from simulator import build_result, run_batch, run_one, summarize, validate

ROOT = Path(__file__).resolve().parent


class EconomyTests(unittest.TestCase):
    def setUp(self):
        self.a = json.loads((ROOT / "config_A.json").read_text(encoding="utf-8"))
        self.b = json.loads((ROOT / "config_B.json").read_text(encoding="utf-8"))

    def test_manual_example_a(self):
        saver = run_one(self.a, "saver")
        investor = run_one(self.a, "investor")
        self.assertEqual([10, 20, 30, 40, 0], [d["balance"] for d in saver["history"]])
        self.assertEqual([10, 0, 25, 0, 25], [d["balance"] for d in investor["history"]])
        self.assertEqual((saver["goal_day"], investor["goal_day"]), (5, 4))

    def test_price_change_b(self):
        investor = run_one(self.b, "investor")
        self.assertEqual([10, 20, 0, 25, 0], [d["balance"] for d in investor["history"]])
        self.assertEqual(investor["goal_day"], 5)

    def test_batch_count_and_reproducibility(self):
        self.a["players_per_profile"] = 3
        batch = run_batch(self.a)
        self.assertEqual(batch, run_batch(self.a))
        self.assertEqual(len(batch), 6)
        self.assertEqual([p["session"] for p in batch], [1, 2, 3, 1, 2, 3])

    def test_money_is_conserved(self):
        for config in (self.a, self.b):
            for player in run_batch(config):
                previous = config["start_gold"]
                for day in player["history"]:
                    self.assertEqual(day["balance_before"], previous)
                    self.assertEqual(day["balance"], previous + day["earned"] - day["spent"])
                    self.assertGreaterEqual(day["balance"], 0)
                    previous = day["balance"]
                self.assertEqual(
                    player["end_gold"],
                    config["start_gold"] + player["total_earned"] - player["total_spent"],
                )

    def test_upgrade_starts_tomorrow_and_goal_does_not_stop_income(self):
        result = run_one(self.a, "investor")
        self.assertEqual([10, 10, 25, 25, 25], [d["earned"] for d in result["history"]])
        self.assertEqual(
            (result["total_earned"], result["total_spent"], result["end_gold"]), (95, 70, 25)
        )

    def test_two_purchases_in_one_day(self):
        self.a["start_gold"] = 60
        result = run_one(self.a, "investor")
        first = result["history"][0]
        self.assertTrue(first["bought_upgrade"] and first["bought_item"])
        self.assertEqual((first["earned"], first["spent"], first["balance"]), (10, 70, 0))
        self.assertEqual(result["goal_day"], 1)

    def test_investor_waits_for_upgrade_even_if_item_is_affordable(self):
        self.a["upgrade"]["price"] = 100
        self.a["item"]["price"] = 20
        self.assertIsNone(run_one(self.a, "investor")["goal_day"])
        self.assertEqual(run_one(self.a, "saver")["goal_day"], 2)

    def test_late_purchase_and_no_purchase(self):
        self.a["goal"]["by_day"] = 3
        late = run_one(self.a, "investor")
        self.assertFalse(late["goal_reached"])
        self.assertEqual(late["goal_day"], 4)
        self.assertEqual(summarize([late])["item_owned_percent"], 100)
        self.assertEqual(summarize([late])["goal_reached_percent"], 0)
        self.a["item"]["price"] = 500
        missing = run_one(self.a, "investor")
        self.assertIsNone(missing["goal_day"])
        self.assertIsNone(summarize([missing])["mean_goal_day"])

    def test_purchase_time_only_counts_buyers(self):
        buyer = run_one(self.a, "saver")
        self.a["item"]["price"] = 500
        stats = summarize([buyer, run_one(self.a, "saver")])
        self.assertEqual(
            (stats["goal_reached_percent"], stats["item_owned_percent"], stats["mean_goal_day"]),
            (50, 50, 5),
        )

    def test_zero_reward_and_free_purchases(self):
        self.a["action_reward"] = 0
        self.a["upgrade"]["price"] = 0
        self.a["item"]["price"] = 0
        result = run_one(self.a, "investor")
        self.assertEqual(result["goal_day"], 1)
        self.assertEqual(result["history"][0]["balance"], 0)

    def test_invalid_settings(self):
        cases = [
            ("days", True),
            ("days", 0),
            ("players_per_profile", -1),
            ("players_per_profile", True),
            ("start_gold", -1),
            ("item", []),
            ("profiles", {"saver": {"players": 3}}),
            ("profiles", []),
            ("profiles", ["unknown"]),
            ("profiles", ["saver", "saver"]),
            ("name", ""),
        ]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                config = copy.deepcopy(self.a)
                config[key] = value
                with self.assertRaises(ValueError):
                    validate(config)
        del self.a["upgrade"]["price"]
        with self.assertRaisesRegex(ValueError, "upgrade.price"):
            validate(self.a)

    def test_player_day_limit(self):
        self.a["players_per_profile"] = 1_000_000
        with self.assertRaisesRegex(ValueError, "Лимит"):
            run_batch(self.a)

    def test_recorded_actions_use_config_names(self):
        self.a["upgrade"]["name"] = "инструмент"
        self.a["item"]["name"] = self.a["goal"]["item"] = "щит"
        result = run_one(self.a, "investor")
        self.assertEqual(
            result["history"][1]["actions"],
            [
                {"type": "purchase", "target": "upgrade", "name": "инструмент", "price": 20},
                {"type": "wait", "target": "item", "name": "щит", "missing_gold": 50},
            ],
        )
        self.assertEqual(
            result["history"][3]["actions"],
            [
                {"type": "purchase", "target": "item", "name": "щит", "price": 50},
            ],
        )
        self.assertEqual(result["history"][4]["actions"], [])

    def test_unknown_profile(self):
        with self.assertRaisesRegex(ValueError, "Неизвестный профиль"):
            run_one(self.a, "unknown")

    def test_json_contains_summary_settings_and_histories(self):
        result = build_result([self.a, self.b])
        self.assertEqual(result, json.loads(json.dumps(result, ensure_ascii=False)))
        self.assertEqual(len(result["summary"]), 4)
        self.assertEqual(result["summary"][1]["mean_goal_day"], 4)
        self.assertEqual(result["summary"][1]["mean_end_gold"], 25)
        for run, config in zip(result["runs"], (self.a, self.b)):
            self.assertEqual(run["config"], config)
            self.assertEqual(len(run["players"]), 2 * config["players_per_profile"])
            self.assertTrue(all(len(p["history"]) == 5 for p in run["players"]))

    def test_cli_does_not_overwrite_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "economy.json"
            original = json.dumps(self.a, ensure_ascii=False)
            path.write_text(original, encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(ROOT / "simulator.py"), str(path), "--output", str(path)],
                capture_output=True,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertNotIn(b"Traceback", completed.stderr)
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_cli_writes_json_in_windows_encoding_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "economy.json"
            self.a["goal"]["by_day"] = 3
            path.write_text(json.dumps(self.a, ensure_ascii=False), encoding="utf-8")
            output = Path(directory) / "output" / "A.json"
            completed = subprocess.run(
                [sys.executable, str(ROOT / "simulator.py"), str(path), "--output", str(output)],
                cwd=directory,
                capture_output=True,
                env={**os.environ, "PYTHONIOENCODING": "cp1251"},
            )
            self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8"))
            self.assertIn("Сохранено:", completed.stdout.decode("utf-8"))
            result = json.loads(output.read_text(encoding="utf-8"))
            investor = result["runs"][0]["players"][1]
            self.assertFalse(investor["goal_reached"])
            self.assertEqual(investor["goal_day"], 4)


if __name__ == "__main__":
    unittest.main()
