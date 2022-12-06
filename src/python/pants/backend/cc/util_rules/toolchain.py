# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Iterable

from pants.backend.cc.subsystems.compiler import CCSubsystem, ExternalCCSubsystem
from pants.backend.cc.target_types import CCLanguage
from pants.core.util_rules.archive import ExtractedArchive
from pants.core.util_rules.archive import rules as archive_rules
from pants.core.util_rules.system_binaries import (
    BinaryNotFoundError,
    BinaryPathRequest,
    BinaryPaths,
    BinaryPathTest,
)
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.fs import DownloadFile
from pants.engine.internals.native_engine import EMPTY_DIGEST, Digest
from pants.engine.platform import Platform
from pants.engine.process import Process
from pants.engine.rules import Get, Rule, collect_rules, rule, rule_helper
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.ordered_set import OrderedSet

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CCToolchainRequest:
    language: CCLanguage


@dataclass(frozen=True)
class CCToolchain:
    """A configured C/C++ toolchain for the current platform."""

    compiler: str
    compile_flags: tuple[str, ...] = ()
    compile_defines: tuple[str, ...] = ()
    link_flags: tuple[str, ...] = ()
    digest: Digest = EMPTY_DIGEST

    def __post_init__(self):
        # TODO: Should this error out to notify the user of a mistake? Or silently handle
        # Or just ensure all defines have -D right now?
        if self.compile_defines:
            sanitized_defines = [define.lstrip("-D") for define in self.compile_defines]
            object.__setattr__(self, "compile_defines", tuple(sanitized_defines))

    @property
    def compile_command(self) -> tuple[str, ...]:
        command = [self.compiler, *self.compile_defines, *self.compile_flags]
        return tuple(filter(None, command))

    @property
    def link_command(self) -> tuple[str, ...]:
        command = [self.compiler, *self.link_flags]
        return tuple(filter(None, command))


@rule_helper
async def _executable_path(binary_names: Iterable[str], search_paths: Iterable[str]) -> str:
    for name in binary_names:
        binary_paths = await Get(
            BinaryPaths,
            BinaryPathRequest(
                binary_name=name,
                search_path=search_paths,
                test=BinaryPathTest(args=["-v"]),
            ),
        )

        if not binary_paths or not binary_paths.first_path:
            continue
        return binary_paths.first_path.path

    raise BinaryNotFoundError(f"Could not find any of '{binary_names}' in any of {search_paths}.")


@rule_helper
async def _setup_downloadable_toolchain(
    request: CCToolchainRequest, subsystem: ExternalCCSubsystem
) -> CCToolchain:
    download_file_request = subsystem.get_request(Platform.current).download_file_request
    maybe_archive_digest = await Get(Digest, DownloadFile, download_file_request)
    extracted_archive = await Get(ExtractedArchive, Digest, maybe_archive_digest)

    # Populate the toolchain for C or C++ accordingly
    if request.language == CCLanguage.CPP:
        return CCToolchain(
            compiler=subsystem.cpp_executable,
            compile_flags=tuple(subsystem.cpp_compile_options),
            compile_defines=tuple(subsystem.cpp_defines),
            digest=extracted_archive.digest,
        )

    return CCToolchain(
        compiler=subsystem.c_executable,
        compile_flags=tuple(subsystem.c_compile_options),
        compile_defines=tuple(subsystem.c_defines),
        digest=extracted_archive.digest,
    )


@rule_helper
async def _setup_system_toolchain(
    request: CCToolchainRequest, subsystem: CCSubsystem
) -> CCToolchain:
    # Sanitize the search paths in case the "<PATH>" is specified
    raw_search_paths = list(subsystem.search_paths)
    if "<PATH>" in raw_search_paths:
        i = raw_search_paths.index("<PATH>")
        env = await Get(Environment, EnvironmentRequest(["PATH"]))
        system_path = env.get("PATH", "")
        raw_search_paths[i : i + 1] = system_path.split(os.pathsep)

    search_paths = tuple(OrderedSet(raw_search_paths))

    # Populate the toolchain for C or C++ accordingly
    if request.language == CCLanguage.CPP:
        cpp_executable = await _executable_path(tuple(subsystem.cpp_executable), search_paths)
        return CCToolchain(
            cpp_executable,
            compile_flags=tuple(subsystem.cpp_compile_options),
            compile_defines=tuple(subsystem.cpp_defines),
        )

    c_executable = await _executable_path(tuple(subsystem.c_executable), search_paths)
    return CCToolchain(
        c_executable,
        compile_flags=tuple(subsystem.c_compile_options),
        compile_defines=tuple(subsystem.c_defines),
    )


@rule(desc="Setup the CC Toolchain", level=LogLevel.DEBUG)
async def setup_cc_toolchain(
    request: CCToolchainRequest, subsystem: CCSubsystem, external_subsystem: ExternalCCSubsystem
) -> CCToolchain:
    if external_subsystem.url_template:
        return await _setup_downloadable_toolchain(request, external_subsystem)
    else:
        return await _setup_system_toolchain(request, subsystem)


@dataclass(frozen=True)
class CCProcess:
    args: tuple[str, ...]
    language: CCLanguage
    description: str
    input_digest: Digest = EMPTY_DIGEST
    output_files: tuple[str, ...] = ()
    level: LogLevel = LogLevel.INFO


@rule(desc="Setup a CC Process loaded with the CCToolchain", level=LogLevel.DEBUG)
async def setup_cc_process(request: CCProcess) -> Process:
    toolchain = await Get(CCToolchain, CCToolchainRequest(request.language))

    # TODO: What if this is for linking instead of compiling?
    compiler_command = list(toolchain.compile_command)

    # If downloaded, this will be the toolchain, otherwise empty digest
    immutable_digests = {"__toolchain": toolchain.digest}

    if toolchain.digest != EMPTY_DIGEST:
        compiler_command[0] = f"__toolchain/{compiler_command[0]}"

    argv = tuple(compiler_command) + request.args
    return Process(
        argv=argv,
        input_digest=request.input_digest,
        output_files=request.output_files,
        description=request.description,
        level=request.level,
        immutable_input_digests=immutable_digests,
        # env={"__PANTS_CC_COMPILER_FINGERPRINT": toolchain.compiler.fingerprint},
    )


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        *archive_rules(),
    )