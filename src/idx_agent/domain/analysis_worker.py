"""WO-017 container worker settings and run results (ADR-0013).

ExecutorConfig is operator-owned: the image comes only from the tool server's
environment. Limits may be lowered (tests do), never raised above the ADR values.
Results carry fixed status codes; raw worker output never leaves the executor.
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from idx_agent.domain.analysis_output import WorkerOutput

WALL_CLOCK_S = 30
ANALYSIS_STDOUT_CAP = 64 * 1024
RENDER_STDOUT_CAP = 512 * 1024
STDERR_CAP = 8 * 1024
IMAGE_ENV = "IDX_ANALYSIS_IMAGE"

_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_IMAGE_DIGEST = re.compile(r"^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$")

WorkerScript = Literal["bootstrap.py", "render.py"]
WorkerStatus = Literal[
    "ok", "timeout", "output_too_large", "failed", "unavailable", "busy"
]
AnalysisStatus = Literal[
    "ok",
    "invalid_code",
    "invalid_output",
    "timeout",
    "output_too_large",
    "failed",
    "unavailable",
    "busy",
]
RenderStatus = Literal[
    "ok",
    "invalid_png",
    "timeout",
    "output_too_large",
    "failed",
    "unavailable",
    "busy",
]
AnalysisReason = Literal[
    "code_not_text",
    "code_too_long",
    "code_has_nul",
    "code_not_utf8",
    "output_refused",
]

_Seconds = Annotated[float, Field(gt=0, le=WALL_CLOCK_S, allow_inf_nan=False)]

_FROZEN = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


def _which_docker() -> str | None:
    found = shutil.which("docker")
    return os.path.abspath(found) if found else None


class ExecutorConfig(BaseModel):
    """Pinned image, resolved docker client and limits that can only go down."""

    model_config = _FROZEN

    image: str
    docker: str | None = Field(default_factory=_which_docker)
    wall_clock_s: _Seconds = WALL_CLOCK_S
    analysis_stdout_cap: int = Field(
        default=ANALYSIS_STDOUT_CAP, gt=0, le=ANALYSIS_STDOUT_CAP, strict=True
    )
    render_stdout_cap: int = Field(
        default=RENDER_STDOUT_CAP, gt=0, le=RENDER_STDOUT_CAP, strict=True
    )
    stderr_cap: int = Field(default=STDERR_CAP, gt=0, le=STDERR_CAP, strict=True)

    @field_validator("image")
    @classmethod
    def _pinned(cls, value: str) -> str:
        if not (_IMAGE_ID.match(value) or _IMAGE_DIGEST.match(value)):
            raise ValueError("the analysis image must be pinned by sha256 digest")
        return value

    @field_validator("docker")
    @classmethod
    def _absolute(cls, value: str | None) -> str | None:
        if value is not None and not os.path.isabs(value):
            raise ValueError("the docker client path must be absolute")
        return value

    def stdout_cap(self, script: WorkerScript) -> int:
        if script == "bootstrap.py":
            return self.analysis_stdout_cap
        return self.render_stdout_cap

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> ExecutorConfig | None:
        """Read only IDX_ANALYSIS_IMAGE; None when unset, an error when not pinned."""
        image = environ.get(IMAGE_ENV, "").strip()
        if not image:
            return None
        return cls(image=image)


class WorkerRun(BaseModel):
    """One container run; stdout is kept only for a clean exit within the caps."""

    model_config = _FROZEN

    status: WorkerStatus
    stdout: bytes | None = None
    exit_code: int | None = None
    duration_s: float = Field(ge=0)

    @model_validator(mode="after")
    def _stdout_only_when_ok(self) -> WorkerRun:
        if (self.stdout is not None) != (self.status == "ok"):
            raise ValueError("stdout is kept only for an ok run")
        return self


class AnalysisRun(BaseModel):
    """Parsed worker output or a fixed status; never raw stdout or stderr."""

    model_config = _FROZEN

    status: AnalysisStatus
    output: WorkerOutput | None = None
    reason: AnalysisReason | None = None
    duration_s: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def _output_only_when_ok(self) -> AnalysisRun:
        if (self.output is not None) != (self.status == "ok"):
            raise ValueError("output is present only for an ok run")
        return self


class RenderRun(BaseModel):
    """A checked PNG or a fixed status; the image is kept only for an ok run."""

    model_config = _FROZEN

    status: RenderStatus
    png: bytes | None = Field(default=None, repr=False)
    width: int | None = None
    height: int | None = None
    duration_s: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def _png_only_when_ok(self) -> RenderRun:
        ok = self.status == "ok"
        if any(
            (part is not None) != ok for part in (self.png, self.width, self.height)
        ):
            raise ValueError("the image is present only for an ok run")
        return self
