# Copyright (C) 2009, Thomas Leonard
# See the README file for details, or visit http://0install.net.

import os, sys, subprocess, shutil, tempfile
from zeroinstall import SafeException
from zeroinstall.injector import reader, model, qdom
from zeroinstall.support import ro_rmtree
from logging import info, warn

import support, compile
from scm import get_scm

XMLNS_RELEASE = 'http://zero-install.sourceforge.net/2007/namespaces/0release'

valid_phases = ['commit-release', 'generate-archive']

TMP_BRANCH_NAME = '0release-tmp'

test_command = os.environ['0TEST']

def run_unit_tests(local_feed):
	print "Running self-tests..."
	exitstatus = subprocess.call([test_command, '--', local_feed])
	if exitstatus == 2:
		print "SKIPPED unit tests for %s (no 'self-test' attribute set)" % local_feed
		return
	if exitstatus:
		raise SafeException("Self-test failed with exit status %d" % exitstatus)

def get_archive_url(options, status, archive):
	archive_dir_public_url = options.archive_dir_public_url.replace('$RELEASE_VERSION', status.release_version)
	if not archive_dir_public_url.endswith('/'):
		archive_dir_public_url += '/'
	return archive_dir_public_url + archive

def upload_archives(options, status, uploads):
	# For each binary or source archive in uploads, ensure it is available
	# from options.archive_dir_public_url

	# We try to do all the uploads together first, and then verify them all
	# afterwards. This is because we may have to wait for them to be moved
	# from an incoming queue before we can test them.

	def url(archive):
		return get_archive_url(options, status, archive)

	# Check that url exists and has the given size
	def is_uploaded(url, size):
		if url.startswith('http://TESTING/releases'):
			return True

		print "Testing URL %s..." % url
		try:
			actual_size = int(support.get_size(url))
		except Exception, ex:
			print "Can't get size of '%s': %s" % (url, ex)
			return False
		else:
			if actual_size == size:
				return True
			print "WARNING: %s exists, but size is %d, not %d!" % (url, actual_size, size)
			return False

	# status.verified_uploads is an array of status flags:
	description = {
		'N': 'Upload required',
		'A': 'Upload has been attempted, but we need to check whether it worked',
		'V': 'Upload has been checked (exists and has correct size)',
	}

	if status.verified_uploads is None:
		# First time around; no point checking for existing uploads
		status.verified_uploads = 'N' * len(uploads)
		status.save()

	while True:
		print "\nUpload status:"
		for i, stat in enumerate(status.verified_uploads):
			print "- %s : %s" % (uploads[i], description[stat])
		print

		# Break if finished
		if status.verified_uploads == 'V' * len(uploads):
			break

		# Find all New archives
		to_upload = []
		for i, stat in enumerate(status.verified_uploads):
			assert stat in 'NAV'
			if stat == 'N':
				to_upload.append(uploads[i])
				print "Upload %s/%s as %s" % (status.release_version, uploads[i], url(uploads[i]))

		cmd = options.archive_upload_command.strip()

		if to_upload:
			# Mark all New items as Attempted
			status.verified_uploads = status.verified_uploads.replace('N', 'A')
			status.save()

			# Upload them...
			if cmd:
				support.show_and_run(cmd, to_upload)
			else:
				if len(to_upload) == 1:
					print "No upload command is set => please upload the archive manually now"
					raw_input('Press Return once the archive is uploaded.')
				else:
					print "No upload command is set => please upload the archives manually now"
					raw_input('Press Return once the %d archives are uploaded.' % len(to_upload))

		# Verify all Attempted uploads
		new_stat = ''
		for i, stat in enumerate(status.verified_uploads):
			assert stat in 'AV', status.verified_uploads
			if stat == 'A' :
				if not is_uploaded(url(uploads[i]), os.path.getsize(uploads[i])):
					print "** Archive '%s' still not uploaded! Try again..." % uploads[i]
					stat = 'N'
				else:
					stat = 'V'
			new_stat += stat

		status.verified_uploads = new_stat
		status.save()

		if 'N' in new_stat and cmd:
			raw_input('Press Return to try again.')

