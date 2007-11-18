# Copyright (C) 2007, Thomas Leonard
# See the README file for details, or visit http://0install.net.

import os, sys, subprocess, shutil, tarfile, tempfile
from zeroinstall import SafeException
from zeroinstall.injector import reader, model
from logging import info
from scm import GIT

XMLNS_RELEASE = 'http://zero-install.sourceforge.net/2007/namespaces/0release'

release_status_file = 'release-status'

valid_phases = ['commit-release']

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

def show_and_run(cmd, args):
	print "Executing: %s %s" % (cmd, ' '.join("[%s]" % x for x in args))
	subprocess.check_call(['sh', '-c', cmd, '-'] + args)

def suggest_release_version(snapshot_version):
	"""Given a snapshot version, suggest a suitable release version.
	>>> suggest_release_version('1.0-pre')
	'1.0'
	>>> suggest_release_version('0.9-post')
	'0.10'
	>>> suggest_release_version('3')
	Traceback (most recent call last):
		...
	SafeException: Version '3' is not a snapshot version (should end in -pre or -post)
	"""
	version = model.parse_version(snapshot_version)
	mod = version[-1]
	if mod == 0:
		raise SafeException("Version '%s' is not a snapshot version (should end in -pre or -post)" % snapshot_version)
	if mod > 0:
		# -post, so increment the number
		version[-2][-1] += 1
	version[-1] = 0	# Remove the modifier
	return model.format_version(version)

def publish(iface, **kwargs):
	args = [os.environ['0PUBLISH']]
	for k in kwargs:
		value = kwargs[k] 
		if value is True:
			args += ['--' + k.replace('_', '-')]
		elif value is not None:
			args += ['--' + k.replace('_', '-'), value]
	args.append(iface)
	info("Executing %s", args)
	subprocess.check_call(args)

def get_singleton_impl(iface):
	impls = iface.implementations
	if len(impls) != 1:
		raise SafeException("Local feed '%s' contains %d versions! I need exactly one!" % (iface.uri, len(impls)))
	return impls.values()[0]

def backup_if_exists(name):
	if not os.path.exists(name):
		return
	backup = name + '~'
	if os.path.exists(backup):
		print "(deleting old backup %s)" % backup
		if os.path.isdir(backup):
			shutil.rmtree(backup)
		else:
			os.unlink(backup)
	os.rename(name, backup)
	print "(renamed old %s as %s; will delete on next run)" % (name, backup)

class Status(object):
	__slots__ = ['old_snapshot_version', 'release_version', 'head_before_release', 'new_snapshot_version', 'head_at_release', 'created_archive', 'tagged']
	def __init__(self):
		for name in self.__slots__:
			setattr(self, name, None)

		if os.path.isfile(release_status_file):
			for line in file(release_status_file):
				assert line.endswith('\n')
				line = line[:-1]
				name, value = line.split('=')
				setattr(self, name, value)
				info("Loaded status %s=%s", name, value)

	def save(self):
		tmp_name = release_status_file + '.new'
		tmp = file(tmp_name, 'w')
		try:
			lines = ["%s=%s\n" % (name, getattr(self, name)) for name in self.__slots__ if getattr(self, name)]
			tmp.write(''.join(lines))
			tmp.close()
			os.rename(tmp_name, release_status_file)
			info("Wrote status to %s", release_status_file)
		except:
			os.unlink(tmp_name)
			raise

def get_choice(*options):
	while True:
		choice = raw_input('/'.join(options) + ': ').lower()
		if not choice: continue
		for o in options:
			if o.lower().startswith(choice):
				return o

