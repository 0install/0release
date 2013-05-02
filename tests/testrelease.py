#!/usr/bin/env python
# Copyright (C) 2007, Thomas Leonard
# See the README file for details, or visit http://0install.net.
import sys, os, shutil, tempfile, subprocess, imp
from StringIO import StringIO
import unittest

from zeroinstall.injector import model, qdom, writer
from zeroinstall.injector.config import load_config
from zeroinstall.support import basedir, ro_rmtree

sys.path.insert(0, '..')
os.environ['http_proxy'] = 'localhost:1111'	# Prevent accidental network access

import support
import release		# (sets sys.path for 0repo)
import repo.cmd

mydir = os.path.realpath(os.path.dirname(__file__))
release_feed = mydir + '/../0release.xml'
test_repo = mydir + '/test-repo.tgz'
test_repo_actions = mydir + '/test-repo-actions.tgz'
test_repo_c = mydir + '/c-prog.tgz'
test_gpg = mydir + '/gpg.tgz'

test_config = """
[global]
freshness = 0
auto_approve_keys = True
help_with_testing = True
network_use = full
"""

CUSTOM_REPO_CONFIG = """
REPOSITORY_BASE_URL = "http://0install.net/tests/"
ARCHIVES_BASE_URL = "http://TESTING/releases"

def upload_archives(archives):
	for dir_rel_url, files in paths.group_by_target_url_dir(archives):
		target_dir = join('..', 'releases', 'archives')	# hack: skip dir_rel_url
		if not os.path.isdir(target_dir):
			os.makedirs(target_dir)
		subprocess.check_call(["cp"] + files + [target_dir])

def check_new_impl(impl):
	pass

def get_archive_rel_url(archive_basename, impl):
	return "{version}/{archive}".format(
		version = impl.get_version(),
		archive = archive_basename)
"""

def call_with_output_suppressed(cmd, stdin, expect_failure = False, **kwargs):
	#cmd = [cmd[0], '-v'] + cmd[1:]
	if stdin:
		child = subprocess.Popen(cmd, stdin = subprocess.PIPE, stdout = subprocess.PIPE, **kwargs)
	else:
		child = subprocess.Popen(cmd, stdout = subprocess.PIPE, **kwargs)
	stdout, stderr  = child.communicate(stdin)
	if (child.returncode != 0) == expect_failure:
		return stdout, stderr
	#print stdout, stderr
	raise Exception("Return code %d from %s\nstdout: %s\nstderr: %s" % (child.returncode, cmd, stdout, stderr))

