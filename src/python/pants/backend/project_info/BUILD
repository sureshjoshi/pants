# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()

python_tests(
    name="tests",
    timeout=180,
    overrides={
        "list_integration_test.py": {
            "dependencies": ["testprojects/src/python:hello_directory"],
            "timeout": 240,
        },
        "list_targets_test.py": {
            "dependencies": ["//BUILD_ROOT:files"],
        },
        "count_loc_test.py": {
            "tags": ["platform_specific_behavior"],
        },
    },
)
