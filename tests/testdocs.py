#!/usr/bin/env python2.5
# Copyright (C) 2007, Thomas Leonard
# See the README file for details, or visit http://0install.net.

import unittest, os, sys
import doctest

sys.path.insert(0, '..')

import support

main_dir = os.path.join(os.path.dirname(__file__), '..')

suite = unittest.TestSuite()
for x in [support]:
	suite.addTest(doctest.DocTestSuite(x))

if __name__ == '__main__':
	runner = unittest.TextTestRunner(verbosity = 2)
	runner.run(suite)
