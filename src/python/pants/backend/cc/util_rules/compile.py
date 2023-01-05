# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from pants.backend.cc.target_types import CCFieldSet
from pants.backend.cc.util_rules.toolchain import CCProcess
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, Rule, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompileCCSourceRequest:
    """A request to compile a single C/C++ source file."""

    field_set: CCFieldSet


@dataclass(frozen=True)
class CompiledCCObject:
    """A compiled C/C++ object file."""

    digest: Digest


@dataclass(frozen=True)
class FallibleCompiledCCObject:
    """A compiled C/C++ object file, which may have failed to compile."""

    name: str
    process_result: FallibleProcessResult


@rule(desc="Compile CC source with the current toolchain")
async def compile_cc_source(request: CompileCCSourceRequest) -> FallibleCompiledCCObject:
    """Compile a single C/C++ source file."""

    field_set = request.field_set

    # Gather all required source files and dependencies
    target_source_file = await Get(SourceFiles, SourceFilesRequest([field_set.sources]))

    # inferred_source_files = await _infer_source_files(field_set)

    input_digest = await Get(
        Digest,
        MergeDigests((target_source_file.snapshot.digest,)),
    )

    # include_directories = _extract_include_directories(inferred_source_files)

    # Generate target compilation args
    target_file = target_source_file.files[0]
    compiled_object_name = f"{target_file}.o"

    # argv = []
    # for d in include_directories:
    # argv += ["-I", f"{d}/include"]
    # TODO: Testing compilation database - clang only
    # argv += ["-MJ", "compile_commands.json", ""]
    # Apply target compile options and defines

    # argv += field_set.compile_flags.value or []
    # argv += field_set.defines.value or []
    # argv += ["-c", target_file, "-o", compiled_object_name]

    compile_result = await Get(
        FallibleProcessResult,
        CCProcess(
            args=(
                "-c",
                target_file,
                "-o",
                compiled_object_name,
            ),
            language=field_set.language.normalized_value(),
            input_digest=input_digest,
            output_files=(compiled_object_name,),
            description=f"Compile CC source file: {target_file}",
            level=LogLevel.DEBUG,
        ),
    )

    logger.debug(compile_result.stderr)
    return FallibleCompiledCCObject(compiled_object_name, compile_result)


def rules() -> Iterable[Rule | UnionRule]:
    return collect_rules()
