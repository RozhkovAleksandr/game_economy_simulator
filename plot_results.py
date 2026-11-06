"""Построить PNG по сохранённой истории JSON. Симуляция здесь не запускается."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean


def plot_results(result: dict, output: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")  # Сохранение картинки без окна и графического интерфейса.
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    if (
        not isinstance(result, dict)
        or not isinstance(result.get("runs"), list)
        or not result["runs"]
    ):
        raise ValueError("В JSON нужен непустой список runs, созданный simulator.py.")
    runs = result["runs"]
    profiles = list(dict.fromkeys(p["profile"] for run in runs for p in run["players"]))
    colors = {profile: f"C{index % 10}" for index, profile in enumerate(profiles)}
    fig, axes = plt.subplots(
        len(runs), 1, figsize=(11, 3.5 * len(runs)), squeeze=False, layout="constrained"
    )
    try:
        fig.suptitle("Золото на руках по дням", fontsize=17, fontweight="bold")
        for ax, run in zip(axes[:, 0], runs):
            config = run["config"]
            groups = defaultdict(list)
            for player in run["players"]:
                groups[player["profile"]].append(player)
            if not groups:
                raise ValueError("В runs нет игроков для построения графика.")
            for profile, players in groups.items():
                # Все точки берутся из history; среднее учитывает каждого игрока.
                balances = defaultdict(list)
                balances[0] = [config["start_gold"]] * len(players)
                for player in players:
                    for day in player["history"]:
                        balances[day["day"]].append(day["balance"])
                days = sorted(balances)
                ax.plot(
                    days,
                    [mean(balances[day]) for day in days],
                    marker="o",
                    markersize=4,
                    linewidth=2,
                    color=colors[profile],
                    label=f"{profile} · игроков: {len(players)}",
                )
            ax.set_title(config["name"], loc="left", fontsize=12)
            ax.set_xlabel("Игровой день (0 — старт)")
            ax.set_ylabel("Золото после покупок\nв среднем на игрока")
            ax.xaxis.set_major_locator(MaxNLocator(integer=True))
            ax.grid(alpha=0.25)
            ax.spines[["top", "right"]].set_visible(False)
            ax.legend()
        output.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output, dpi=160, format="png")
    finally:
        plt.close(fig)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="График золота из истории results.json в PNG.")
    parser.add_argument("input", nargs="?", type=Path, default=Path("results.json"))
    parser.add_argument("--output", type=Path, default=Path("results.png"))
    args = parser.parse_args()
    try:
        if args.input.resolve() == args.output.resolve():
            raise ValueError("Путь картинки должен отличаться от входного JSON.")
        if args.output.suffix.lower() != ".png":
            raise ValueError("Укажите выходной файл с расширением .png.")
        result = json.loads(args.input.read_text(encoding="utf-8-sig"))
        plot_results(result, args.output)
    except ModuleNotFoundError:
        parser.error("Для графика установите библиотеку: python -m pip install -r requirements.txt")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(f"Не удалось построить график: {error}")
    print(f"График сохранён: {args.output.resolve()}")


if __name__ == "__main__":
    main()
