"""MVP: настройки экономики → симуляция игроков → результат в JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import mean

MAX_PLAYER_DAYS = 1_000_000


def validate(config: dict) -> None:
    """Проверить настройки до запуска игроков."""
    if not isinstance(config, dict):
        raise ValueError("Конфигурация должна быть JSON-объектом.")
    for key in (
        "name",
        "days",
        "players_per_profile",
        "start_gold",
        "action_reward",
        "item",
        "upgrade",
        "goal",
        "profiles",
    ):
        if key not in config:
            raise ValueError(f"В конфигурации отсутствует поле {key}.")
    if not isinstance(config["name"], str) or not config["name"].strip():
        raise ValueError("name: требуется непустое название.")
    for key in ("days", "players_per_profile"):
        if type(config[key]) is not int or config[key] <= 0:
            raise ValueError(f"{key}: требуется целое число больше нуля.")
    for key in ("item", "upgrade", "goal"):
        if not isinstance(config[key], dict):
            raise ValueError(f"{key}: требуется JSON-объект.")
    for key in ("item", "upgrade"):
        name = config[key].get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{key}.name: требуется непустое название.")
    amounts = {
        "start_gold": config["start_gold"],
        "action_reward": config["action_reward"],
        "item.price": config["item"].get("price"),
        "upgrade.price": config["upgrade"].get("price"),
        "upgrade.reward_after": config["upgrade"].get("reward_after"),
    }
    for key, value in amounts.items():
        if type(value) is not int or value < 0:
            raise ValueError(f"{key}: требуется целое число не меньше нуля.")
    profiles = config["profiles"]
    if (
        not isinstance(profiles, list)
        or not profiles
        or any(p not in ("saver", "investor") for p in profiles)
    ):
        raise ValueError("profiles: нужен список из saver и/или investor.")
    if len(set(profiles)) != len(profiles):
        raise ValueError("profiles: профили не должны повторяться.")
    goal = config["goal"]
    if goal.get("type") != "own_item" or goal.get("item") != config["item"]["name"]:
        raise ValueError("goal: поддерживается own_item для предмета из item.name.")
    if type(goal.get("by_day")) is not int or not 1 <= goal["by_day"] <= config["days"]:
        raise ValueError("goal.by_day: срок должен быть от 1 до days включительно.")
    if config["days"] * config["players_per_profile"] * len(profiles) > MAX_PLAYER_DAYS:
        raise ValueError(f"Лимит расчёта — {MAX_PLAYER_DAYS:,} дней игроков.")


def run_one(config: dict, profile: str) -> dict:
    """Дни одного игрока. config уже проверен в run_batch."""
    if profile not in ("saver", "investor"):
        raise ValueError(f"Неизвестный профиль: {profile}.")
    balance = config["start_gold"]
    upgraded = False
    item_owned = False
    goal_day = None
    history = []
    for day in range(1, config["days"] + 1):
        balance_before = balance
        earned = config["upgrade"]["reward_after"] if upgraded else config["action_reward"]
        balance += earned
        spent = 0
        bought_upgrade = False
        bought_item = False
        actions = []

        # Инвестор сначала тратит деньги на улучшение; накопитель его не покупает.
        if profile == "investor" and not upgraded and balance >= config["upgrade"]["price"]:
            balance -= config["upgrade"]["price"]
            spent += config["upgrade"]["price"]
            upgraded = bought_upgrade = True
            actions.append(
                {
                    "type": "purchase",
                    "target": "upgrade",
                    "name": config["upgrade"]["name"],
                    "price": config["upgrade"]["price"],
                }
            )

        # Накопитель покупает предмет сразу, инвестор — после улучшения.
        if (
            not item_owned
            and balance >= config["item"]["price"]
            and (profile == "saver" or upgraded)
        ):
            balance -= config["item"]["price"]
            spent += config["item"]["price"]
            item_owned = bought_item = True
            goal_day = day
            actions.append(
                {
                    "type": "purchase",
                    "target": "item",
                    "name": config["item"]["name"],
                    "price": config["item"]["price"],
                }
            )

        if not item_owned:
            target = "upgrade" if profile == "investor" and not upgraded else "item"
            actions.append(
                {
                    "type": "wait",
                    "target": target,
                    "name": config[target]["name"],
                    "missing_gold": config[target]["price"] - balance,
                }
            )
        history.append(
            {
                "day": day,
                "balance_before": balance_before,
                "earned": earned,
                "spent": spent,
                "balance": balance,
                "upgraded": upgraded,
                "item_owned": item_owned,
                "bought_upgrade": bought_upgrade,
                "bought_item": bought_item,
                "actions": actions,
            }
        )
    return {
        "profile": profile,
        "goal_reached": goal_day is not None and goal_day <= config["goal"]["by_day"],
        "goal_day": goal_day,
        "end_gold": balance,
        "history": history,
        "total_earned": sum(day["earned"] for day in history),
        "total_spent": sum(day["spent"] for day in history),
    }


def run_batch(config: dict) -> list[dict]:
    """Запустить одинаковое число игроков каждого выбранного профиля."""
    validate(config)
    players = []
    for profile in config["profiles"]:
        for number in range(1, config["players_per_profile"] + 1):
            player = run_one(config, profile)
            player["session"] = number
            players.append(player)
    return players


def summarize(players: list[dict]) -> dict:
    """День покупки усредняется только среди купивших."""
    days = [p["goal_day"] for p in players if p["goal_day"] is not None]
    return {
        "goal_reached_percent": 100 * mean(p["goal_reached"] for p in players),
        "item_owned_percent": 100 * len(days) / len(players),
        "mean_goal_day": mean(days) if days else None,
        "mean_earned": mean(p["total_earned"] for p in players),
        "mean_spent": mean(p["total_spent"] for p in players),
        "mean_end_gold": mean(p["end_gold"] for p in players),
    }


def build_result(configs: list[dict]) -> dict:
    result = {"summary": [], "runs": []}
    for config in configs:
        batch = run_batch(config)
        result["runs"].append({"config": config, "players": batch})
        for profile in config["profiles"]:
            players = [p for p in batch if p["profile"] == profile]
            result["summary"].append(
                {
                    "economy": config["name"],
                    "profile": profile,
                    "players": len(players),
                    **summarize(players),
                }
            )
    return result


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Симулятор игровой экономики с результатами в JSON."
    )
    defaults = [Path(__file__).with_name(f"config_{letter}.json") for letter in ("A", "B")]
    parser.add_argument("configs", nargs="*", type=Path, default=defaults)
    parser.add_argument("--output", type=Path, default=Path("results.json"))
    args = parser.parse_args()
    try:
        if any(path.resolve() == args.output.resolve() for path in args.configs):
            raise ValueError("Путь результата должен отличаться от входных конфигураций.")
        configs = [json.loads(path.read_text(encoding="utf-8-sig")) for path in args.configs]
        result = build_result(configs)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"Сохранено: {args.output.resolve()}")
    print("summary — итоги; runs — настройки и история игроков по дням.")


if __name__ == "__main__":
    main()
