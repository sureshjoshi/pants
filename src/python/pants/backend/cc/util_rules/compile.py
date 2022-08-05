# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable

from pants.backend.cc.dependency_inference.rules import (
    CCDependencyInferenceFieldSet,
    InferCCDependenciesRequest,
)
from pants.backend.cc.subsystems.toolchain import CCToolchain
from pants.backend.cc.target_types import CC_HEADER_FILE_EXTENSIONS
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, MultiGet, Rule, collect_rules, rule
from pants.engine.target import (
    InferredDependencies,
    SourcesField,
    Target,
    WrappedTarget,
    WrappedTargetRequest,
)
from pants.engine.unions import UnionRule

logger = logging.getLogger(__name__)

# @dataclass(frozen=True)
# class CompileCCSourceRequest:
#     name: str
#     targets: Iterable[Target]


@dataclass(frozen=True)
class FallibleCompiledCCObject:
    name: str
    process_result: FallibleProcessResult


@dataclass(frozen=True)
class CompileCCSourceRequest:
    # field_sets = (CCFieldSet, CCGeneratorFieldSet)
    target: Target


@rule(desc="Compile CC source with the current toolchain")
async def compile_cc_source(
    toolchain: CCToolchain, request: CompileCCSourceRequest
) -> FallibleCompiledCCObject:

    # Try to determine what this file needs in its digest to compile correctly (i.e. which header files)
    inferred_dependencies = await Get(
        InferredDependencies,
        InferCCDependenciesRequest(CCDependencyInferenceFieldSet.create(request.target)),
    )

    # Convert inferred dependency addresses into targets
    wrapped_targets = await MultiGet(
        Get(
            WrappedTarget,
            WrappedTargetRequest(address, description_of_origin="<cc/util_rules/compile.py>"),
        )
        for address in inferred_dependencies.include
    )

    # Gather all required source files and dependencies
    target_source_file = await Get(
        SourceFiles, SourceFilesRequest([request.target.get(SourcesField)])
    )

    inferred_source_files = await Get(
        SourceFiles,
        SourceFilesRequest(
            [wrapped_target.target.get(SourcesField) for wrapped_target in wrapped_targets]
        ),
    )
    logger.debug(inferred_source_files.snapshot)

    input_digest = await Get(
        Digest,
        MergeDigests((target_source_file.snapshot.digest, inferred_source_files.snapshot.digest)),
    )

    # Add header include directories to compilation args prefixed with "-I"
    inferred_header_files = [
        file
        for file in inferred_source_files.files
        if PurePath(file).suffix in CC_HEADER_FILE_EXTENSIONS
    ]
    # TODO: This "/inc" is hardcoded - not a robust way to determine which folders should be included here
    include_directories = [
        file.split("/inc")[0] for file in inferred_header_files if "/inc" in file
    ]

    target_file = target_source_file.files[0]
    compiled_object_name = f"{target_file}.o"

    # TODO: While gcc will usually pick the correct tool under the hood, we may want to make it explicit
    # TODO: How should we handle compiling .c files with C++?
    argv = [toolchain.c]
    for d in include_directories:
        argv += ["-I", f"{d}/include"]
    argv += ["-c", target_file]

    compile_result = await Get(
        FallibleProcessResult,
        Process(
            argv=argv,
            input_digest=input_digest,
            description=f"Compile CC source file: {target_file}",
            output_files=(compiled_object_name,),
        ),
    )
    return FallibleCompiledCCObject(compiled_object_name, compile_result)


def rules() -> Iterable[Rule | UnionRule]:
    return collect_rules()
