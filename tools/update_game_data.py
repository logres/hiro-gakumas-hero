"""Prepare KAA public game data using its official staging/apply workflow.

Run from the repository root. Does not launch or control the game.
"""
import hiro.vision  # Apply HIRO_KAA_GAME_DATA before constructing the updater.
from kaa.game_data.updater import GameDataUpdater, apply_pending, has_usable_baseline


def main():
    updater = GameDataUpdater()
    result = updater.check_only()
    if result is None:
        raise SystemExit("Could not retrieve the public game-data manifest; existing data retained")
    missing = result.needs_db or any(result.category_missing.values())
    if result.needs_update or missing:
        print(f"Preparing public game data: {result.manifest.version}", flush=True)
        shown = {}

        def progress(name, current, total):
            percent = current * 100 // total if total else 0
            if total and (current == total or percent >= shown.get(name, -25) + 25):
                shown[name] = percent
                print(f"  {name}: {percent}%", flush=True)

        updater.download_to_staging(result, file_progress_cb=progress)
        if not apply_pending():
            raise SystemExit("Download finished but staged data could not be applied")
    if not has_usable_baseline():
        raise SystemExit("Public game data failed baseline validation")
    print("Public game data baseline validated", flush=True)


if __name__ == "__main__":
    main()
