# Copyright (C) 2009, Thomas Leonard
# See the README file for details, or visit http://0install.net.

import tempfile, shutil, subprocess, os
import ConfigParser
from logging import info
from zeroinstall.injector import model
from zeroinstall.support import basedir

import support

COMPILE = 'http://0install.net/2006/interfaces/0compile.xml'

class Compiler:
	def __init__(self, options, src_feed_name):
		self.src_feed_name = src_feed_name
		self.src_feed = support.load_feed(src_feed_name)
		self.archive_dir_public_url = options.archive_dir_public_url
		assert options.archive_dir_public_url

		self.config = ConfigParser.RawConfigParser()

		# Start with a default configuration
		self.config.add_section('global')
		self.config.set('global', 'builders', 'host')

		self.config.add_section('builder-host')
		self.config.set('builder-host', 'build', '0launch --not-before 0.10 http://0install.net/2007/interfaces/0release.xml --build-slave "$@"')

		self.src_impl = support.get_singleton_impl(self.src_feed)
		if self.src_impl.arch and self.src_impl.arch.endswith('-src'):
			path = basedir.load_first_config('0install.net', '0release', 'builders.conf')
			if path:
				info("Loading configuration file '%s'", path)
				self.config.read(path)
			else:
				info("No builders.conf configuration; will build a binary for this host only")

			if options.builders is not None:
				builders = options.builders
			else:
				builders = self.config.get('global', 'builders').strip()
			if builders:
				self.targets = [x.strip() for x in builders.split(',')]
				info("%d build targets configured: %s", len(self.targets), self.targets)
			else:
				self.targets = []
				info("No builders set; no binaries will be built")
		else:
			self.targets = []

	# We run the build in a sub-process. The idea is that the build may need to run
	# on a different machine.
	def build_binaries(self):
		if not self.targets: return

		print "Source package, so generating binaries..."

		archive_file = support.get_archive_basename(self.src_impl)

		for target in self.targets:
			start = self.get('builder-' + target, 'start', None)
			command = self.config.get('builder-' + target, 'build')
			stop = self.get('builder-' + target, 'stop', None)

			binary_feed = 'binary-' + target + '.xml'
			if os.path.exists(binary_feed):
				print "Feed %s already exists; not rebuilding" % binary_feed
			else:
				print "\nBuilding binary with builder '%s' ...\n" % target

				if start: support.show_and_run(start, [])
				try:
					support.show_and_run(command, [os.path.basename(self.src_feed_name), archive_file, self.archive_dir_public_url, binary_feed + '.new'])
				finally:
					if stop: support.show_and_run(stop, [])

				bin_feed = support.load_feed(binary_feed + '.new')
				bin_impl = support.get_singleton_impl(bin_feed)
				bin_archive_file = support.get_archive_basename(bin_impl)
				bin_size = bin_impl.download_sources[0].size

				assert os.path.exists(bin_archive_file), "Compiled binary '%s' not found!" % os.path.abspath(bin_archive_file)
				assert os.path.getsize(bin_archive_file) == bin_size, "Compiled binary '%s' has wrong size!" % os.path.abspath(bin_archive_file)

				os.rename(binary_feed + '.new', binary_feed)

	def get_binary_feeds(self):
		return ['binary-%s.xml' % target for target in self.targets]

	def get(self, section, option, default):
		try:
			return self.config.get(section, option)
		except ConfigParser.NoOptionError:
			return default

# This is the actual build process, running on the build machine
def build_slave(src_feed, archive_file, archive_dir_public_url, target_feed):
	feed = support.load_feed(src_feed)

	src_feed = os.path.abspath(src_feed)
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

		support.check_call(['0launch', COMPILE, '--not-before=0.30', 'build'], cwd = tmpdir)
		support.check_call(['0launch', COMPILE, '--not-before=0.30', 'publish', '--target-feed', target_feed], cwd = tmpdir)

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
