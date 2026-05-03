from __future__ import annotations

import shlex

from biblio_uplift.core.pipeline import PipelineContext, PipelineStep, StepResult, StepStatus


class GitPullStep(PipelineStep):
    name = "git_pull"
    description = "Pull latest changes from repository"
    skippable = True

    def execute(self, ctx: PipelineContext) -> StepResult:
        config = ctx.config
        project_dir = shlex.quote(str(config.project_dir))
        out = ctx.on_output or (lambda x: None)

        # 1. Show current commit
        result = ctx.ssh.run(f"cd {project_dir} && git log --oneline -1", on_output=out)
        if result.ok:
            ctx.state["git_pre_pull_hash"] = result.stdout.strip().split()[0]
            out(f"Current: {result.stdout.strip()}")

        # 2. Get current branch
        branch_result = ctx.ssh.run(f"cd {project_dir} && git rev-parse --abbrev-ref HEAD", on_output=out)
        branch = branch_result.stdout.strip() if branch_result.ok else "main"
        if config.git_branch:
            branch = config.git_branch
        ctx.state["git_branch"] = branch

        # 3. Fetch latest
        out(f"Fetching latest for {branch}...")
        result = ctx.ssh.run(f"cd {project_dir} && git fetch origin", timeout=120, on_output=out)
        if not result.ok:
            return StepResult(status=StepStatus.FAILED, error=f"git fetch failed: {result.stderr}")

        # 4. Reset to origin (handles dirty working tree)
        out(f"Resetting to origin/{branch}...")
        result = ctx.ssh.run(
            f"cd {project_dir} && git reset --hard origin/{shlex.quote(branch)}",
            timeout=30,
            on_output=out,
        )
        if not result.ok:
            return StepResult(status=StepStatus.FAILED, error=f"git reset failed: {result.stderr}")

        # 5. Show new commit
        result2 = ctx.ssh.run(f"cd {project_dir} && git log --oneline -1", on_output=out)
        if result2.ok:
            out(f"Now at: {result2.stdout.strip()}")

        # Show what changed
        pre_hash = ctx.state.get("git_pre_pull_hash", "")
        if pre_hash:
            diff_result = ctx.ssh.run(
                f"cd {project_dir} && git diff --stat {shlex.quote(pre_hash)}..HEAD",
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
        project_dir = shlex.quote(str(ctx.config.project_dir))
        out(f"Rollback: reverting to {pre_hash} on {branch}...")
        ctx.ssh.run(
            f"cd {project_dir} && git checkout {shlex.quote(branch)} && git reset --hard {shlex.quote(pre_hash)}",
            timeout=30,
            on_output=out,
        )