def do_release(local_iface, options):
	status = Status()
	local_impl = get_singleton_impl(local_iface)

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

	scm = GIT(local_iface)

	def run_hooks(phase, cwd, env):
		info("Running hooks for phase '%s'" % phase)
		full_env = os.environ.copy()
		full_env.update(env)
		for x in phase_actions[phase]:
			print "[%s]: %s" % (phase, x)
			subprocess.check_call(x, shell = True, cwd = cwd, env = full_env)

	def set_to_release():
		print "Snapshot version is " + local_impl.get_version()
		suggested = suggest_release_version(local_impl.get_version())
		release_version = raw_input("Version number for new release [%s]: " % suggested)
		if not release_version:
			release_version = suggested

		scm.ensure_no_tag(release_version)

		status.head_before_release = scm.get_head_revision()
		status.save()

		working_copy = local_impl.id
		run_hooks('commit-release', cwd = working_copy, env = {'RELEASE_VERSION': release_version})

		print "Releasing version", release_version
		publish(local_iface.uri, set_released = 'today', set_version = release_version)

		status.old_snapshot_version = local_impl.get_version()
		status.release_version = release_version
		scm.commit('Release %s' % release_version)
		status.head_at_release = scm.get_head_revision()
		status.save()

		return release_version
	
	def set_to_snapshot(snapshot_version):
		assert snapshot_version.endswith('-post')
		publish(local_iface.uri, set_released = '', set_version = snapshot_version)
		scm.commit('Start development series %s' % snapshot_version)
		status.new_snapshot_version = scm.get_head_revision()
		status.save()
		
	def ensure_ready_to_release():
		scm.ensure_committed()
		info("No uncommitted changes. Good.")
		# Not needed for GIT. For SCMs where tagging is expensive (e.g. svn) this might be useful.
		#run_unit_tests(local_impl)
	
	def create_feed(local_iface_stream, archive_file, archive_name, version):
		tmp = tempfile.NamedTemporaryFile(prefix = '0release-')
		shutil.copyfileobj(local_iface_stream, tmp)
		tmp.flush()

		publish(tmp.name,
			archive_url = options.archive_dir_public_url + '/' + os.path.basename(archive_file),
			archive_file = archive_file,
			archive_extract = archive_name)
		return tmp
	
	def unpack_tarball(archive_file, archive_name):
		tar = tarfile.open(archive_file, 'r:bz2')
		members = [m for m in tar.getmembers() if m.name != 'pax_global_header']
		tar.extractall('.', members = members)
	
	def fail_candidate(archive_file):
		backup_if_exists(archive_file)
		head = scm.get_head_revision()
		if head != status.new_snapshot_version:
			raise SafeException("There have been commits since starting the release! Please rebase them onto %s" % status.head_before_release)
		# Check no uncommitted changes
		scm.ensure_committed()
		scm.reset_hard(status.head_before_release)
		os.unlink(release_status_file)
		print "Restored to state before starting release. Make your fixes and try again..."
	
	def accept_and_publish(archive_file, archive_name, local_iface_rel_path):
		assert options.master_feed_file

		if status.tagged:
			print "Already tagged and added to master feed."
		else:
			tar = tarfile.open(archive_file, 'r:bz2')
			stream = tar.extractfile(tar.getmember(archive_name + '/' + local_iface_rel_path))
			remote_dl_iface = create_feed(stream, archive_file, archive_name, version)
			stream.close()

			publish(options.master_feed_file, local = remote_dl_iface.name, xmlsign = True, key = options.key)
			remote_dl_iface.close()

			scm.tag(status.release_version, status.head_at_release)

			status.tagged = 'true'
			status.save()

		# Copy files...
		print "Upload %s as %s" % (archive_file, options.archive_dir_public_url + '/' + os.path.basename(archive_file))
		cmd = options.archive_upload_command.strip()
		if cmd:
			show_and_run(cmd, [archive_file])
		else:
			print "NOTE: No upload command set => you'll have to upload it yourself!"

		assert len(local_iface.feed_for) == 1
		feed_base = os.path.dirname(local_iface.feed_for.keys()[0])
		feed_files = [options.master_feed_file]
		print "Upload %s into %s" % (', '.join(feed_files), feed_base)
		cmd = options.master_feed_upload_command.strip()
		if cmd:
			show_and_run(cmd, feed_files)
		else:
			print "NOTE: No feed upload command set => you'll have to upload them yourself!"

		os.unlink(release_status_file)
	
	if status.head_before_release:
		head = scm.get_head_revision() 
		if status.release_version:
			print "RESUMING release of version %s" % status.release_version
		elif head == status.head_before_release:
			print "Restarting release (HEAD revision has not changed)"
		else:
			raise SafeException("Something went wrong with the last run:\n" +
					    "HEAD revision for last run was " + status.head_before_release + "\n" +
					    "HEAD revision now is " + head + "\n" +
					    "You should revert your working copy to the previous head and try again.\n" +
					    "If you're sure you want to release from the current head, delete '" + release_status_file + "'")

	print "Releasing", local_iface.get_name()

	ensure_ready_to_release()

	if status.release_version:
		version = status.release_version
		need_set_snapshot = False
		if status.new_snapshot_version:
			head = scm.get_head_revision() 
			if head != status.new_snapshot_version:
				print "WARNING: there are more commits since we tagged; they will not be included in the release!"
		else:
			raise SafeException("Something went wrong previously when setting the new snapshot version.\n" +
					    "Suggest you reset to the original HEAD of\n%s and delete '%s'." % (status.head_before_release, release_status_file))
	else:
		version = set_to_release()
		need_set_snapshot = True

	archive_name = local_iface.get_name().lower().replace(' ', '-') + '-' + version
	archive_file = archive_name + '.tar.bz2'

	if status.created_archive and os.path.isfile(archive_file):
		print "Archive already created"
	else:
		backup_if_exists(archive_file)
		scm.export(archive_name, archive_file)
		status.created_archive = 'true'
		status.save()

	if need_set_snapshot:
		set_to_snapshot(version + '-post')

	#backup_if_exists(archive_name)
	unpack_tarball(archive_file, archive_name)
	if local_impl.main:
		main = os.path.join(archive_name, local_impl.main)
		if not os.path.exists(main):
			raise SafeException("Main executable '%s' not found after unpacking archive!" % main)

	extracted_iface_path = os.path.abspath(os.path.join(archive_name, local_iface_rel_path))
	extracted_iface = model.Interface(extracted_iface_path)
	reader.update(extracted_iface, extracted_iface_path, local = True)
	extracted_impl = get_singleton_impl(extracted_iface)

	try:
		run_unit_tests(extracted_impl)
	except SafeException:
		print "(leaving extracted directory for examination)"
		fail_candidate(archive_file)
		raise
	# Unpack it again in case the unit-tests changed anything
	shutil.rmtree(archive_name)
	unpack_tarball(archive_file, archive_name)

	print "\nCandidate release archive:", archive_file
	print "(extracted to %s for inspection)" % os.path.abspath(archive_name)

	print "\nPlease check candidate and select an action:"
	print "P) Publish candidate (accept)"
	print "F) Fail candidate (untag)"
	print "(you can also hit CTRL-C and resume this script when done)"
	choice = get_choice('Publish', 'Fail')

	info("Deleting extracted archive %s", archive_name)
	shutil.rmtree(archive_name)

	if choice == 'Publish':
		accept_and_publish(archive_file, archive_name, local_iface_rel_path)
	else:
		assert choice == 'Fail'
		fail_candidate(archive_file)


if __name__ == "__main__":
    import doctest
    doctest.testmod()