def do_release(local_iface, options):
	assert options.master_feed_file
	options.master_feed_file = os.path.abspath(options.master_feed_file)

	if not options.archive_dir_public_url:
		raise SafeException("Downloads directory not set. Edit the 'make-release' script and try again.")

	if not local_iface.feed_for:
		raise SafeException("Feed %s missing a <feed-for> element" % local_iface.uri)

	status = support.Status()
	local_impl = support.get_singleton_impl(local_iface)

	local_impl_dir = local_impl.id
	assert local_impl_dir.startswith('/')
	local_impl_dir = os.path.realpath(local_impl_dir)
	assert os.path.isdir(local_impl_dir)
	assert local_iface.uri.startswith(local_impl_dir + '/')

	# From the impl directory to the feed
	# NOT relative to the archive root (in general)
	local_iface_rel_path = local_iface.uri[len(local_impl_dir) + 1:]
	assert not local_iface_rel_path.startswith('/')
	assert os.path.isfile(os.path.join(local_impl_dir, local_iface_rel_path))

	phase_actions = {}
	for phase in valid_phases:
		phase_actions[phase] = []	# List of <release:action> elements

	add_toplevel_dir = None
	release_management = local_iface.get_metadata(XMLNS_RELEASE, 'management')
	if len(release_management) == 1:
		info("Found <release:management> element.")
		release_management = release_management[0]
		for x in release_management.childNodes:
			if x.uri == XMLNS_RELEASE and x.name == 'action':
				phase = x.getAttribute('phase')
				if phase not in valid_phases:
					raise SafeException("Invalid action phase '%s' in local feed %s. Valid actions are:\n%s" % (phase, local_iface.uri, '\n'.join(valid_phases)))
				phase_actions[phase].append(x.content)
			elif x.uri == XMLNS_RELEASE and x.name == 'add-toplevel-directory':
				add_toplevel_dir = local_iface.get_name()
			else:
				warn("Unknown <release:management> element: %s", x)
	elif len(release_management) > 1:
		raise SafeException("Multiple <release:management> sections in %s!" % local_iface)
	else:
		info("No <release:management> element found in local feed.")

	scm = get_scm(local_iface, options)

	# Path relative to the archive / SCM root
	local_iface_rel_root_path = local_iface.uri[len(scm.root_dir) + 1:]

	def run_hooks(phase, cwd, env):
		info("Running hooks for phase '%s'" % phase)
		full_env = os.environ.copy()
		full_env.update(env)
		for x in phase_actions[phase]:
			print "[%s]: %s" % (phase, x)
			support.check_call(x, shell = True, cwd = cwd, env = full_env)

	def set_to_release():
		print "Snapshot version is " + local_impl.get_version()
		suggested = support.suggest_release_version(local_impl.get_version())
		release_version = raw_input("Version number for new release [%s]: " % suggested)
		if not release_version:
			release_version = suggested

		scm.ensure_no_tag(release_version)

		status.head_before_release = scm.get_head_revision()
		status.save()

		working_copy = local_impl.id
		run_hooks('commit-release', cwd = working_copy, env = {'RELEASE_VERSION': release_version})

		print "Releasing version", release_version
		support.publish(local_iface.uri, set_released = 'today', set_version = release_version)

		support.backup_if_exists(release_version)
		os.mkdir(release_version)
		os.chdir(release_version)

		status.old_snapshot_version = local_impl.get_version()
		status.release_version = release_version
		status.head_at_release = scm.commit('Release %s' % release_version, branch = TMP_BRANCH_NAME, parent = 'HEAD')
		status.save()
	
	def set_to_snapshot(snapshot_version):
		assert snapshot_version.endswith('-post')
		support.publish(local_iface.uri, set_released = '', set_version = snapshot_version)
		scm.commit('Start development series %s' % snapshot_version, branch = TMP_BRANCH_NAME, parent = TMP_BRANCH_NAME)
		status.new_snapshot_version = scm.get_head_revision()
		status.save()
		
	def ensure_ready_to_release():
		if not options.master_feed_file:
			raise SafeException("Master feed file not set! Check your configuration")

		scm.ensure_committed()
		scm.ensure_versioned(os.path.abspath(local_iface.uri))
		info("No uncommitted changes. Good.")
		# Not needed for GIT. For SCMs where tagging is expensive (e.g. svn) this might be useful.
		#run_unit_tests(local_impl)

		scm.grep('\(^\\|[^=]\)\<\\(TODO\\|XXX\\|FIXME\\)\>')
	
	def create_feed(target_feed, local_iface_path, archive_file, archive_name, main):
		shutil.copyfile(local_iface_path, target_feed)

		support.publish(target_feed,
			set_main = main,
			archive_url = get_archive_url(options, status, os.path.basename(archive_file)),
			archive_file = archive_file,
			archive_extract = archive_name)
	
	def get_previous_release(this_version):
		"""Return the highest numbered verison in the master feed before this_version.
		@return: version, or None if there wasn't one"""
		parsed_release_version = model.parse_version(this_version)

		if os.path.exists(options.master_feed_file):
			master = model.Interface(os.path.realpath(options.master_feed_file))
			reader.update(master, master.uri, local = True)
			versions = [impl.version for impl in master.implementations.values() if impl.version < parsed_release_version]
			if versions:
				return model.format_version(max(versions))
		return None

	def export_changelog(previous_release):
		changelog = file('changelog-%s' % status.release_version, 'w')
		try:
			try:
				scm.export_changelog(previous_release, status.head_before_release, changelog)
			except SafeException, ex:
				print "WARNING: Failed to generate changelog: " + str(ex)
			else:
				print "Wrote changelog from %s to here as %s" % (previous_release or 'start', changelog.name)
		finally:
			changelog.close()
	
	def fail_candidate(archive_file):
		cwd = os.getcwd()
		assert cwd.endswith(status.release_version)
		support.backup_if_exists(cwd)
		scm.delete_branch(TMP_BRANCH_NAME)
		os.unlink(support.release_status_file)
		print "Restored to state before starting release. Make your fixes and try again..."

	def accept_and_publish(archive_file, archive_name, src_feed_name):
		assert options.master_feed_file

		if not options.archive_dir_public_url:
			raise SafeException("Archive directory public URL is not set! Edit configuration and try again.")

		if status.tagged:
			print "Already tagged in SCM. Not re-tagging."
		else:
			scm.ensure_committed()
			head = scm.get_head_revision() 
			if head != status.head_before_release:
				raise SafeException("Changes committed since we started!\n" +
						    "HEAD was " + status.head_before_release + "\n"
						    "HEAD now " + head)

			scm.tag(status.release_version, status.head_at_release)
			scm.reset_hard(TMP_BRANCH_NAME)
			scm.delete_branch(TMP_BRANCH_NAME)

			status.tagged = 'true'
			status.save()

		if status.updated_master_feed:
			print "Already added to master feed. Not changing."
		else:
			publish_opts = {}
			if os.path.exists(options.master_feed_file):
				# Check we haven't already released this version
				master = model.Interface(os.path.realpath(options.master_feed_file))
				reader.update(master, master.uri, local = True)
				existing_releases = [impl for impl in master.implementations.values() if impl.get_version() == status.release_version]
				if len(existing_releases):
					raise SafeException("Master feed %s already contains an implementation with version number %s!" % (options.master_feed_file, status.release_version))

				previous_release = get_previous_release(status.release_version)
				previous_testing_releases = [impl for impl in master.implementations.values() if impl.get_version() == previous_release
													     and impl.upstream_stability == model.stability_levels["testing"]]
				if previous_testing_releases:
					print "The previous release, version %s, is still marked as 'testing'. Set to stable?" % previous_release
					if support.get_choice(['Yes', 'No']) == 'Yes':
						publish_opts['select_version'] = previous_release
						publish_opts['set_stability'] = "stable"

			# Merge the source and binary feeds together first, so
			# that we update the master feed atomically and only
			# have to sign it once.
			shutil.copyfile(src_feed_name, 'merged.xml')
			for b in compiler.get_binary_feeds():
				support.publish('merged.xml', local = b)

			support.publish(options.master_feed_file, local = 'merged.xml', xmlsign = True, key = options.key, **publish_opts)
			os.unlink('merged.xml')

			status.updated_master_feed = 'true'
			status.save()

		# Copy files...
		uploads = [os.path.basename(archive_file)]
		for b in compiler.get_binary_feeds():
			stream = file(b)
			binary_feed = model.ZeroInstallFeed(qdom.parse(stream), local_path = b)
			stream.close()
			impl, = binary_feed.implementations.values()
			uploads.append(os.path.basename(impl.download_sources[0].url))

		upload_archives(options, status, uploads)

		assert len(local_iface.feed_for) == 1
		feed_base = os.path.dirname(local_iface.feed_for.keys()[0])
		feed_files = [options.master_feed_file]
		print "Upload %s into %s" % (', '.join(feed_files), feed_base)
		cmd = options.master_feed_upload_command.strip()
		if cmd:
			support.show_and_run(cmd, feed_files)
		else:
			print "NOTE: No feed upload command set => you'll have to upload them yourself!"

		print "Push changes to public SCM repository..."
		public_repos = options.public_scm_repository
		if public_repos:
			scm.push_head_and_release(status.release_version)
		else:
			print "NOTE: No public repository set => you'll have to push the tag and trunk yourself."

		os.unlink(support.release_status_file)
	
	if status.head_before_release:
		head = scm.get_head_revision() 
		if status.release_version:
			print "RESUMING release of %s %s" % (local_iface.get_name(), status.release_version)
		elif head == status.head_before_release:
			print "Restarting release of %s (HEAD revision has not changed)" % local_iface.get_name()
		else:
			raise SafeException("Something went wrong with the last run:\n" +
					    "HEAD revision for last run was " + status.head_before_release + "\n" +
					    "HEAD revision now is " + head + "\n" +
					    "You should revert your working copy to the previous head and try again.\n" +
					    "If you're sure you want to release from the current head, delete '" + support.release_status_file + "'")
	else:
		print "Releasing", local_iface.get_name()

	ensure_ready_to_release()

	if status.release_version:
		if not os.path.isdir(status.release_version):
			raise SafeException("Can't resume; directory %s missing. Try deleting '%s'." % (status.release_version, support.release_status_file))
		os.chdir(status.release_version)
		need_set_snapshot = False
		if status.tagged:
			print "Already tagged. Resuming the publishing process..."
		elif status.new_snapshot_version:
			head = scm.get_head_revision() 
			if head != status.head_before_release:
				raise SafeException("There are more commits since we started!\n"
						    "HEAD was " + status.head_before_release + "\n"
						    "HEAD now " + head + "\n"
						    "To include them, delete '" + support.release_status_file + "' and try again.\n"
						    "To leave them out, put them on a new branch and reset HEAD to the release version.")
		else:
			raise SafeException("Something went wrong previously when setting the new snapshot version.\n" +
					    "Suggest you reset to the original HEAD of\n%s and delete '%s'." % (status.head_before_release, support.release_status_file))
	else:
		set_to_release()	# Changes directory
		assert status.release_version
		need_set_snapshot = True

	# May be needed by the upload command
	os.environ['RELEASE_VERSION'] = status.release_version

	archive_name = support.make_archive_name(local_iface.get_name(), status.release_version)
	archive_file = archive_name + '.tar.bz2'

	export_prefix = archive_name
	if add_toplevel_dir is not None:
		export_prefix += '/' + add_toplevel_dir

	if status.created_archive and os.path.isfile(archive_file):
		print "Archive already created"
	else:
		support.backup_if_exists(archive_file)
		scm.export(export_prefix, archive_file, status.head_at_release)

		has_submodules = scm.has_submodules()

		if phase_actions['generate-archive'] or has_submodules:
			try:
				support.unpack_tarball(archive_file)
				if has_submodules:
					scm.export_submodules(archive_name)
				run_hooks('generate-archive', cwd = archive_name, env = {'RELEASE_VERSION': status.release_version})
				info("Regenerating archive (may have been modified by generate-archive hooks...")
				support.check_call(['tar', 'cjf', archive_file, archive_name])
			except SafeException:
				scm.reset_hard(scm.get_current_branch())
				fail_candidate(archive_file)
				raise

		status.created_archive = 'true'
		status.save()

	if need_set_snapshot:
		set_to_snapshot(status.release_version + '-post')
		# Revert back to the original revision, so that any fixes the user makes
		# will get applied before the tag
		scm.reset_hard(scm.get_current_branch())

	#backup_if_exists(archive_name)
	support.unpack_tarball(archive_file)

	extracted_iface_path = os.path.abspath(os.path.join(export_prefix, local_iface_rel_root_path))
	assert os.path.isfile(extracted_iface_path), "Local feed not in archive! Is it under version control?"
	extracted_iface = model.Interface(extracted_iface_path)
	reader.update(extracted_iface, extracted_iface_path, local = True)
	extracted_impl = support.get_singleton_impl(extracted_iface)

	if extracted_impl.main:
		# Find main executable, relative to the archive root
		abs_main = os.path.join(os.path.dirname(extracted_iface_path), extracted_impl.id, extracted_impl.main)
		main = support.relative_path(archive_name + '/', abs_main)
		if main != extracted_impl.main:
			print "(adjusting main: '%s' for the feed inside the archive, '%s' externally)" % (extracted_impl.main, main)
			# XXX: this is going to fail if the feed uses the new <command> syntax
		if not os.path.exists(abs_main):
			raise SafeException("Main executable '%s' not found after unpacking archive!" % abs_main)
		if main == extracted_impl.main:
			main = None	# Don't change the main attribute
	else:
		main = None

	try:
		if status.src_tests_passed:
			print "Unit-tests already passed - not running again"
		else:
			# Make directories read-only (checks tests don't write)
			support.make_readonly_recursive(archive_name)

			run_unit_tests(extracted_iface_path)
			status.src_tests_passed = True
			status.save()
	except SafeException:
		print "(leaving extracted directory for examination)"
		fail_candidate(archive_file)
		raise
	# Unpack it again in case the unit-tests changed anything
	ro_rmtree(archive_name)
	support.unpack_tarball(archive_file)

	# Generate feed for source
	stream = open(extracted_iface_path)
	src_feed_name = '%s.xml' % archive_name
	create_feed(src_feed_name, extracted_iface_path, archive_file, archive_name, main)
	print "Wrote source feed as %s" % src_feed_name

	# If it's a source package, compile the binaries now...
	compiler = compile.Compiler(options, os.path.abspath(src_feed_name))
	compiler.build_binaries()

	previous_release = get_previous_release(status.release_version)
	export_changelog(previous_release)

	if status.tagged:
		raw_input('Already tagged. Press Return to resume publishing process...')
		choice = 'Publish'
	else:
		print "\nCandidate release archive:", archive_file
		print "(extracted to %s for inspection)" % os.path.abspath(archive_name)

		print "\nPlease check candidate and select an action:"
		print "P) Publish candidate (accept)"
		print "F) Fail candidate (untag)"
		if previous_release:
			print "D) Diff against release archive for %s" % previous_release
			maybe_diff = ['Diff']
		else:
			maybe_diff = []
		print "(you can also hit CTRL-C and resume this script when done)"

		while True:
			choice = support.get_choice(['Publish', 'Fail'] + maybe_diff)
			if choice == 'Diff':
				previous_archive_name = support.make_archive_name(local_iface.get_name(), previous_release)
				previous_archive_file = '../%s/%s.tar.bz2' % (previous_release, previous_archive_name)

				# For archives created by older versions of 0release
				if not os.path.isfile(previous_archive_file):
					old_previous_archive_file = '../%s.tar.bz2' % previous_archive_name
					if os.path.isfile(old_previous_archive_file):
						previous_archive_file = old_previous_archive_file

				if os.path.isfile(previous_archive_file):
					support.unpack_tarball(previous_archive_file)
					try:
						support.show_diff(previous_archive_name, archive_name)
					finally:
						shutil.rmtree(previous_archive_name)
				else:
					# TODO: download it?
					print "Sorry, archive file %s not found! Can't show diff." % previous_archive_file
			else:
				break

	info("Deleting extracted archive %s", archive_name)
	shutil.rmtree(archive_name)

	if choice == 'Publish':
		accept_and_publish(archive_file, archive_name, src_feed_name)
	else:
		assert choice == 'Fail'
		fail_candidate(archive_file)
