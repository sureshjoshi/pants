# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass

from pants.backend.shell.subsystems.shell_setup import ShellSetup
from pants.backend.shell.target_types import (
    ShellSourcesGeneratorTarget,
    Shunit2TestsGeneratorSourcesField,
    Shunit2TestsGeneratorTarget,
)
from pants.core.goals.tailor import (
    AllOwnedSources,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsRequest,
)
from pants.engine.intrinsics import path_globs_to_paths
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.target import Target
from pants.engine.unions import UnionRule
from pants.source.filespec import FilespecMatcher
from pants.util.dirutil import group_by_dir
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PutativeShellTargetsRequest(PutativeTargetsRequest):
    pass


def classify_source_files(paths: Iterable[str]) -> dict[type[Target], set[str]]:
    """Returns a dict of target type -> files that belong to targets of that type."""
    tests_filespec_matcher = FilespecMatcher(Shunit2TestsGeneratorSourcesField.default, ())
    test_filenames = set(tests_filespec_matcher.matches([os.path.basename(path) for path in paths]))
    test_files = {path for path in paths if os.path.basename(path) in test_filenames}
    sources_files = set(paths) - test_files
    return {Shunit2TestsGeneratorTarget: test_files, ShellSourcesGeneratorTarget: sources_files}


@rule(level=LogLevel.DEBUG, desc="Determine candidate shell targets to create")
async def find_putative_targets(
    req: PutativeShellTargetsRequest, all_owned_sources: AllOwnedSources, shell_setup: ShellSetup
) -> PutativeTargets:
    if not (shell_setup.tailor_sources or shell_setup.tailor_shunit2_tests):
        return PutativeTargets()

    all_shell_files = await path_globs_to_paths(req.path_globs("*.sh"))
    unowned_shell_files = set(all_shell_files.files) - set(all_owned_sources)
    classified_unowned_shell_files = classify_source_files(unowned_shell_files)
    pts: list[PutativeTarget] = []
    for tgt_type, paths in classified_unowned_shell_files.items():
        for dirname, filenames in group_by_dir(paths).items():
            if tgt_type == Shunit2TestsGeneratorTarget:
                if not shell_setup.tailor_shunit2_tests:
                    continue
                name = "tests"
            else:
                if not shell_setup.tailor_sources:
                    continue
                name = None

            pts.append(
                PutativeTarget.for_target_type(
                    tgt_type, path=dirname, name=name, triggering_sources=sorted(filenames)
                )
            )
    return PutativeTargets(pts)


def rules() -> Iterable[Rule | UnionRule]:
    return (*collect_rules(), UnionRule(PutativeTargetsRequest, PutativeShellTargetsRequest))
