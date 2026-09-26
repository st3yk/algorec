"""Thin wrappers over git for the branch checks. See docs/guardrails.md."""

import subprocess
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Commit:
    sha: str
    subject: str
    body: str
    files: tuple[str, ...] = field(default_factory=tuple)
    parents: int = 1

    @property
    def short(self) -> str:
        return self.sha[:7]

    def trailers(self, key: str) -> list[str]:
        prefix = f"{key.lower()}:"
        return [
            line.split(":", 1)[1].strip()
            for line in self.body.splitlines()
            if line.lower().startswith(prefix) and line.split(":", 1)[1].strip()
        ]


def git(repo: str, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def rev(repo: str, ref: str) -> str:
    return git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()


def merge_base(repo: str, base: str, head: str) -> str:
    return git(repo, "merge-base", base, head).strip()


def commits(repo: str, base: str, head: str) -> list[Commit]:
    out = git(repo, "log", "--reverse", "--format=%H%x00%P%x00%s%x00%b%x1e", f"{base}..{head}")
    result = []
    for record in out.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        sha, parents, subject, body = record.split("\x00", 3)
        files = git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "-m", "--root", sha).split()
        result.append(Commit(sha, subject, body.strip(), tuple(sorted(set(files))), len(parents.split())))
    return result


def changed_files(repo: str, base: str, head: str) -> list[str]:
    return sorted(set(git(repo, "diff", "--name-only", f"{base}..{head}").split()))


def show(repo: str, ref: str, path: str) -> str | None:
    result = subprocess.run(["git", "-C", repo, "show", f"{ref}:{path}"], capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else None


def ls_tree(repo: str, ref: str, *paths: str) -> list[str]:
    return git(repo, "ls-tree", "-r", "--name-only", ref, "--", *paths).split()
def show_bytes(repo: str, ref: str, path: str) -> bytes | None:
    result = subprocess.run(["git", "-C", repo, "show", f"{ref}:{path}"], capture_output=True)
    return result.stdout if result.returncode == 0 else None




def dirty_tracked(repo: str) -> list[str]:
    return [line[3:] for line in git(repo, "status", "--porcelain", "--untracked-files=no").splitlines() if line]
