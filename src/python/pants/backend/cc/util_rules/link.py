# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from pants.backend.cc.subsystems.toolchain import CCToolchain, CCToolchainRequest
from pants.engine.internals.native_engine import Digest, Snapshot
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, Rule, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LinkCCBinaryRequest:
    """Link a CC binary from object files."""

    input_digest: Digest
    output_name: str
    # flags, options


@dataclass(frozen=True)
class LinkedCCBinary:
    """A linked CC binary stored in a `Digest`."""

    digest: Digest


@rule(desc="Create an executable from object files")
async def link_cc_binary(request: LinkCCBinaryRequest) -> LinkedCCBinary:

    # Get object files in digest
    snapshot = await Get(Snapshot, Digest, request.input_digest)

    # TODO: Determine language from files or passed in
    toolchain = await Get(CCToolchain, CCToolchainRequest(language="c++"))

    argv = list(toolchain.link_argv) + ["-o", request.output_name, *snapshot.files]

    logger.debug(f"Linker args for {request.output_name}: {argv}")
    link_result = await Get(
        FallibleProcessResult,
        Process(
            argv=argv,
            input_digest=request.input_digest,
            description=f"Linking CC binary: {request.output_name}",
            output_files=(request.output_name,),
            level=LogLevel.DEBUG,
            env={"__PANTS_CC_COMPILER_FINGERPRINT": toolchain.compiler.fingerprint},
        ),
    )
    logger.warning(link_result.stderr)

    return LinkedCCBinary(link_result.output_digest)


def rules() -> Iterable[Rule | UnionRule]:
    return collect_rules()
