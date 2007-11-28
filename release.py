# Copyright (C) 2007, Thomas Leonard
# See the README file for details, or visit http://0install.net.

import os, sys, subprocess, shutil, tarfile, tempfile
from zeroinstall import SafeException
from zeroinstall.injector import reader, model
from logging import info

import support
from scm import GIT

XMLNS_RELEASE = 'http://zero-install.sourceforge.net/2007/namespaces/0release'

valid_phases = ['commit-release', 'generate-archive']

TMP_BRANCH_NAME = '0release-tmp'

def run_unit_tests(impl):
	self_test = impl.metadata.get('self-test', None)
	if self_test is None:
		print "SKIPPING unit tests for %s (no 'self-test' attribute set)" % impl
		return
	self_test = os.path.join(impl.id, self_test)
	print "Running self-test:", self_test
	exitstatus = subprocess.call([self_test], cwd = os.path.dirname(self_test))
	if exitstatus:
		raise SafeException("Self-test failed with exit status %d" % exitstatus)

def do_release(local_iface, options):
	status = support.Status()
	local_impl = support.get_singleton_impl(local_iface)

	local_impl_dir = local_impl.id
	assert local_impl_dir.startswith('/')
	local_impl_dir = os.path.realpath(local_impl_dir)
	assert os.path.isdir(local_impl_dir)
	assert local_iface.uri.startswith(local_impl_dir + '/')
	local_iface_rel_path = local_iface.uri[len(local_impl_dir) + 1:]
	assert not local_iface_rel_path.startswith('/')
	assert os.path.isfile(os.path.join(local_impl_dir, local_iface_rel_path))

	phase_actions = {}
	for phase in valid_phases:
		phase_actions[phase] = []	# List of <release:action> elements

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
			else:
				warn("Unknown <release:management> element: %s", x)
	elif len(release_management) > 1:
		raise SafeException("Multiple <release:management> sections in %s!" % local_iface)
	else:
		info("No <release:management> element found in local feed.")

	scm = GIT(local_iface, options)

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
		scm.ensure_committed()
		scm.ensure_versioned(local_iface_rel_path)
		info("No uncommitted changes. Good.")
		# Not needed for GIT. For SCMs where tagging is expensive (e.g. svn) this might be useful.
		#run_unit_tests(local_impl)
	
	def create_feed(local_iface_stream, archive_file, archive_name):
		tmp = tempfile.NamedTemporaryFile(prefix = '0release-')
		shutil.copyfileobj(local_iface_stream, tmp)
		tmp.flush()

		support.publish(tmp.name,
			archive_url = options.archive_dir_public_url + '/' + os.path.basename(archive_file),
			archive_file = archive_file,
			archive_extract = archive_name)
		return tmp
	
	def unpack_tarball(archive_file, archive_name):
		tar = tarfile.open(archive_file, 'r:bz2')
		members = [m for m in tar.getmembers() if m.name != 'pax_global_header']
		tar.extractall('.', members = members)
	
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

	def export_changelog(previous_release = None):
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
		support.backup_if_exists(archive_file)
		scm.delete_branch(TMP_BRANCH_NAME)
		os.unlink(support.release_status_file)
		print "Restored to state before starting release. Make your fixes and try again..."
	
	def accept_and_publish(archive_file, archive_name, local_iface_rel_path):
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
			master = model.Interface(os.path.realpath(options.master_feed_file))
			reader.update(master, master.uri, local = True)
			existing_releases = [impl for impl in master.implementations.values() if impl.get_version() == status.release_version]
			if len(existing_releases):
				raise SafeException("Master feed %s already contains an implementation with version number %s!" % (options.master_feed_file, status.release_version))

			tar = tarfile.open(archive_file, 'r:bz2')
			stream = tar.extractfile(tar.getmember(archive_name + '/' + local_iface_rel_path))
			remote_dl_iface = create_feed(stream, archive_file, archive_name)
			stream.close()

			support.publish(options.master_feed_file, local = remote_dl_iface.name, xmlsign = True, key = options.key)
			remote_dl_iface.close()

			status.updated_master_feed = 'true'
			status.save()

		def is_uploaded(url, size):
			try:
				actual_size = support.get_size(url)
			except Exception, ex:
				print "Can't get size of '%s': %s" % (url, ex)
				return False
			else:
				if int(actual_size) == size:
					return True
				print "WARNING: %s exists, but size is %d, not %d!" % (url, actual_size, size)
				return False

		# Copy files...
		print
		archive_url = options.archive_dir_public_url + '/' + os.path.basename(archive_file)
		archive_size = os.path.getsize(archive_file)
		if status.uploaded_archive and is_uploaded(archive_url, archive_size):
			print "Archive already uploaded. Not uploading again."
		else:
			while True:
				print "Upload %s as %s" % (archive_file, archive_url)
				cmd = options.archive_upload_command.strip()
				if cmd:
					support.show_and_run(cmd, [archive_file])
				else:
					print "No upload command is set => please upload the archive manually now"
					raw_input('Press Return once archive is uploaded.')
				print
				if is_uploaded(archive_url, archive_size):
					print "OK, archive uploaded successfully"
					status.uploaded_archive = 'true'
					status.save()
					break
				print "** Archive still not uploaded! Try again..."
				if cmd:
					raw_input('Press Return to retry upload command.')

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
		set_to_release()
		assert status.release_version
		need_set_snapshot = True

	archive_name = support.make_archive_name(local_iface.get_name(), status.release_version)
	archive_file = archive_name + '.tar.bz2'

	if status.created_archive and os.path.isfile(archive_file):
		print "Archive already created"
	else:
		support.backup_if_exists(archive_file)
		scm.export(archive_name, archive_file, status.head_at_release)

		if phase_actions['generate-archive']:
			try:
				unpack_tarball(archive_file, archive_name)
				run_hooks('generate-archive', cwd = archive_name, env = {'RELEASE_VERSION': status.release_version})
				info("Regenerating archive (may have been modified by generate-archive hooks...")
				support.check_call(['tar', 'cjf', archive_file, archive_name])
			except SafeException:
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
	unpack_tarball(archive_file, archive_name)
	if local_impl.main:
		main = os.path.join(archive_name, local_impl.main)
		if not os.path.exists(main):
			raise SafeException("Main executable '%s' not found after unpacking archive!" % main)

	extracted_iface_path = os.path.abspath(os.path.join(archive_name, local_iface_rel_path))
	assert os.path.isfile(extracted_iface_path), "Local feed not in archive! Is it under version control?"
	extracted_iface = model.Interface(extracted_iface_path)
	reader.update(extracted_iface, extracted_iface_path, local = True)
	extracted_impl = support.get_singleton_impl(extracted_iface)

	try:
		run_unit_tests(extracted_impl)
	except SafeException:
		print "(leaving extracted directory for examination)"
		fail_candidate(archive_file)
		raise
	# Unpack it again in case the unit-tests changed anything
	shutil.rmtree(archive_name)
	unpack_tarball(archive_file, archive_name)

	previous_release = get_previous_release(status.release_version)
	export_changelog()

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
			previous_archive_file = previous_archive_name + '.tar.bz2'
			if os.path.isfile(previous_archive_file):
				unpack_tarball(previous_archive_file, previous_archive_name)
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
		accept_and_publish(archive_file, archive_name, local_iface_rel_path)
	else:
		assert choice == 'Fail'
		fail_candidate(archive_file)
