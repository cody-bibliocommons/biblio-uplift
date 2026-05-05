from __future__ import annotations

import shlex

from biblio_uplift.core.pipeline import PipelineContext, PipelineStep, StepResult, StepStatus


def _git_cmd(project_dir: str, git_args: str) -> str:
    """Wrap cd + git in bash -c so sudo doesn't choke on the cd builtin."""
    dir_q = shlex.quote(project_dir)
    inner = (
        f"grep -q bitbucket.org ~/.ssh/known_hosts 2>/dev/null"
        f" || ssh-keyscan -t ed25519 bitbucket.org >> ~/.ssh/known_hosts 2>/dev/null; "
        f"cd {dir_q} && git -c safe.directory={dir_q} {git_args}"
    )
    return f"bash -c {shlex.quote(inner)}"


class GitPullStep(PipelineStep):
    name = "git_pull"
    description = "Pull latest changes from repository"
    skippable = True

    def execute(self, ctx: PipelineContext) -> StepResult:
        config = ctx.config
        project_dir = str(config.project_dir)
        out = ctx.on_output or (lambda x: None)

        # 1. Show current commit
        result = ctx.ssh.run(_git_cmd(project_dir, "log --oneline -1"), on_output=out)
        if result.ok:
            ctx.state["git_pre_pull_hash"] = result.stdout.strip().split()[0]
            out(f"Current: {result.stdout.strip()}")

        # 2. Get current branch
        branch_result = ctx.ssh.run(_git_cmd(project_dir, "rev-parse --abbrev-ref HEAD"), on_output=out)
        branch = branch_result.stdout.strip() if branch_result.ok else "main"
        if config.git_branch:
            branch = config.git_branch
        ctx.state["git_branch"] = branch

        # 3. Fetch latest
        out(f"Fetching latest for {branch}...")
        result = ctx.ssh.run(_git_cmd(project_dir, "fetch origin"), timeout=120, on_output=out)
        if not result.ok:
            return StepResult(status=StepStatus.FAILED, error=f"git fetch failed: {result.stderr}")

        # 4. Check for uncommitted changes
        status_result = ctx.ssh.run(_git_cmd(project_dir, "status --porcelain"), timeout=10)
        if status_result.ok and status_result.stdout.strip():
            out("WARNING: Uncommitted changes detected on remote, will be overwritten:")
            for line in status_result.stdout.strip().splitlines()[:10]:
                out(f"  {line}")

        # 5. Reset to origin (handles dirty working tree)
        out(f"Resetting to origin/{branch}...")
        result = ctx.ssh.run(
            _git_cmd(project_dir, f"reset --hard origin/{shlex.quote(branch)}"),
            timeout=30,
            on_output=out,
        )
        if not result.ok:
            return StepResult(status=StepStatus.FAILED, error=f"git reset failed: {result.stderr}")

        # 6. Show new commit
        result2 = ctx.ssh.run(_git_cmd(project_dir, "log --oneline -1"), on_output=out)
        if result2.ok:
            out(f"Now at: {result2.stdout.strip()}")

        # Show what changed
        pre_hash = ctx.state.get("git_pre_pull_hash", "")
        if pre_hash:
            diff_result = ctx.ssh.run(
                _git_cmd(project_dir, f"diff --stat {shlex.quote(pre_hash)}..HEAD"),
                on_output=out,
            )
            if diff_result.ok and diff_result.stdout.strip():
                out("Changes:")
                # stdout already streamed via on_output
            elif diff_result.ok:
                out("No file changes.")

        return StepResult(status=StepStatus.SUCCESS, message=result2.stdout.strip() if result2.ok else "")

    def rollback(self, ctx: PipelineContext) -> None:
        pre_hash = ctx.state.get("git_pre_pull_hash")
        branch = ctx.state.get("git_branch", "main")
        if not pre_hash:
            return
        out = ctx.on_output or (lambda x: None)
        project_dir = str(ctx.config.project_dir)
        out(f"Rollback: reverting to {pre_hash} on {branch}...")
        dir_q = shlex.quote(project_dir)
        inner = (
            f"cd {dir_q} && "
            f"git -c safe.directory={dir_q} checkout {shlex.quote(branch)} && "
            f"git -c safe.directory={dir_q} reset --hard {shlex.quote(pre_hash)}"
        )
        ctx.ssh.run(
            f"bash -c {shlex.quote(inner)}",
            timeout=30,
            on_output=out,
        )
