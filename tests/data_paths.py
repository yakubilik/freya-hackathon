"""Read untracked test inputs from the primary checkout in a linked worktree."""
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent


def data_path(relative):
    local = ROOT / relative
    if local.exists():
        return local
    common = subprocess.check_output(
        ["git", "rev-parse", "--git-common-dir"], cwd=ROOT, text=True
    ).strip()
    shared = (ROOT / common).resolve().parent / relative
    return shared if shared.exists() else local
