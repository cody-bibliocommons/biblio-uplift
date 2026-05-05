from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from biblio_uplift.config.schema import ProjectConfig
    from biblio_uplift.core.ssh import SSHRunner

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    success: bool
    output: str = ""
    error: str = ""


class Tool:
    name: str = ""
    category: str = ""
    description: str = ""
    read_only: bool = True

    def dry_run(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        raise NotImplementedError

    def execute(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        raise NotImplementedError


def get_all_tools() -> list[Tool]:
    from biblio_uplift.core.tools.docker import TOOLS as docker_tools
    from biblio_uplift.core.tools.network import TOOLS as network_tools
    from biblio_uplift.core.tools.security import TOOLS as sec
    from biblio_uplift.core.tools.system import TOOLS as sys_tools
    from biblio_uplift.core.tools.users import TOOLS as user_tools
    return sec + sys_tools + docker_tools + network_tools + user_tools
