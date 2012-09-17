import sublime, sublime_plugin

import lib.util
import sys
# reload lib.util on update/reload of primary module
# so improvements will be loaded without a sublime restart
sys.modules['lib.util'] = reload(lib.util)
from lib.util import communicate, which

import os
import re
import shlex

INDENTATION = '  '

class BoundaryError(Exception): pass

def xiki(view):
	settings = view.settings()

	output = None
	cmd = None
	oldcwd = None
	if settings.get('xiki'):
		indent, sign, path, tag, tree = find_tree(view)

		pos = get_pos(view)
		if get_line(view, 1).startswith(indent + INDENTATION):
			if sign == '-':
				replace_line(view, pos, indent + '+ ' + tag)

			edit = view.begin_edit()
			cleanup(view, edit, pos, indent + INDENTATION)
			select(view, pos)
			view.end_edit(edit)
			return
		elif sign == '$':
			if path:
				oldcwd = os.getcwd()

				# maybe this should be offloaded into find_tree
				# so path will be multiple directories instead of just a base dir
				path_re = r'^(.+)/%s$' % re.escape(tag)
				match = re.match(path_re, tree)
				if match:
					os.chdir(os.path.join(path, match.group(1)))
				else:
					os.chdir(path)

			cmd = shlex.split(tag.encode('ascii', 'replace'), True)
		elif path:
			# directory listing or file open
			target = os.path.join(path, tree)
			if os.path.isfile(target):
				sublime.active_window().open_file(target)
				return
			elif os.path.isdir(target):
				dirs = ''
				files = ''
				listing = []
				try:
					listing = os.listdir(target)
				except OSError, err:
					dirs = '- ' + err.strerror + '\n'

				for entry in listing:
						absolute = os.path.join(target, entry)
						if os.path.isdir(absolute):
							dirs += '+ %s/\n' % entry
						else:
							files += '%s\n' % entry

				output = (dirs + files) or '\n'
		elif sign == '-':
			# dunno here
			return
		elif tree:
			if which('ruby'):
				cmd = ['ruby', which('xiki')]
			else:
				cmd = ['xiki']

			cmd += tree.split(' ')

		if cmd:
			output = communicate(cmd, None, 3, return_error=True)
			if oldcwd:
				os.chdir(oldcwd)

		if output:
			if sign == '+':
				replace_line(view, pos, indent + '- ' + tag)

			insert(view, output, indent + INDENTATION)

def find_tree(view):
	regex = re.compile(r'^(\s*)([-+$]\s*)?(.*)$')

	view.run_command('single_selection')
	line = get_line(view)
	match = regex.match(line)

	line_indent = last_indent = match.group(1)
	sign = (match.group(2) or '').strip()
	tag = match.group(3)
	tree = [tag]
	if tag.startswith('/'):
		sign = '/'

	offset = -1
	while last_indent != '':
		try:
			line = get_line(view, offset)
		except BoundaryError:
			break

		offset -= 1

		match = regex.match(line)
		if match:
			indent = match.group(1)
			part = match.group(3)

			if len(indent) < len(last_indent) and part:
				last_indent = indent
				tree.insert(0, part)

	new_tree = []
	path = None
	for part in reversed(tree):
		if part.startswith('@'):
			new_tree.insert(0, part.strip('@'))
		elif part.startswith('/'):
			path = part
		elif part.startswith('~'):
			path = os.path.expanduser(part)
		else:
			new_tree.insert(0, part)
			continue

		break

	return line_indent, sign, path, tag, '/'.join(new_tree).replace('//', '/')

# helpers

def replace_line(view, point, text):
	text = text.rstrip()
	line = view.full_line(point)

	edit = view.begin_edit()
	view.insert(edit, line.b, text + '\n')
	view.erase(edit, line)
	view.end_edit(edit)

def get_pos(view):
	cursor = view.sel()[0].b
	return view.line(cursor).b

def cleanup(view, edit, pos, indent):
	line, _ = view.rowcol(pos)

	append_newline = False
	while True:
		point = view.text_point(line + 1, 0)
		region = view.full_line(point)
		if region.a == region.b:
			break

		text = view.substr(region)
		if text.startswith(indent):
			view.erase(edit, region)
		elif not text.strip():
			view.erase(edit, region)
			append_newline = True
		else:
			break

	if append_newline:
		point = view.line(point).a
		view.insert(edit, point, '\n')

def insert(view, text, indent=''):
	line_end = get_pos(view)

	edit = view.begin_edit()
	cleanup(view, edit, line_end, indent)

	for line in reversed(text.split('\n')):
		view.insert(edit, line_end, '\n' + indent + line)

	select(view, line_end)
	view.end_edit(edit)

def get_line(view, offset=0):
	row, _ = view.rowcol(get_pos(view))

	point = view.text_point(row + offset, 0)
	if row + offset < 0:
		raise BoundaryError

	line = view.line(point)
	return view.substr(line).strip('\r\n')

def select(view, point):
	view.sel().clear()
	view.sel().add(sublime.Region(point, point))

# sublime commands

class Xiki(sublime_plugin.WindowCommand):
	def run(self):
		view = self.window.active_view()
		xiki(view)

	def is_enabled(self):
		view = self.window.active_view()
		if view.settings().get('xiki'):
			return True

class NewXiki(sublime_plugin.WindowCommand):
	def run(self):
		view = self.window.new_file()
		view.settings().set('xiki', True)

class XikiClick(sublime_plugin.WindowCommand):
	def run(self):
		view = self.window.active_view()
		if view.settings().get('xiki'):
			xiki(view)
		else:
			# emulate the default double-click behavior
			# if we're not in a xiki buffer
			view.run_command('expand_selection', {'to': 'word'})
