# Copyright (C) 2007, Thomas Leonard
# See the README file for details, or visit http://0install.net.

import os, subprocess
from zeroinstall import SafeException
from logging import info

class SCM:
	def __init__(self, local_iface, options):
		self.local_iface = local_iface
		self.options = options

class GIT(SCM):
	def _run(self, args, **kwargs):
		info("Running git %s", ' '.join(args))
		return subprocess.Popen(["git"] + args, cwd = os.path.dirname(self.local_iface.uri), **kwargs)
	
	def _run_check(self, args, **kwargs):
		child = self._run(args, **kwargs)
		code = child.wait()
		if code:
			raise SafeException("Git %s failed with exit code %d" % (repr(args), code))

	def _run_stdout(self, args, **kwargs):
		child = self._run(args, stdout = subprocess.PIPE, **kwargs)
		stdout, unused = child.communicate()
		if child.returncode:
			raise SafeException('Failed to get current branch! Exit code %d: %s' % (child.returncode, stdout))
		return stdout
	
	def ensure_versioned(self, path):
		"""Ensure path is a file tracked by the version control system.
		@raise SafeException: if file is not tracked"""
		out = self._run_stdout(['ls-tree', 'HEAD', path]).strip()
		if not out:
			raise SafeException("File '%s' is not under version control, according to git-ls-tree" % path)

	def reset_hard(self, revision):
		self._run_check(['reset', '--hard', revision])

	def ensure_committed(self):
		child = self._run(["status", "-a"], stdout = subprocess.PIPE)
		stdout, unused = child.communicate()
		if not child.returncode:
			raise SafeException('Uncommitted changes! Use "git-commit -a" to commit them. Changes are:\n' + stdout)
	
	def make_tag(self, version):
		return 'v' + version

	def tag(self, version, revision):
		tag = self.make_tag(version)
		if self.options.key:
			key_opts = ['-u', self.options.key]
		else:
			key_opts = []
		self._run_check(['tag', '-s'] + key_opts + ['-m', 'Release %s' % version, tag, revision])
		print "Tagged as %s" % tag
	
	def get_current_branch(self):
		current_branch = self._run_stdout(['symbolic-ref', 'HEAD']).strip()
		info("Current branch is %s", current_branch)
		return current_branch
	
	def delete_branch(self, branch):
		self._run_check(['branch', '-D', branch])

	def push_head_and_release(self, version):
		self._run_check(['push', self.options.public_scm_repository, self.make_tag(version), self.get_current_branch()])
	
	def ensure_no_tag(self, version):
		tag = self.make_tag(version)
		child = self._run(['tag', '-l', '-q', tag])
		code = child.wait()
		if code == 0:
			raise SafeException(("Release %s is already tagged! If you want to replace it, do\n" + 
						"git-tag -d %s") % (version, tag))
	
	def export(self, prefix, archive_file, revision):
		child = self._run(['archive', '--format=tar', '--prefix=' + prefix + '/', revision], stdout = subprocess.PIPE)
		subprocess.check_call(['bzip2', '-'], stdin = child.stdout, stdout = file(archive_file, 'w'))
		status = child.wait()
		if status:
			if os.path.exists(archive_file):
				os.unlink(archive_file)
			raise SafeException("git-archive failed with exit code %d" % status)
	
	def commit(self, message, branch, parent):
		self._run_check(['add', '-u'])		# Commit all changed tracked files to index
		tree = self._run_stdout(['write-tree']).strip()
		child = self._run(['commit-tree', tree, '-p', parent], stdin = subprocess.PIPE, stdout = subprocess.PIPE)
		stdout, unused = child.communicate(message)
		commit = stdout.strip()
		info("Committed as %s", commit)
		self._run_check(['branch', '-f', branch, commit])
		return commit
	
	def get_head_revision(self):
		proc = self._run(['rev-parse', 'HEAD'], stdout = subprocess.PIPE)
		stdout, unused = proc.communicate()
		if proc.returncode:
			raise Exception("git rev-parse failed with exit code %d" % proc.returncode)
		head = stdout.strip()
		assert head
		return head
	
	def export_changelog(self, last_release_version, head, stream):
		if last_release_version:
			self._run_check(['log', 'refs/tags/v' + last_release_version + '..' + head], stdout = stream)
		else:
			self._run_check(['log', head], stdout = stream)


def get_scm(local_iface, options):
	start_dir = os.path.dirname(os.path.abspath(local_iface.uri))
	current = start_dir
	while True:
		if os.path.exists(os.path.join(current, '.git')):
			return GIT(local_iface, options)
		parent = os.path.dirname(current)
		if parent == current:
			raise SafeException("Unable to determine which version control system is being used. Couldn't find .git in %s or any parent directory." % start_dir)
		current = parent
