#!/usr/bin/env python2.5
# Copyright (C) 2007, Thomas Leonard
# See the README file for details, or visit http://0install.net.
import sys, os, shutil, tempfile, subprocess
import unittest
from zeroinstall.injector import model, qdom

sys.path.insert(0, '..')

import support

mydir = os.path.realpath(os.path.dirname(__file__))
release_feed = mydir + '/../0release.xml'
test_repo = mydir + '/test-repo.tgz'
test_repo_actions = mydir + '/test-repo-actions.tgz'
test_repo_c = mydir + '/c-prog.tgz'
test_gpg = mydir + '/gpg.tgz'

def make_releases_dir(src_feed = '../hello/HelloWorld.xml', auto_upload = False):
	os.chdir('releases')
	support.check_call(['0launch', release_feed, src_feed])
	assert os.path.isfile('make-release')

	lines = file('make-release').readlines()
	lines[lines.index('ARCHIVE_DIR_PUBLIC_URL=\n')] = 'ARCHIVE_DIR_PUBLIC_URL=http://TESTING/releases\n'

	if auto_upload:
		os.mkdir('archives')
		lines[lines.index('ARCHIVE_UPLOAD_COMMAND=\n')] = 'ARCHIVE_UPLOAD_COMMAND=\'cp "$@" ../archives/\'\n'

	s = file('make-release', 'w')
	s.write(''.join(lines))
	s.close()

class TestRelease(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.mkdtemp(prefix = '0release-')
		os.chdir(self.tmp)
		support.check_call(['tar', 'xzf', test_gpg])
		os.mkdir('releases')
		os.environ['GNUPGHOME'] = self.tmp + '/gpg'
		os.chmod(os.environ['GNUPGHOME'], 0700)
	
	def tearDown(self):
		os.chdir(mydir)
		shutil.rmtree(self.tmp)

	def testSimple(self):
		support.check_call(['tar', 'xzf', test_repo])
		make_releases_dir()

		child = subprocess.Popen(['./make-release', '-k', 'Testing'], stdin = subprocess.PIPE)
		unused, unused = child.communicate('\nP\n\n')
		assert child.returncode == 0

		child = subprocess.Popen(['./make-release', '-k', 'Testing'], stdin = subprocess.PIPE)
		unused, unused = child.communicate('\nP\n\n')
		assert child.returncode == 0

		assert 'Prints "Hello World"' in file('0.1/changelog-0.1').read()
		assert 'Prints "Hello World"' not in file('0.2/changelog-0.2').read()

	def testUncommitted(self):
		support.check_call(['tar', 'xzf', test_repo_actions])
		make_releases_dir()

		child = subprocess.Popen(['./make-release', '-k', 'Testing'], stdin = subprocess.PIPE, stderr = subprocess.PIPE)
		unused, stderr = child.communicate()
		assert child.returncode != 0
		assert "Uncommitted changes!" in stderr

	def testActions(self):
		support.check_call(['tar', 'xzf', test_repo_actions])
		os.chdir('hello')
		support.check_call(['git', 'commit', '-a', '-m', 'Added release instructions'])
		os.chdir('..')
		make_releases_dir()

		assert "version = '0.2'\n" not in file('../hello/hello.py').read()

		child = subprocess.Popen(['./make-release', '-k', 'Testing'], stdin = subprocess.PIPE)
		unused, unused = child.communicate('\nP\n\n')
		assert child.returncode == 0

		assert "version = '0.2'\n" in file('../hello/hello.py').read()

	def testBinaryRelease(self):
		support.check_call(['tar', 'xzf', test_repo_c])
		make_releases_dir(src_feed = '../c-prog/c-prog.xml', auto_upload = True)

		child = subprocess.Popen(['./make-release', '-k', 'Testing'], stdin = subprocess.PIPE)
		unused, unused = child.communicate('\nP\n\n')
		assert child.returncode == 0

		feed = model.ZeroInstallFeed(qdom.parse(file('HelloWorld-in-C.xml')))

		assert len(feed.implementations) == 2
		src_impl, = [x for x in feed.implementations.values() if x.arch == '*-src']
		host_impl, = [x for x in feed.implementations.values() if x.arch != '*-src']

		assert src_impl.main == None
		assert host_impl.main == 'hello'

		archives = os.listdir('archives')
		assert os.path.basename(src_impl.download_sources[0].url) in archives
		assert os.path.basename(host_impl.download_sources[0].url) in archives

suite = unittest.makeSuite(TestRelease)
if __name__ == '__main__':
	sys.argv.append('-v')
	unittest.main()