def make_releases_dir(src_feed = '../hello/HelloWorld.xml', auto_upload = False):
	os.chdir('releases')
	call_with_output_suppressed(['0release', src_feed], None)
	assert os.path.isfile('make-release')

	lines = file('make-release').readlines()
	lines[lines.index('ARCHIVE_DIR_PUBLIC_URL=\n')] = 'ARCHIVE_DIR_PUBLIC_URL=http://TESTING/releases/\\$RELEASE_VERSION\n'

	# Force us to test against this version of 0release
	for i, line in enumerate(lines):
		if line.startswith('exec 0launch http://0install.net/2007/interfaces/0release.xml --release'):
			lines[i] = '0release --release ' + line.split('--release ', 1)[1]
			break
	else:
		assert 0

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

		config_dir = os.path.join(self.tmp, 'config')
		injector_config = os.path.join(config_dir, '0install.net', 'injector')
		os.makedirs(injector_config)
		s = open(os.path.join(injector_config, 'global'), 'w')
		s.write(test_config)
		s.close()

		if 'ZEROINSTALL_PORTABLE_BASE' in os.environ:
			del os.environ['ZEROINSTALL_PORTABLE_BASE']
		os.environ['XDG_CONFIG_HOME'] = config_dir
		imp.reload(basedir)
		assert basedir.xdg_config_home == config_dir

	def tearDown(self):
		os.chdir(mydir)
		ro_rmtree(self.tmp)

	def testSimple(self):
		support.check_call(['tar', 'xzf', test_repo])
		make_releases_dir()

		call_with_output_suppressed(['./make-release', '-k', 'Testing'], '\nP\n\n')

		call_with_output_suppressed(['./make-release', '-k', 'Testing'], '\nP\nY\n\n')

		assert 'Prints "Hello World"' in file('0.1/changelog-0.1').read()
		assert 'Prints "Hello World"' not in file('0.2/changelog-0.2').read()

	def testUncommitted(self):
		support.check_call(['tar', 'xzf', test_repo_actions])
		make_releases_dir()

		unused, stderr = call_with_output_suppressed(['./make-release', '-k', 'Testing'], None,
							expect_failure = True, stderr = subprocess.PIPE)
		assert "Uncommitted changes!" in stderr

	def testActions(self):
		support.check_call(['tar', 'xzf', test_repo_actions])
		os.chdir('hello')
		support.check_call(['git', 'commit', '-a', '-m', 'Added release instructions'], stdout = subprocess.PIPE)
		os.chdir('..')
		make_releases_dir()

		assert "version = '0.2'\n" not in file('../hello/hello.py').read()

		child = subprocess.Popen(['./make-release', '-k', 'Testing'], stdin = subprocess.PIPE, stdout = subprocess.PIPE)
		unused, unused = child.communicate('\nP\n\n')
		assert child.returncode == 0

		assert "version = '0.2'\n" in file('../hello/hello.py').read()

	def testBinaryRelease(self):
		support.check_call(['tar', 'xzf', test_repo_c])
		make_releases_dir(src_feed = '../c-prog/c-prog.xml', auto_upload = True)

		call_with_output_suppressed(['./make-release', '-k', 'Testing', '--builders=host'], '\nP\n\n')

		feed = self.get_public_feed('HelloWorld-in-C.xml', 'c-prog.xml')

		assert len(feed.implementations) == 2
		src_impl, = [x for x in feed.implementations.values() if x.arch == '*-src']
		host_impl, = [x for x in feed.implementations.values() if x.arch != '*-src']

		assert src_impl.main == None
		assert host_impl.main == 'hello'

		archives = os.listdir('archives')
		assert os.path.basename(src_impl.download_sources[0].url) in archives, src_impl.download_sources[0].url

		host_download = host_impl.download_sources[0]
		self.assertEqual('http://TESTING/releases/1.1/helloworld-in-c-linux-x86_64-1.1.tar.bz2',
				host_download.url)
		host_archive = os.path.basename(host_download.url)
		assert host_archive in archives
		support.check_call(['tar', 'xjf', os.path.join('archives', host_archive)])
		c = subprocess.Popen(['0launch', os.path.join(host_download.extract, '0install', 'feed.xml')], stdout = subprocess.PIPE)
		output, _ = c.communicate()

		self.assertEquals("Hello from C! (version 1.1)\n", output)
	
	def get_public_feed(self, name, uri_basename):
		with open(name, 'rb') as stream:
			return model.ZeroInstallFeed(qdom.parse(stream))

def run_repo(args):
	oldcwd = os.getcwd()

	old_stdout = sys.stdout
	sys.stdout = StringIO()
	try:
		sys.stdin = StringIO('\n')	# (simulate a press of Return if needed)
		repo.cmd.main(['0repo'] + args)
		return sys.stdout.getvalue()
	finally:
		os.chdir(oldcwd)
		sys.stdout = old_stdout

class TestRepoRelease(TestRelease):
	def setUp(self):
		TestRelease.setUp(self)

		# Let GPG initialise (it's a bit verbose)
		child = subprocess.Popen(['gpg', '-q', '--list-secret-keys'], stdout = subprocess.PIPE, stderr = subprocess.PIPE)
		unused, unused = child.communicate()
		child.wait()
		
		run_repo(['create', 'my-repo', 'Testing <testing@example.com>'])
		os.chdir('my-repo')

		if '0repo-config' in sys.modules:
			del sys.modules['0repo-config']

		with open('0repo-config.py', 'at') as stream:
			stream.write(CUSTOM_REPO_CONFIG)
		run_repo(['register'])
		os.chdir('..')
	
	def get_public_feed(self, name, uri_basename):
		with open(os.path.join(self.tmp, 'my-repo', 'public', uri_basename), 'rb') as stream:
			return model.ZeroInstallFeed(qdom.parse(stream))
	
unittest.makeSuite(TestRelease)
unittest.makeSuite(TestRepoRelease)
if __name__ == '__main__':
	unittest.main()
