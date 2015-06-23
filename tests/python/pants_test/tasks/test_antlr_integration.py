# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import time

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class AntlrIntegrationTest(PantsRunIntegrationTest):
  def test_run_antlr3(self):
    stdout_data = self.bundle_and_run('examples/src/java/org/pantsbuild/example/antlr3', 'antlr3',
                                      args=['7*8'])
    self.assertEquals('56.0', stdout_data.rstrip(), msg="got output:{0}".format(stdout_data))

  def test_run_antlr4(self):
    stdout_data = self.bundle_and_run('examples/src/java/org/pantsbuild/example/antlr4', 'antlr4',
                                      args=['7*6'])
    self.assertEquals('42.0', stdout_data.rstrip(), msg="got output:{0}".format(stdout_data))


  # Test that antlr3 and antlr4 generated java targets are cache-able.
  def test_compile_antlr_cached(self):
    for enable_zinc_java in ['--compile-zinc-java-enabled', '--no-compile-zinc-java-enabled']:
      # Use the same temporary workdir because generated target's name includes the workdir.
      # Use the same artifact_cache dir to share artifacts across two runs.
      with temporary_dir(root_dir=self.workdir_root()) as tmp_workdir:
        with temporary_dir(root_dir=self.workdir_root()) as artifact_cache:
          # Note that this only works as a test with clean-all because AntlrGen does not use
          # the artifact cache, just the local build invalidator.  As such, the clean-all
          # actually forces it to re-gen _unlike_ the jvm compile tasks.  If AntlrGen starts
          # using the artifact cache this test will pass even if the generated synthetic target
          # was uncacheable due to changing fingerprints, because the .g files have not changed
          # between runs and AntlrGen will not re-gen.
          compile_antlr_args = [
            'clean-all',
            'compile',
            "--cache-gen-antlr-write-to=['{}']".format(artifact_cache),
            "--cache-gen-antlr-read-from=['{}']".format(artifact_cache),
            enable_zinc_java,
            'examples/src/antlr/org/pantsbuild/example/exp::'
          ]
          # First run should generate and cache artifacts.
          pants_run = self.run_pants_with_workdir(compile_antlr_args, tmp_workdir)
          self.assert_success(pants_run)
          self.assertIn('Caching artifacts for 2 targets.', pants_run.stdout_data)

          # Sleeps 1 second to ensure the timestamp in sources generated by antlr is different.
          time.sleep(1)

          # Second run should use the cached artifacts (even with clean-all).
          pants_run = self.run_pants_with_workdir(compile_antlr_args, tmp_workdir)
          self.assert_success(pants_run)
          self.assertIn('Using cached artifacts for 2 targets.', pants_run.stdout_data)

  def test_python_invalid_antlr_grammar_fails(self):
    result = self.run_pants(['test',
                             'testprojects/src/python/antlr:test_antlr_failure'])
    self.assertNotEqual(0, result.returncode)
