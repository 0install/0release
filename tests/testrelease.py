#!/usr/bin/env python2.5
# Copyright (C) 2007, Thomas Leonard
# See the README file for details, or visit http://0install.net.
import sys, os, shutil, tempfile, subprocess
import unittest

sys.path.insert(0, '..')

import support

mydir = os.path.realpath(os.path.dirname(__file__))
release_feed = mydir + '/../0release.xml'
test_repo = mydir + '/test-repo.tgz'
test_gpg = mydir + '/gpg.tgz'

class TestRelease(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.mkdtemp(prefix = '0release-')
		os.chdir(self.tmp)
		support.check_call(['tar', 'xzf', test_repo])
		support.check_call(['tar', 'xzf', test_gpg])
		os.mkdir('releases')
		os.environ['GNUPGHOME'] = self.tmp + '/gpg'
	
	def tearDown(self):
		os.chdir(mydir)
		shutil.rmtree(self.tmp)

	def testSimple(self):
		os.chdir('releases')
		support.check_call(['0launch', release_feed, '../hello/HelloWorld.xml'])
		assert os.path.isfile('make-release')

		lines = file('make-release').readlines()
		lines[lines.index('ARCHIVE_DIR_PUBLIC_URL=\n')] = 'ARCHIVE_DIR_PUBLIC_URL=http://TESTING/releases\n'
		s = file('make-release', 'w')
		s.write(''.join(lines))
		s.close()

		child = subprocess.Popen(['./make-release', '-k', 'Testing'], stdin = subprocess.PIPE)
		unused, unused = child.communicate('\nP\n\n')
		assert child.returncode == 0

		child = subprocess.Popen(['./make-release', '-k', 'Testing'], stdin = subprocess.PIPE)
		unused, unused = child.communicate('\nP\n\n')
		assert child.returncode == 0

		assert 'Prints "Hello World"' in file('changelog-0.1').read()
		assert 'Prints "Hello World"' not in file('changelog-0.2').read()

suite = unittest.makeSuite(TestRelease)
if __name__ == '__main__':
	sys.argv.append('-v')
	unittest.main()
