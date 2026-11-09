"""Iron & Snow: a story-driven Battle of the Bastards fan game."""


def main() -> None:
    """Launch the game through the installed ``iron-and-snow`` command."""
    from iron_and_snow.game import main as run_game

    run_game()


__all__ = ["main"]
