# Copyright (C) 2009, Thomas Leonard
# See the README file for details, or visit http://0install.net.

import tempfile, shutil, subprocess, os
import ConfigParser
from zeroinstall.injector import model

import support

COMPILE = 'http://0install.net/2006/interfaces/0compile.xml'
RELEASE = 'http://0install.net/2007/interfaces/0release.xml'

class Compiler:
	def __init__(self, options, src_feed_name):
		self.src_feed_name = src_feed_name
		self.src_feed = support.load_feed(src_feed_name)
		self.archive_dir_public_url = options.archive_dir_public_url
		assert options.archive_dir_public_url

		self.src_impl = support.get_singleton_impl(self.src_feed)
		if self.src_impl.arch and self.src_impl.arch.endswith('-src'):
			self.targets = ['host']
		else:
			self.targets = []

	# We run the build in a sub-process. The idea is that the build may need to run
	# on a different machine.
	def build_binaries(self):
		if not self.targets: return

		print "Source package, so generating binaries..."

		archive_file = support.get_archive_basename(self.src_impl)

		for arch in self.targets:
			if arch == 'host':
				command = ['0launch', '--not-before', '0.8-post', RELEASE, '--build-slave']
			else:
				command = ['0release-build', arch]

			binary_feed = 'binary-' + arch + '.xml'
			if os.path.exists(binary_feed):
				print "Feed %s already exists; not rebuilding" % binary_feed
			else:
				print "\nBuilding binary for %s architecture...\n" % arch
				subprocess.check_call(command + [self.src_feed_name, archive_file, self.archive_dir_public_url, binary_feed + '.new'])
				bin_feed = support.load_feed(binary_feed + '.new')
				bin_impl = support.get_singleton_impl(bin_feed)
				bin_archive_file = support.get_archive_basename(bin_impl)
				bin_size = bin_impl.download_sources[0].size

				assert os.path.exists(bin_archive_file), "Compiled binary '%s' not found!" % os.path.abspath(bin_archive_file)
				assert os.path.getsize(bin_archive_file) == bin_size, "Compiled binary '%s' has wrong size!" % os.path.abspath(bin_archive_file)

				os.rename(binary_feed + '.new', binary_feed)

	def get_binary_feeds(self):
		return ['binary-%s.xml' % arch for arch in self.targets]

# This is the actual build process, running on the build machine
def build_slave(src_feed, archive_file, archive_dir_public_url, target_feed):
	feed = support.load_feed(src_feed)

	archive_file = os.path.abspath(archive_file)
	target_feed = os.path.abspath(target_feed)

	impl, = feed.implementations.values()

	tmpdir = tempfile.mkdtemp(prefix = '0release-')
	try:
		os.chdir(tmpdir)
		depdir = os.path.join(tmpdir, 'dependencies')
		os.mkdir(depdir)

		support.unpack_tarball(archive_file)
		os.rename(impl.download_sources[0].extract, os.path.join(depdir, impl.id))

		config = ConfigParser.RawConfigParser()
		config.add_section('compile')
		config.set('compile', 'download-base-url', archive_dir_public_url)
		config.set('compile', 'version-modifier', '')
		config.set('compile', 'interface', src_feed)
		config.set('compile', 'selections', '')
		config.set('compile', 'metadir', '0install')
		stream = open(os.path.join(tmpdir, '0compile.properties'), 'w')
		try:
			config.write(stream)
		finally:
			stream.close()

		subprocess.check_call(['0launch', COMPILE, 'build'], cwd = tmpdir)
		subprocess.check_call(['0launch', COMPILE, 'publish', '--target-feed', target_feed], cwd = tmpdir)

		# TODO: run unit-tests

		feed = support.load_feed(target_feed)
		impl = support.get_singleton_impl(feed)
		archive_file = support.get_archive_basename(impl)

		shutil.move(archive_file, os.path.join(os.path.dirname(target_feed), archive_file))
	except:
		print "\nLeaving temporary directory %s for inspection...\n" % tmpdir
		raise
	else:
		shutil.rmtree(tmpdir)
