import sublime, sublime_plugin
from lib.util import communicate, which

import re

def xiki(view):
	settings = view.settings()

	if settings.get('xiki'):
		indent, sign, tag, tree = find_tree(view)
		if not tree: return
		print 'xiki', repr(indent), sign, tree

		pos = get_pos(view)
		if sign == '+':
			replace_line(view, pos, indent + '- ' + tag)

		if get_line(view, 1).startswith(indent + '\t'):
			if sign == '-':
				replace_line(view, pos, indent + '+ ' + tag)

			edit = view.begin_edit()
			cleanup(view, edit, pos, indent + '\t')
			select(view, pos)

			view.end_edit(edit)
			return

		cmd = ['ruby', which('xiki')] + tree.split(' ')
		print cmd
		output = communicate(cmd)
		if output:
			insert(view, output, indent + '\t')

def find_tree(view):
	view.run_command('single_selection')
	line = get_line(view)
	match = re.match('^(\s*)(\+ |- )?(.*)$', line)
	line_indent = last_indent = match.group(1)
	sign = (match.group(2) or '').strip()
	tag = match.group(3)
	tree = [tag]

	offset = -1
	while last_indent != '':
		line = get_line(view, offset)
		offset -= 1

		match = re.match('^(\s*)(\+ |- )?(.*)$', line)
		if match:
			indent = match.group(1)
			tag = match.group(3)

			if len(indent) < len(last_indent) and tag:
				last_indent = indent
				tree.insert(0, tag.strip('/'))

	new_tree = []
	for tag in reversed(tree):
		if tag.startswith('@'):
			new_tree.insert(0, tag.strip('@'))
			break

		new_tree.insert(0, tag)

	return line_indent, sign, tree[-1], '/'.join(new_tree)

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
	assert row + offset >= 0

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
