# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from pants.backend.python.target_types import PythonSourceField
from pants.backend.python.util_rules import ancestor_files
from pants.backend.python.util_rules.ancestor_files import AncestorFilesRequest, find_ancestor_files
from pants.core.target_types import FileSourceField, ResourceSourceField
from pants.core.util_rules import source_files, stripped_source_files
from pants.core.util_rules.source_files import (
    SourceFiles,
    SourceFilesRequest,
    determine_source_files,
)
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles, strip_source_roots
from pants.engine.fs import EMPTY_SNAPSHOT, MergeDigests
from pants.engine.internals.graph import hydrate_sources
from pants.engine.intrinsics import digest_to_snapshot
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.target import HydrateSourcesRequest, SourcesField, Target
from pants.engine.unions import UnionMembership
from pants.source.source_root import SourceRootRequest, get_source_root
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PythonSourceFiles:
    """Sources that can be introspected by Python, relative to a set of source roots.

    Specifically, this will filter out to only have Python, and, optionally, resource and
    file targets; and will add any missing `__init__.py` files to ensure that modules are
    recognized correctly.

    Use-cases that introspect Python source code (e.g., the `test, `lint`, `fmt` goals) can
    request this type to get relevant sources that are still relative to their source roots.
    That way the paths they report are the unstripped ones the user is familiar with.

    The sources can also be imported and used by Python (e.g., for the `test` goal), but only
    if sys.path is modified to include the source roots.
    """

    source_files: SourceFiles
    source_roots: tuple[str, ...]  # Source roots for the specified source files.

    @classmethod
    def empty(cls) -> PythonSourceFiles:
        return cls(SourceFiles(EMPTY_SNAPSHOT, tuple()), tuple())


@dataclass(frozen=True)
class StrippedPythonSourceFiles:
    """A PythonSourceFiles that has had its source roots stripped."""

    stripped_source_files: StrippedSourceFiles


@dataclass(unsafe_hash=True)
class PythonSourceFilesRequest:
    targets: tuple[Target, ...]
    include_resources: bool
    # NB: Setting this to True may cause Digest merge collisions, in the presence of
    #  relocated_files targets that relocate two different files to the same destination.
    #  Set this to True only if you know this cannot logically happen (e.g., if it did
    #  happen the underlying user operation would make no sense anyway).
    #  For example, if the user relocates different config files to the same location
    #  in different tests, there is no problem as long as we sandbox each test's sources
    #  separately. The user may hit this issue if they run tests in batches, but in that
    #  case they couldn't make that work even without Pants.
    include_files: bool

    def __init__(
        self,
        targets: Iterable[Target],
        *,
        include_resources: bool = True,
        include_files: bool = False,
    ) -> None:
        object.__setattr__(self, "targets", tuple(targets))
        object.__setattr__(self, "include_resources", include_resources)
        object.__setattr__(self, "include_files", include_files)

    @property
    def valid_sources_types(self) -> tuple[type[SourcesField], ...]:
        types: list[type[SourcesField]] = [PythonSourceField]
        if self.include_resources:
            types.append(ResourceSourceField)
        if self.include_files:
            types.append(FileSourceField)
        return tuple(types)


@rule(level=LogLevel.DEBUG)
async def prepare_python_sources(
    request: PythonSourceFilesRequest, union_membership: UnionMembership
) -> PythonSourceFiles:
    sources = await determine_source_files(
        SourceFilesRequest(
            (tgt.get(SourcesField) for tgt in request.targets),
            for_sources_types=request.valid_sources_types,
            enable_codegen=True,
        )
    )

    missing_init_files = await find_ancestor_files(
        AncestorFilesRequest(
            input_files=sources.snapshot.files, requested=("__init__.py", "__init__.pyi")
        )
    )
    init_injected = await digest_to_snapshot(
        **implicitly(MergeDigests((sources.snapshot.digest, missing_init_files.snapshot.digest)))
    )

    # Codegen is able to generate code in any arbitrary location, unlike sources normally being
    # rooted under the target definition. To determine source roots for these generated files, we
    # cannot use the normal `SourceRootRequest.for_target()` and we instead must determine
    # a source root for every individual generated file. So, we re-resolve the codegen sources here.
    python_and_resources_targets = []
    codegen_targets = []
    for tgt in request.targets:
        if tgt.has_field(PythonSourceField) or tgt.has_field(ResourceSourceField):
            python_and_resources_targets.append(tgt)
        elif tgt.get(SourcesField).can_generate(PythonSourceField, union_membership) or tgt.get(
            SourcesField
        ).can_generate(ResourceSourceField, union_membership):
            codegen_targets.append(tgt)
    codegen_sources = await concurrently(
        hydrate_sources(
            HydrateSourcesRequest(
                tgt.get(SourcesField),
                for_sources_types=request.valid_sources_types,
                enable_codegen=True,
            ),
            **implicitly(),
        )
        for tgt in codegen_targets
    )
    source_root_requests = [
        *(SourceRootRequest.for_target(tgt) for tgt in python_and_resources_targets),
        *(
            SourceRootRequest.for_file(f)
            for sources in codegen_sources
            for f in sources.snapshot.files
        ),
    ]

    source_root_objs = await concurrently(get_source_root(req) for req in source_root_requests)
    source_root_paths = {source_root_obj.path for source_root_obj in source_root_objs}
    return PythonSourceFiles(
        SourceFiles(init_injected, sources.unrooted_files), tuple(sorted(source_root_paths))
    )


@rule(level=LogLevel.DEBUG)
async def strip_python_sources(python_sources: PythonSourceFiles) -> StrippedPythonSourceFiles:
    stripped = await strip_source_roots(python_sources.source_files)
    return StrippedPythonSourceFiles(stripped)


def rules():
    return [
        *collect_rules(),
        *ancestor_files.rules(),
        *source_files.rules(),
        *stripped_source_files.rules(),
    ]
