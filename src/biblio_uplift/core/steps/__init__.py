"""Pipeline step construction."""

from biblio_uplift.core.steps.backup import BackupCleanupStep, BackupFilesStep, BackupVolumesStep
from biblio_uplift.core.steps.cleanup import DockerCleanupStep, LogCleanupStep
from biblio_uplift.core.steps.docker import DockerDownStep, DockerPullStep, DockerUpStep
from biblio_uplift.core.steps.git import GitPullStep
from biblio_uplift.core.steps.healthcheck import HealthCheckStep
from biblio_uplift.core.steps.hooks import HooksStep
from biblio_uplift.core.steps.preflight import PreflightStep
from biblio_uplift.core.steps.system import OsUpdateStep, RebootStep


def get_upgrade_steps():
    return [
        PreflightStep(),
        HooksStep("pre_hooks", "Pre-upgrade hooks", "pre_upgrade_hooks"),
        BackupFilesStep(),
        BackupVolumesStep(),
        BackupCleanupStep(),
        DockerDownStep(),
        GitPullStep(),
        DockerPullStep(),
        OsUpdateStep(),
        RebootStep(),
        DockerUpStep(),
        HealthCheckStep(),
        HooksStep("post_hooks", "Post-upgrade hooks", "post_upgrade_hooks"),
    ]


def get_cleanup_steps():
    return [
        PreflightStep(),
        DockerCleanupStep(),
        LogCleanupStep(),
    ]
