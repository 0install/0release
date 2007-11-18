#!/usr/bin/env python2.5
import sys, os, shutil, tempfile, subprocess
import unittest

sys.path.insert(0, '..')

mydir = os.path.dirname(__file__)
release_feed = os.path.realpath(mydir + '/../0release.xml')
test_repo = os.path.realpath(mydir + '/test-repo.tgz')
test_gpg = os.path.realpath(mydir + '/gpg.tgz')

class TestRelease(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.mkdtemp(prefix = '0release-')
		os.chdir(self.tmp)
		subprocess.check_call(['tar', 'xzf', test_repo])
		subprocess.check_call(['tar', 'xzf', test_gpg])
		os.mkdir('releases')
		os.environ['GNUPGHOME'] = self.tmp + '/gpg'
	
	def tearDown(self):
		os.chdir('/')
		shutil.rmtree(self.tmp)

	def testSimple(self):
		os.chdir('releases')
		subprocess.check_call(['0launch', release_feed, '../hello/HelloWorld.xml'])
		assert os.path.isfile('make-release')

		child = subprocess.Popen(['./make-release', '-k', 'Testing'], stdin = subprocess.PIPE)
		unused, unused = child.communicate('\nP\n')
		assert child.returncode == 0

		child = subprocess.Popen(['./make-release', '-k', 'Testing'], stdin = subprocess.PIPE)
		unused, unused = child.communicate('\nP\n')
		assert child.returncode == 0

		assert 'Prints "Hello World"' in file('changelog-0.1').read()
		assert 'Prints "Hello World"' not in file('changelog-0.2').read()

suite = unittest.makeSuite(TestRelease)
if __name__ == '__main__':
	sys.argv.append('-v')
	unittest.main()
