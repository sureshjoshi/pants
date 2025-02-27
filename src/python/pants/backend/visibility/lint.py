# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.backend.visibility.subsystem import VisibilitySubsystem
from pants.core.goals.lint import LintResult, LintTargetsRequest
from pants.core.util_rules.partitions import PartitionerType
from pants.engine.internals.build_files import get_dependencies_rule_application
from pants.engine.internals.dep_rules import DependencyRuleActionDeniedError
from pants.engine.internals.graph import resolve_dependencies
from pants.engine.internals.session import RunId
from pants.engine.platform import Platform
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.target import (
    AlwaysTraverseDeps,
    Dependencies,
    DependenciesRequest,
    DependenciesRuleApplicationRequest,
    FieldSet,
)
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class VisibilityFieldSet(FieldSet):
    required_fields = (Dependencies,)
    dependencies: Dependencies


class EnforceVisibilityRules(LintTargetsRequest):
    tool_subsystem = VisibilitySubsystem
    field_set_type = VisibilityFieldSet
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION


@rule(desc="Check for visibility rule violations", level=LogLevel.DEBUG)
async def check_visibility_rule_violations(
    request: EnforceVisibilityRules.Batch, platform: Platform, run_id: RunId
) -> LintResult:
    all_dependencies = await concurrently(
        resolve_dependencies(
            DependenciesRequest(
                field_set.dependencies,
                should_traverse_deps_predicate=AlwaysTraverseDeps(),
            ),
            **implicitly(),
        )
        for field_set in request.elements
    )
    all_dependencies_rule_action = await concurrently(
        get_dependencies_rule_application(
            DependenciesRuleApplicationRequest(
                address=field_set.address,
                dependencies=dependencies,
                description_of_origin=f"get dependency rules for {field_set.address}",
            ),
            **implicitly(),
        )
        for field_set, dependencies in zip(request.elements, all_dependencies)
    )

    violations: list[str] = []
    for deps_rule_action in all_dependencies_rule_action:
        try:
            deps_rule_action.execute_actions()
        except DependencyRuleActionDeniedError as e:
            violations.append(str(e))

    return LintResult(
        exit_code=0 if not violations else 1,
        stdout="\n\n".join(violations),
        stderr="",
        linter_name=request.tool_name,
        partition_description=request.partition_metadata.description,
    )


def rules():
    return (
        *collect_rules(),
        *EnforceVisibilityRules.rules(),
    )
